import contextlib
import contextvars
import json
import os
import re
import time
from pathlib import Path

from dotenv import load_dotenv

# The models the translation and the assistant can use. The prompts are the same for every model; this module is
# the only place that knows how each provider is called. The keys are read from the .env file (or the environment)
# on the server and never leave it: OPENAI_API_KEY and COHERE_API_KEY.
# The .env of the project root is read by its path (not by where the server was started) and it wins over the
# environment, so the key written there is the one used.
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(ENV_FILE, override=True)

PROVIDERS = {
    "openai": {"label": "OpenAI", "key_name": "OPENAI_API_KEY"},
    "cohere": {"label": "Cohere", "key_name": "COHERE_API_KEY"},
}
DEFAULT_MODEL = {"provider": "openai", "model": "gpt-4o-mini"}

# The models the settings window shows (not every model of the provider). The names are exactly as the providers
# write them; the note is what the user reads. A model the provider does not list for this key is not shown.
# To offer another model, add it here.
RECOMMENDED_MODELS = {
    "openai": [
        {"id": "gpt-4o-mini", "note": "الأرخص والأسرع، وهو الافتراضي"},
        {"id": "gpt-4.1", "note": "جودة أعلى في النصوص الطويلة وتعدد اللغات"},
        {"id": "gpt-5", "note": "الأعلى جودة، وهو أبطأ وأغلى"},
    ],
    "cohere": [
        {"id": "command-a-plus-05-2026", "note": "موديل Cohere الرئيسي، اختاره Amr للترجمة"},
        {"id": "command-a-translate-08-2025", "note": "مخصص للترجمة (سياقه 8000 token فقط)"},
        {"id": "command-a-03-2025", "note": "الإصدار السابق من Command A، سياق طويل"},
        {"id": "c4ai-aya-expanse-32b", "note": "متعدد اللغات ويدعم العربية"},
        {"id": "command-r7b-12-2024", "note": "صغير ورخيص وسريع"},
    ],
}
# Used even if the provider's own list can't be read.
KNOWN_MODELS = {provider: [item["id"] for item in items] for provider, items in RECOMMENDED_MODELS.items()}

# The longest text (in characters) we send in one question to a model with a small context window; a longer
# paragraph is cut into pieces that are translated one by one (see split_into_chunks in arabic_text.py).
# command-a-translate reads 8000 tokens in all (the question and its answer); arabic takes about 2 characters
# for a token, so 1500 characters leave room for the answer.
MAX_INPUT_CHARS = {"command-a-translate-08-2025": 1500}

# When a model does not answer, the question goes to these (the plain, safe model of each provider).
FALLBACK_MODEL = {"openai": "gpt-4o-mini", "cohere": "command-a-plus-05-2026"}
MAX_ATTEMPTS = 3  # the chosen model and two others, never more
REQUEST_TIMEOUT_SECONDS = 60  # a model that is silent for this long has failed
FAILURE_MEMORY_SECONDS = 60  # a model that failed is not tried again for a minute (the next questions don't wait for it)

# Models that are not for chat (sound, images, search, embeddings...) are left out of the list of OpenAI.
NOT_CHAT_WORDS = (
    "embedding", "whisper", "tts", "dall-e", "audio", "realtime", "transcribe", "moderation",
    "image", "davinci", "babbage", "search", "sora", "codex",
)
MODEL_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}")
LIST_CACHE_SECONDS = 600

_cohere_client = None
_models_cache = {}  # provider -> (time it was read, [model names the provider has])
_recent_failures = {}  # (provider, model) -> time it failed
_fallback_log = contextvars.ContextVar("fallback_log", default=None)


def has_key(provider):
    # .env is read again each time, so a key added while the server is running is seen without a restart
    load_dotenv(ENV_FILE, override=True)
    return bool(os.environ.get(PROVIDERS[provider]["key_name"], "").strip())


def get_cohere_client():
    global _cohere_client
    if _cohere_client is None:
        if not has_key("cohere"):
            raise ValueError("no api key for cohere: add COHERE_API_KEY to the .env file")
        import cohere  # only needed when Cohere is used

        _cohere_client = cohere.ClientV2(os.environ["COHERE_API_KEY"])
    return _cohere_client


def read_cohere_text(response):
    # the answer is a list of parts; a model that thinks first gives its thoughts (no .text) before the text
    parts = getattr(response.message, "content", None) or getattr(response.message, "contents", None) or []
    texts = [part.text for part in parts if getattr(part, "text", None)]
    if not texts:
        raise ValueError("the llm answer is empty")
    return texts[-1]


# ---------- one question, with other models ready ----------

def max_input_chars(model):
    # the longest text this model can be asked about in one question, or None if it has no small limit
    return MAX_INPUT_CHARS.get((model or DEFAULT_MODEL)["model"])


def forget_failures():
    _recent_failures.clear()


@contextlib.contextmanager
def track_fallbacks():
    # Collects the switches of model made while a request is answered:
    #   with track_fallbacks() as fallbacks: ...   -> [{"from": "gpt-5", "to": "gpt-4o-mini", "reason": "..."}]
    log = []
    token = _fallback_log.set(log)
    try:
        yield log
    finally:
        _fallback_log.reset(token)


def _note_fallback(failed, replacement, reason):
    log = _fallback_log.get()
    if log is not None:
        log.append({"from": failed["model"], "to": replacement["model"], "reason": reason[:160]})


