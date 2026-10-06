import QDetect.qdetect as qdetect
import codecs
import json
import re
import threading
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
from paragraph_format import (
    concatenate_paragraph_segements,
    build_paragraph_display_parts,
)
from arabic_text import normalize_arabic, split_into_chunks  # normalize_arabic is also imported from here by other modules
from llm import chat_text, max_input_chars
from glossary import (
    find_glossary_hits,
    build_glossary_instructions,
    build_glossary_correction,
    translation_is_used,
)
from trusted_terms import find_trusted_terms, build_trusted_instructions, build_trusted_correction, is_used

# reads OPENAI_API_KEY from a .env file (or the environment)
load_dotenv()
client = OpenAI()

# the quran translation jsons live in the data/ folder at the project root
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# The quran translations we have for every language (the files are made by download_quran_translation.py and
# convert_qul_translation.py in translation_pipeline/). The text of the quran is never made by the llm.
# The first one of a language is the one used when the user chose nothing. The names are shown as they are.
QURAN_SOURCES = {
    "English": [
        {"id": "hilali_khan", "file": "quran_en_hilali_khan.json",
         "name": "Muhammad Taqi-ud-Din al-Hilali & Muhammad Muhsin Khan (The Noble Quran, King Fahd Complex)"},
        {"id": "saheeh", "file": "quran_en_saheeh.json", "name": "Saheeh International"},
    ],
    "French": [
        {"id": "hamidullah", "file": "quran_fr_hamidullah.json",
         "name": "Muhammad Hamidullah (revised by the King Fahd Complex)"},
    ],
    "German": [
        {"id": "bubenheim", "file": "quran_de_bubenheim.json", "name": "Frank Bubenheim and Nadeem"},
    ],
    "Spanish": [
        {"id": "garcia", "file": "quran_es_garcia.json", "name": "Isa Garcia (Latin America, \"ustedes\")"},
    ],
    # NOT READY (they are "coming soon" in the home page):
    # Diyanet translates a few ayahs together, so the same text is repeated on 843 consecutive ayahs;
    # the edition of the Indonesian one is not confirmed yet.
    "Turkish": [
        {"id": "diyanet", "file": "quran_tr_diyanet.json", "name": "Diyanet Isleri Baskanligi"},
    ],
    "Indonesian": [
        {"id": "kemenag", "file": "quran_id_kemenag.json", "name": "Indonesian Islamic Affairs Ministry"},
    ],
}


def find_quran_source(target_lang, source_id=None):
    # the quran translation of a language: the one with this id, or the first one if no id is given
    if target_lang not in QURAN_SOURCES:
        raise ValueError(f"No quran translation for the language: {target_lang}")
    sources = QURAN_SOURCES[target_lang]
    if source_id is None:
        return sources[0]
    for source in sources:
        if source["id"] == source_id:
            return source
    raise ValueError(f"No quran translation {source_id} for the language: {target_lang}")


def find_quran_file(target_lang, source_id=None):
    return DATA_DIR / find_quran_source(target_lang, source_id)["file"]


def quran_source_options():
    # what the settings window shows: for every language, its quran translations (the first is the default)
    return {
        language: [{"id": source["id"], "name": source["name"], "default": number == 0}
                   for number, source in enumerate(sources)]
        for language, sources in QURAN_SOURCES.items()
    }


detector_lock = threading.Lock()
_annotater = None  # the quran matcher, see load_detector


def load_detector():
    # The matcher takes ~6 seconds to build. It is not built when this module is imported (that made the server
    # take that long to start, and the browser showed an error until it did): it is built the first time it is
    # needed, or earlier by warm_up_detector_in_background. Only one build, even if many requests ask together.
    global _annotater
    with detector_lock:
        if _annotater is None:
            _annotater = qdetect.qMatcherAnnotater()
        return _annotater


def detector_is_ready():
    return _annotater is not None


def warm_up_detector_in_background():
    # the page of the user asks for this when a book is chosen, so the matcher is ready when the translation starts
    if _annotater is None:
        threading.Thread(target=load_detector, daemon=True).start()


