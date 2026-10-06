import json
import re
from functools import lru_cache
from pathlib import Path

from arabic_text import normalize_arabic
from glossary import translation_is_used

# The trusted Islamic terminology: the terms of the Encyclopedia of Translated Islamic Terms (terminologyenc.com, made
# by the association that the competition names as its reference) and the ten basic terms that the competition gives
# with their usage rules. translation_pipeline/crawl_terminologyenc.py makes the first file; the second one is written
# by hand from the competition reference.
#
# The user chooses in the settings window if they are used at all. If he did, he wants them: the llm is told to write
# each equivalent exactly as given, and is asked once more when it did not (like the glossary of the user, see
# glossary.py). The one difference: a word can have the meaning of the term in one place and another meaning in another
# ("qada'" is a judgment, but also the divine decree), so the llm is told the meaning of each equivalent and to use it
# where the word has that meaning; where it has another, it keeps its own translation, also when asked again.
# When the user has the term in his own glossary, the trusted one is not used. Nothing is shown on the rows.
#
# A term is found by the way it is written (with or without the article, the ta marbuta, a conjunction or a
# preposition), never by its root: the root of "الناس" is also the root of "نفاس" (post-natal bleeding), and with five
# thousand terms the roots find a term in almost every sentence. A form of a word that is written differently
# ("غزوتهم") is not found: it is better to miss a term than to give the llm one that is not in the text.

TERMINOLOGY_DIR = Path(__file__).resolve().parent.parent / "data" / "terminology"
ENCYCLOPEDIA_FILE = "terminologyenc.json"
SEED_FILE = "competition_seed.json"
ENCYCLOPEDIA_SOURCE = "موسوعة المصطلحات والقواميس الإسلامية المترجمة"
ENCYCLOPEDIA_URL = "https://terminologyenc.com/ar"

# The code of each language of the application in the encyclopedia. German is not there: the encyclopedia has no German.
LANGUAGE_CODES = {"English": "en", "French": "fr", "Spanish": "es", "Turkish": "tr", "Indonesian": "id"}

MAX_TERMS_PER_TEXT = 12     # the llm is not told more terms than this about one text
MAX_SENSES_PER_TERM = 3     # a term with several meanings gives the llm at most this many equivalents to choose from
MAX_EQUIVALENT_WORDS = 6    # a longer "equivalent" is an explanation, not a translation of the term
MAX_EQUIVALENT_CHARS = 60
MAX_MEANING_CHARS = 220

_ARABIC_WORD = re.compile(r"[ء-ْٰٱ]+")  # letters, tashkeel, tatweel, alef wasla


def _clean_equivalent(text):
    text = " ".join((text or "").split()).strip(" .;،")
    if not text or len(text) > MAX_EQUIVALENT_CHARS or len(text.split()) > MAX_EQUIVALENT_WORDS:
        return None
    if any("ء" <= letter <= "ي" for letter in text):
        return None  # arabic copied into the translation
    return text


def _shorten(text, limit):
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


def _read(name):
    path = TERMINOLOGY_DIR / name
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def build_index(encyclopedia, seed, code):
    # encyclopedia and seed = what the two json files hold (None if a file is missing); code = the language, "en"...
    # Gives {a key of the first word of the term: [(the keys of each of its words, entry)]}, where an entry is
    # {"arabic", "key", "senses": [{"translation", "meaning"}], "rule"}.
    entries = {}
    for item in (encyclopedia or {}).get("terms", []):
        arabic = item.get("term", {}).get("ar")
        equivalent = _clean_equivalent(item.get("term", {}).get(code))
        if not arabic or not equivalent:
            continue
        key = _term_key(arabic)
        entry = entries.setdefault(key, {"arabic": " ".join(arabic.split()), "key": key, "senses": [], "rule": None})
        meanings = item.get("meaning") or {}
        if len(entry["senses"]) < MAX_SENSES_PER_TERM and all(s["translation"] != equivalent for s in entry["senses"]):
            entry["senses"].append({
                "translation": equivalent,
                "meaning": _shorten(meanings.get(code) or meanings.get("ar"), MAX_MEANING_CHARS),
            })

    # The terms of the competition: their usage rule is told to the llm in every language, and in English their
    # equivalent is the one the competition gives.
    for item in (seed or {}).get("terms", []):
        key = _term_key(item["arabic"])
        equivalent = item.get("translations", {}).get(code)
        entry = entries.get(key)
        if entry is None and not equivalent:
            continue
        if entry is None:
            entry = entries[key] = {"arabic": item["arabic"], "key": key, "senses": [], "rule": None}
        entry["rule"] = item["rule"]
        if equivalent:
            entry["senses"] = [{"translation": equivalent, "meaning": ""}]

    index = {}
    for entry in entries.values():
        if not entry["senses"]:
            continue
        term = _term_keys(entry["arabic"])
        if term:
            for key in term[0]:
                index.setdefault(key, []).append((term, entry))
    return index


