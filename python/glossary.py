import json
import re

from nltk.stem.isri import ISRIStemmer

from arabic_text import normalize_arabic

# The glossary of the user: Arabic terms and the translation he wants for each one (in the language he translates to).
# The front keeps it (in the browser) and sends it with every translation; this module checks it, finds the terms
# in a text and builds what the llm is told. An entry is {"arabic": "حي بن يقظان", "translation": "Hay bin Yaqdhan"}.

MAX_TERMS = 2000
MAX_ARABIC_CHARS = 100
MAX_TRANSLATION_CHARS = 200

_stemmer = ISRIStemmer()
_ARABIC_LETTER = re.compile(r"[ء-ي]")
_ARABIC_WORD = re.compile(r"[ء-ْٰٱ]+")  # letters, tashkeel, tatweel, alef wasla


def clean_glossary(entries):
    # The glossary comes from the browser, so it is checked again here. Gives the entries without
    # extra spaces and without repeated terms, or raises ValueError with a message for the user.
    if len(entries) > MAX_TERMS:
        raise ValueError(f"the glossary has more than {MAX_TERMS} terms")

    cleaned = []
    seen = set()
    for number, entry in enumerate(entries, start=1):
        arabic = entry["arabic"].strip()
        translation = entry["translation"].strip()
        if not _ARABIC_LETTER.search(arabic):
            raise ValueError(f"glossary term {number}: the term must be written in arabic")
        if not translation:
            raise ValueError(f"glossary term {number}: the translation is empty")
        if len(arabic) > MAX_ARABIC_CHARS or len(translation) > MAX_TRANSLATION_CHARS:
            raise ValueError(f"glossary term {number}: the term or its translation is too long")
        if "\n" in arabic or "\r" in arabic or "\n" in translation or "\r" in translation:
            raise ValueError(f"glossary term {number}: a term must be on one line")

        key = _term_key(arabic)
        if key in seen:
            continue  # the same term twice: the first one wins
        seen.add(key)
        cleaned.append({"arabic": arabic, "translation": translation})
    return cleaned


def _term_key(arabic):
    return " ".join(normalize_arabic(arabic).split())


def _word_forms(word):
    # A written word may carry prefixes the stemmer doesn't take off together ("وبالصلاة" = و + ب + الصلاة),
    # so the word is also tried without them.
    forms = [word]
    rest = word
    if len(rest) > 3 and rest[0] in "وف":
        rest = rest[1:]
        forms.append(rest)
    if len(rest) > 3 and rest[0] in "بكل":
        forms.append(rest[1:])
    return forms


def _words(text):
    # every arabic word of the text as ([the stems it may be], where it starts, where it ends).
    # The stem makes "الصلاة" and "الصلوات" the same word; punctuation and tashkeel are never part of a word.
    words = []
    for match in _ARABIC_WORD.finditer(text):
        normalized = normalize_arabic(match.group())
        stems = [_stemmer.stem(form) or form for form in _word_forms(normalized)]
        words.append((stems, match.start(), match.end()))
    return words


def find_glossary_hits(text, glossary):
    # The entries whose term is in the text, in the order they appear. A term of several words has to be
    # found as the same words one after the other. If two terms share words, the longer one takes them.
    words = _words(text)
    taken = [False] * len(words)

    prepared = []
    for entry in glossary:
        # the term is written the way a dictionary has it, so only its own stems count
        term = [stems[0] for stems, _, _ in _words(entry["arabic"])]
        if term:
            prepared.append((term, entry))
    prepared.sort(key=lambda item: -len(item[0]))

    found = []
    for term, entry in prepared:
        for start in range(len(words) - len(term) + 1):
            same_words = all(term[i] in words[start + i][0] for i in range(len(term)))
            if same_words and not any(taken[start:start + len(term)]):
                taken[start:start + len(term)] = [True] * len(term)
                found.append((start, entry))
                break
    return [{"arabic": entry["arabic"], "translation": entry["translation"]} for _, entry in sorted(found, key=lambda f: f[0])]


def build_glossary_instructions(hits):
    # added to the system prompt. The texts are written as json strings, so a term can't be taken as an instruction.
    lines = [
        f"- {json.dumps(hit['arabic'], ensure_ascii=False)} => {json.dumps(hit['translation'], ensure_ascii=False)}"
        for hit in hits
    ]
    return (
        "\n\nApproved glossary. When one of these Arabic terms is in the text, write its approved translation "
        "exactly as given (same spelling), without translating it again and without any explanation:\n"
        + "\n".join(lines)
    )


def build_glossary_correction(missing):
    # the next message to the llm when its translation did not use some of the approved translations
    names = ", ".join(json.dumps(hit["translation"], ensure_ascii=False) for hit in missing)
    return (
        f"Your translation does not contain these approved translations: {names}. "
        "Translate the text again and use each of them exactly as given. Reply with only the translation."
    )


def translation_is_used(translated_text, translation):
    # case and extra spaces don't matter
    squeeze = lambda value: " ".join(value.split()).casefold()
    return squeeze(translation) in squeeze(translated_text)