def quran_detector(paragraph):
    # one matcher is shared by all the requests; only one request uses it at a time
    annotater = load_detector()
    with detector_lock:
        quran_detector_result = annotater.matchAll(paragraph)
    #print(quran_detector_result)
    return quran_detector_result


def split_quran_and_normal_paragraph(paragraph):
    quran_paragraph_dictionary = quran_detector(paragraph) # now we got the dictioary
    words = paragraph.split()
    
    ayah_or_sentence_list=[]
    cursor = 0
    for ayah in quran_paragraph_dictionary:
        ayah_start, ayah_end =  ayah["startInText"], min(ayah["endInText"], len(words))

        # same words can match more than one ayah, keep the first and skip the overlap
        if ayah_start < cursor:
            continue

        # normal text = words between the last ayah's end (cursor) and this ayah's start
        if ayah_start > cursor:
            normal_paragraph = " ".join(words[cursor:ayah_start])
            ayah_or_sentence_list.append({"type": "normal", "text": normal_paragraph})

        ayah_paragraph = " ".join(words[ayah_start:ayah_end])
        ayah_or_sentence_list.append({"type": "quran", "text": ayah_paragraph, "aya_name": ayah["aya_name"],"aya_start": ayah["aya_start"], "aya_end": ayah["aya_end"]})
        cursor = ayah_end

    # whatever is left after the last ayah is normal text too
    if cursor < len(words):
        normal_paragraph = " ".join(words[cursor:])
        ayah_or_sentence_list.append({"type": "normal", "text": normal_paragraph})

    return ayah_or_sentence_list


def ask_llm(messages, model=None):
    # model = {"provider", "model"} chosen by the user, or None for the default one (see llm.py)
    return chat_text(client, messages, model)


def translate_chunk_with_report(paragraph, target_lang, glossary, model, use_trusted_terms=True):
    # One question to the llm. The terms of the glossary that are in the text are told to it, and if its
    # translation does not use one of them it is asked once more. Gives {"text", "glossary"}, where "glossary"
    # has the terms found in the text and whether the translation uses each one ("used"). The trusted Islamic terms
    # (see trusted_terms.py) are told and asked again like the terms of the user, if the user did not turn them off;
    # they are not reported to the front.
    hits = find_glossary_hits(paragraph, glossary or [])
    trusted = find_trusted_terms(paragraph, target_lang, [hit["arabic"] for hit in hits]) if use_trusted_terms else []
    system_prompt = (
        f"You are a translator. Translate the user's Arabic text into "
        f"{target_lang}. Reply with only the translation, "
        f"no explanations or extra text."
    )
    if hits:
        system_prompt += build_glossary_instructions(hits)
    if trusted:
        system_prompt += build_trusted_instructions(trusted, target_lang)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": paragraph},
    ]

    def not_used(translation):
        return (
            [hit for hit in hits if not translation_is_used(translation, hit["translation"])],
            [entry for entry in trusted if not is_used(entry, translation)],
        )

    text = ask_llm(messages, model)
    missing, trusted_missing = not_used(text)
    if missing or trusted_missing:
        corrections = []
        if missing:
            corrections.append(build_glossary_correction(missing))
        if trusted_missing:
            corrections.append(build_trusted_correction(trusted_missing))
        retry_messages = messages + [
            {"role": "assistant", "content": text},
            {"role": "user", "content": "\n\n".join(corrections)},
        ]
        retried = ask_llm(retry_messages, model)
        still_missing, still_trusted_missing = not_used(retried)
        # the second translation is kept only if it is better
        if len(still_missing) + len(still_trusted_missing) < len(missing) + len(trusted_missing):
            text, missing = retried, still_missing

    report = [{**hit, "used": hit not in missing} for hit in hits]
    return {"text": text, "glossary": report}