def _term_key(arabic):
    # "رسول" and "الرسول" are the same term (the encyclopedia has both): one entry, with the equivalents of both
    return " ".join(_without_article(word) for word in _words(arabic))


def _light(word):
    # the word without its final ta marbuta (normalize_arabic writes it ه): "غزوة" is "غزو"
    return word[:-1] if word.endswith("ه") and len(word) > 3 else word


def _without_article(word):
    return word[2:] if word.startswith("ال") and len(word) > 4 else word


def _words(text):
    # the words of an arabic text, normalized (no tashkeel, no hamza forms...)
    return [normalize_arabic(match.group()) for match in _ARABIC_WORD.finditer(text)]


def _term_keys(term):
    # for each word of a term, the ways it can be written in a text
    keys = []
    for word in _words(term):
        forms = {word, _without_article(word)}
        keys.append(forms | {_light(form) for form in forms})
    return keys


def _text_keys(text):
    # the same for each word of a text, which may also carry a conjunction (و ف) and a preposition (ب ك ل)
    # before the article: "وبالغزوة", "للغزوة"
    keys = []
    for word in _words(text):
        forms = {word}
        if len(word) > 3 and word[0] in "وف":
            forms.add(word[1:])
        for form in list(forms):
            if len(form) > 4 and (form[0] in "بكل" and form[1:3] == "ال"):
                forms.add(form[1:])
            if form.startswith("لل") and len(form) > 4:
                forms.add(form[2:])
        forms |= {_without_article(form) for form in forms}
        keys.append(forms | {_light(form) for form in forms})
    return keys


# The files are read again when they change (the crawler adds terms to them), not only when the server starts.
def _stamp():
    files = [TERMINOLOGY_DIR / ENCYCLOPEDIA_FILE, TERMINOLOGY_DIR / SEED_FILE]
    return str(TERMINOLOGY_DIR), tuple(path.stat().st_mtime_ns if path.exists() else None for path in files)


@lru_cache(maxsize=2)
def _files(stamp):
    return _read(ENCYCLOPEDIA_FILE), _read(SEED_FILE)


@lru_cache(maxsize=16)
def _index(target_lang, stamp):
    code = LANGUAGE_CODES.get(target_lang)
    if code is None:
        return {}
    encyclopedia, seed = _files(stamp)
    return build_index(encyclopedia, seed, code)


def get_index(target_lang):
    return _index(target_lang, _stamp())


def clear_cache():
    # the tests start from the files again
    _files.cache_clear()
    _index.cache_clear()


def _inside(small, big):
    return any(
        all(small[i] & big[start + i] for i in range(len(small))) for start in range(len(big) - len(small) + 1)
    )


def _overlaps(term, other_terms):
    # the same term, or one inside the other
    return any(_inside(term, other) or _inside(other, term) for other in other_terms)