def fallback_chain(choice):
    # the models to try, in order: the chosen one, the safe one of its provider, the safe one of the other provider
    first = choice or DEFAULT_MODEL
    chain = [first]
    own_safe = {"provider": first["provider"], "model": FALLBACK_MODEL[first["provider"]]}
    if own_safe not in chain and has_key(first["provider"]):
        chain.append(own_safe)
    for provider in PROVIDERS:
        if provider != first["provider"] and has_key(provider):
            chain.append({"provider": provider, "model": FALLBACK_MODEL[provider]})
    return chain[:MAX_ATTEMPTS]


def _failed_recently(candidate):
    failed_at = _recent_failures.get((candidate["provider"], candidate["model"]))
    return failed_at is not None and time.time() - failed_at < FAILURE_MEMORY_SECONDS


def _ask_once(openai_client, messages, candidate, json_output):
    extra = {"response_format": {"type": "json_object"}} if json_output else {}
    if candidate["provider"] == "cohere":
        response = get_cohere_client().chat(
            model=candidate["model"], messages=messages,
            request_options={"timeout_in_millis": REQUEST_TIMEOUT_SECONDS * 1000}, **extra,
        )
        text = read_cohere_text(response)
    else:
        response = openai_client.chat.completions.create(
            model=candidate["model"], messages=messages, timeout=REQUEST_TIMEOUT_SECONDS, **extra
        )
        text = response.choices[0].message.content
    if not text or not text.strip():
        raise ValueError("the llm answer is empty")
    if json_output:
        json.loads(text)  # an answer that is not json counts as a failure, so another model is tried
    return text


def chat_text(openai_client, messages, model=None, json_output=False):
    # One question to a model, the answer as text. model = {"provider", "model"}, or None for the default one.
    # openai_client is the client the caller already has (so the callers keep one client each).
    # If the model fails (an error, no answer in time, an empty answer, or not json when json is asked) the next
    # model of fallback_chain answers instead; the switch is told to track_fallbacks(). Only when every model
    # failed there is an error (ValueError, a message for the user).
    chain = fallback_chain(model)
    attempts = [candidate for candidate in chain if not _failed_recently(candidate)] or chain
    if attempts[0] != chain[0]:
        _note_fallback(chain[0], attempts[0], "it failed a moment ago")

    last_error = None
    for number, candidate in enumerate(attempts):
        try:
            return _ask_once(openai_client, messages, candidate, json_output)
        except Exception as error:  # noqa: BLE001 - any failure of a provider means "try the next model"
            last_error = error
            _recent_failures[(candidate["provider"], candidate["model"])] = time.time()
            if number + 1 < len(attempts):
                _note_fallback(candidate, attempts[number + 1], f"{type(error).__name__}: {error}")
    raise ValueError(f"the models are not answering: {type(last_error).__name__}: {last_error}"[:300])


# ---------- the models the user can choose ----------

def _fetch_models(provider):
    # asks the provider which models this key can use
    if provider == "cohere":
        listed = get_cohere_client().models.list(endpoint="chat", page_size=1000)
        return [item.name for item in listed.models]

    from openai import OpenAI  # a new client: this is not a question to a model

    names = [item.id for item in OpenAI().models.list()]
    return [name for name in names if not any(word in name.lower() for word in NOT_CHAT_WORDS)]


def provider_models(provider):
    # every chat model the provider says this key can use (kept for 10 minutes)
    cached = _models_cache.get(provider)
    if cached and time.time() - cached[0] < LIST_CACHE_SECONDS:
        return cached[1]
    fetched = sorted(set(_fetch_models(provider)))
    _models_cache[provider] = (time.time(), fetched)
    return fetched


def list_models(provider):
    # every model that can be used: the recommended ones first, then the others of the provider
    live = provider_models(provider)
    return KNOWN_MODELS[provider] + [name for name in live if name not in KNOWN_MODELS[provider]]


def model_options():
    # What the settings window shows: for every provider, whether its key is on the server and the recommended
    # models it has. If the list of the provider can't be read, the recommended ones are shown without the check.
    options = []
    for provider, info in PROVIDERS.items():
        entry = {"provider": provider, "label": info["label"], "has_key": has_key(provider), "models": [], "list_failed": False}
        if entry["has_key"]:
            try:
                live = set(provider_models(provider))
                entry["models"] = [item for item in RECOMMENDED_MODELS[provider] if item["id"] in live]
            except Exception:  # no internet, a wrong key, a limit...
                entry["models"] = list(RECOMMENDED_MODELS[provider])
                entry["list_failed"] = True
        options.append(entry)
    return options


def resolve_model(choice):
    # The model the front asked for, checked: {"provider", "model"} or None for the default one.
    # Raises ValueError (a message for the user) when it can't be used.
    if choice is None:
        return None
    provider, name = choice.get("provider"), choice.get("model", "")
    if provider not in PROVIDERS:
        raise ValueError(f"unknown model provider: {provider}")
    if not MODEL_NAME_PATTERN.fullmatch(name):
        raise ValueError("the model name is not valid")
    if not has_key(provider):
        raise ValueError(f"no api key for {provider}: add {PROVIDERS[provider]['key_name']} to the .env file")
    if name not in KNOWN_MODELS[provider]:
        try:
            available = list_models(provider)
        except Exception:
            available = []
        if name not in available:
            raise ValueError(f"the model {name} is not available for {provider}")
    return {"provider": provider, "model": name}