def merge_glossary_reports(reports):
    # the reports of the pieces of one paragraph as one: a term counts as used only if every piece that has it used it
    merged = {}
    for report in reports:
        for item in report:
            key = (item["arabic"], item["translation"])
            if key in merged:
                merged[key]["used"] = merged[key]["used"] and item["used"]
            else:
                merged[key] = dict(item)
    return list(merged.values())


def translate_normal_paragraph_with_report(paragraph, target_lang="English", glossary=None, model=None, use_trusted_terms=True):
    # A model with a small context window gets a long paragraph piece by piece (cut at the end of sentences).
    limit = max_input_chars(model)
    chunks = split_into_chunks(paragraph, limit) if limit else [paragraph]
    results = [translate_chunk_with_report(chunk, target_lang, glossary, model, use_trusted_terms) for chunk in chunks]
    if len(results) == 1:
        return results[0]
    return {
        "text": " ".join(result["text"] for result in results),
        "glossary": merge_glossary_reports([result["glossary"] for result in results]),
    }


def translate_normal_paragraph(paragraph, target_lang="English", glossary=None, model=None, use_trusted_terms=True):
    return translate_normal_paragraph_with_report(paragraph, target_lang, glossary, model, use_trusted_terms)["text"]


def translate_quran_paragraph(segment, quran_json):
    # quran text comes from the json, never from the llm
    for surah_number, surah_data in quran_json.items():
        if normalize_arabic(surah_data["name_arabic"]) == normalize_arabic(segment["aya_name"]):
            ayahs = [surah_data["ayahs"][str(n)] for n in range(segment["aya_start"], segment["aya_end"] + 1)]
            return " ".join(ayahs)
    return segment["text"] # surah not found, keep the arabic as it is


def translate_paragraph_segments(
    paragraph, json_file=None, target_lang="English", glossary=None, quran_source=None, model=None, use_trusted_terms=True
):
    # quran_source = id of the quran translation (the first one of the language if None); model = see ask_llm;
    # use_trusted_terms = the user's choice in the settings, see trusted_terms.py
    source = None
    if json_file is None:
        source = find_quran_source(target_lang, quran_source)
        json_file = DATA_DIR / source["file"]
    with open(json_file, encoding="utf-8") as f:
        quran_json = json.load(f)

    translated_segments = []
    for segment_number, segment in enumerate(split_quran_and_normal_paragraph(paragraph), start=1):
        glossary_report = {}
        if segment["type"] == "quran":
            translated_text = translate_quran_paragraph(segment, quran_json)
            if source:
                glossary_report = {"quran_source": source["id"]}  # which translation of the quran this ayah comes from
        else:
            result = translate_normal_paragraph_with_report(segment["text"], target_lang, glossary, model, use_trusted_terms)
            translated_text = result["text"]
            if result["glossary"]:
                glossary_report["glossary"] = result["glossary"]  # the terms of the user's glossary found in this part
        # id = stable name for the segment, text = the translation, original = the arabic we got it from
        translated_segments.append({
            **segment, "id": f"seg_{segment_number}", "text": translated_text, "original": segment["text"], **glossary_report,
        })

    return translated_segments


def translate_paragraph_and_build_response(
    paragraph, json_file=None, target_lang="English", glossary=None, quran_source=None, model=None, use_trusted_terms=True
):
    segments = translate_paragraph_segments(
        paragraph, json_file, target_lang, glossary, quran_source, model, use_trusted_terms
    )
    return {
        "paragraph": concatenate_paragraph_segements(segments),
        "parts": build_paragraph_display_parts(segments),
        "segments": segments,
    }


def swap_quran_source(segments, target_lang, quran_source):
    # The ayahs of translated segments written again from another quran translation. No llm, and nothing else changes.
    source = find_quran_source(target_lang, quran_source)
    with open(DATA_DIR / source["file"], encoding="utf-8") as f:
        quran_json = json.load(f)
    return [
        {**segment, "text": translate_quran_paragraph(segment, quran_json), "quran_source": source["id"]}
        if segment["type"] == "quran" else segment
        for segment in segments
    ]