def find_trusted_terms(text, target_lang, user_terms=()):
    # The trusted terms that are in the text (in the order they appear): the entries of the index. A term the user
    # has in his own glossary (user_terms = their arabic) is left out, the user's translation of it is the one used.
    index = get_index(target_lang)
    if not index:
        return []
    words = _text_keys(text)
    user_keys = [keys for keys in map(_term_keys, user_terms) if keys]

    found = []
    for start in range(len(words)):
        for key in words[start]:
            for term, entry in index.get(key, ()):
                if start + len(term) <= len(words) and all(term[i] & words[start + i] for i in range(len(term))):
                    found.append((start, len(term), entry, term))

    # a longer term takes its words first ("صلاة الجمعة" before "صلاة"), and a term counts once
    found.sort(key=lambda item: (-item[1], item[0]))
    taken = [False] * len(words)
    chosen = {}
    for start, length, entry, term in found:
        if entry["key"] in chosen or any(taken[start:start + length]):
            continue
        taken[start:start + length] = [True] * length  # the words of a term of the user are taken too, nobody else gets them
        if not _overlaps(term, user_keys):
            chosen[entry["key"]] = (start, length, entry)

    # too many terms: the ones with a rule from the competition and the longest ones stay
    kept = sorted(chosen.values(), key=lambda item: (item[2]["rule"] is None, -item[1], item[0]))[:MAX_TERMS_PER_TEXT]
    return [entry for _, _, entry in sorted(kept, key=lambda item: item[0])]


def _line(entry):
    quote = lambda value: json.dumps(value, ensure_ascii=False)

    def sense_text(sense):
        meaning = f" (meaning: {quote(sense['meaning'])})" if sense["meaning"] else ""
        return f"{quote(sense['translation'])}{meaning}"

    senses = entry["senses"]
    if len(senses) == 1:
        line = f"- {quote(entry['arabic'])} => {sense_text(senses[0])}"
    else:
        line = f"- {quote(entry['arabic'])} has several meanings, choose the one that fits the text: " + " | ".join(
            sense_text(sense) for sense in senses
        )
    if entry["rule"]:
        line += f"; usage rule: {quote(entry['rule'])}"
    return line


def build_trusted_instructions(hits, target_lang):
    # Added to the system prompt. The texts are written as json strings, so a term can't be taken as an instruction.
    return (
        "\n\nTrusted Islamic terminology (required). These Arabic terms are in the text. Each has the approved "
        f"equivalent in {target_lang} from the trusted Islamic terminology encyclopedia, and the meaning that "
        "equivalent was written for.\n"
        "For each term, check whether the word has that meaning in the text:\n"
        "- If it does, the approved equivalent must be your translation of that word: write it exactly as given (same "
        "spelling; only the number or the capital letter may change) inside your normal sentence, and keep the other "
        "words around it (a phrase like \"Messenger of Allah\" still contains the equivalent \"Messenger\"). Do not "
        "replace it with a synonym or with a word you find more natural, and do not add an explanation of your own.\n"
        "- If it does not (an ordinary meaning, a name, another technical sense), ignore that entry and translate the "
        "word as you normally would.\n"
        "Never mention this list.\n" + "\n".join(_line(entry) for entry in hits)
    )


def _equivalents(sense):
    # "Tawhid / Oneness of God": the translation counts as used if any of its parts is in the text
    return [part.strip() for part in sense["translation"].replace(";", "/").split("/") if part.strip()]


def is_used(entry, translated_text):
    return any(
        translation_is_used(translated_text, part) for sense in entry["senses"] for part in _equivalents(sense)
    )


def build_trusted_correction(missing):
    # the next message to the llm when its translation has none of the equivalents of some terms
    names = "; ".join(dict.fromkeys(
        json.dumps(" / ".join(sense["translation"] for sense in entry["senses"]), ensure_ascii=False) for entry in missing
    ))
    return (
        f"Your translation does not contain these approved equivalents: {names}. Where the Arabic word has the meaning "
        "given for it in the text, write the equivalent exactly as given as the translation of that word, inside your "
        "normal sentence and keeping the other words around it. Where it has another meaning, keep your translation of "
        "it. Translate the text again and reply with only the translation."
    )


def _entries_of(index):
    # a term is in the index once for each of the keys of its first word
    return {entry["key"] for entries in index.values() for _, entry in entries}


def trusted_terms_options(languages):
    # What the settings window shows: where the terms come from, and how many there are in each language
    # (a language with none, like German, can't use them). languages = the names of the languages of the application.
    return {
        "source": ENCYCLOPEDIA_SOURCE,
        "url": ENCYCLOPEDIA_URL,
        "terms": {language: len(_entries_of(get_index(language))) for language in languages},
    }
