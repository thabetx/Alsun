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
from arabic_text import normalize_arabic  # also imported from here by other modules
from glossary import (
    find_glossary_hits,
    build_glossary_instructions,
    build_glossary_correction,
    translation_is_used,
)

# reads OPENAI_API_KEY from a .env file (or the environment)
load_dotenv()
client = OpenAI()

# the quran translation jsons live in the data/ folder at the project root
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# the quran translation we use for every language (the files are made by download_quran_translation.py
# and convert_qul_translation.py in translation_pipeline/). The text of the quran is never made by the llm.
QURAN_FILES = {
    "English": "quran_en_hilali_khan.json",
    "French": "quran_fr_hamidullah.json",    # Hamidullah, revised by the King Fahd Complex
    "German": "quran_de_bubenheim.json",     # Bubenheim and Elyas
    "Turkish": "quran_tr_diyanet.json",      # Diyanet. NOT READY: it translates a few ayahs together, so the same text is repeated on 843 consecutive ayahs
    "Spanish": "quran_es_garcia.json",       # Isa Garcia, the latin america edition ("ustedes")
    "Indonesian": "quran_id_kemenag.json",   # Ministry of Religious Affairs; the edition is not confirmed yet
}


def find_quran_file(target_lang):
    if target_lang not in QURAN_FILES:
        raise ValueError(f"No quran translation for the language: {target_lang}")
    return DATA_DIR / QURAN_FILES[target_lang]


detector_lock = threading.Lock()
quran_annotate = qdetect.qMatcherAnnotater() # built once, it takes ~6 seconds

def quran_detector(paragraph):
    # one matcher is shared by all the requests; only one request uses it at a time
    with detector_lock:
        quran_detector_result = quran_annotate.matchAll(paragraph)
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


def ask_llm(messages):
    response = client.chat.completions.create(model="gpt-4o-mini", messages=messages)
    return response.choices[0].message.content


def translate_normal_paragraph_with_report(paragraph, target_lang="English", glossary=None):
    # normal text goes to the llm. The terms of the glossary that are in the text are told to it, and if its
    # translation does not use one of them it is asked once more. Gives {"text", "glossary"}, where "glossary"
    # has the terms found in the text and whether the translation uses each one ("used").
    hits = find_glossary_hits(paragraph, glossary or [])
    system_prompt = (
        f"You are a translator. Translate the user's Arabic text into "
        f"{target_lang}. Reply with only the translation, "
        f"no explanations or extra text."
    )
    if hits:
        system_prompt += build_glossary_instructions(hits)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": paragraph},
    ]

    text = ask_llm(messages)
    missing = [hit for hit in hits if not translation_is_used(text, hit["translation"])]
    if missing:
        retry_messages = messages + [
            {"role": "assistant", "content": text},
            {"role": "user", "content": build_glossary_correction(missing)},
        ]
        retried = ask_llm(retry_messages)
        still_missing = [hit for hit in hits if not translation_is_used(retried, hit["translation"])]
        if len(still_missing) < len(missing):  # the second translation is kept only if it is better
            text, missing = retried, still_missing

    report = [{**hit, "used": hit not in missing} for hit in hits]
    return {"text": text, "glossary": report}


def translate_normal_paragraph(paragraph, target_lang="English", glossary=None):
    return translate_normal_paragraph_with_report(paragraph, target_lang, glossary)["text"]


def translate_quran_paragraph(segment, quran_json):
    # quran text comes from the json, never from the llm
    for surah_number, surah_data in quran_json.items():
        if normalize_arabic(surah_data["name_arabic"]) == normalize_arabic(segment["aya_name"]):
            ayahs = [surah_data["ayahs"][str(n)] for n in range(segment["aya_start"], segment["aya_end"] + 1)]
            return " ".join(ayahs)
    return segment["text"] # surah not found, keep the arabic as it is


def translate_paragraph_segments(paragraph, json_file=None, target_lang="English", glossary=None):
    if json_file is None:
        json_file = find_quran_file(target_lang)
    with open(json_file, encoding="utf-8") as f:
        quran_json = json.load(f)

    translated_segments = []
    for segment_number, segment in enumerate(split_quran_and_normal_paragraph(paragraph), start=1):
        glossary_report = {}
        if segment["type"] == "quran":
            translated_text = translate_quran_paragraph(segment, quran_json)
        else:
            result = translate_normal_paragraph_with_report(segment["text"], target_lang, glossary)
            translated_text = result["text"]
            if result["glossary"]:
                glossary_report = {"glossary": result["glossary"]}  # the terms of the user's glossary found in this part
        # id = stable name for the segment, text = the translation, original = the arabic we got it from
        translated_segments.append({
            **segment, "id": f"seg_{segment_number}", "text": translated_text, "original": segment["text"], **glossary_report,
        })

    return translated_segments


def translate_paragraph_and_build_response(paragraph, json_file=None, target_lang="English", glossary=None):
    segments = translate_paragraph_segments(paragraph, json_file, target_lang, glossary)
    return {
        "paragraph": concatenate_paragraph_segements(segments),
        "parts": build_paragraph_display_parts(segments),
        "segments": segments,
    }



