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
from nltk.stem.isri import ISRIStemmer

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

stemmer = ISRIStemmer()


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


def normalize_arabic(name):
    # make surah names comparable: no tashkeel, one form of alef / taa marbuta / yaa
    name = re.sub(r"[ً-ٰٟـ]", "", name)
    name = re.sub(r"[أإآٱ]", "ا", name)
    return name.replace("ة", "ه").replace("ى", "ي")


def stem_arabic(text):
    text = normalize_arabic(text)
    tokens = [stemmer.stem(t) for t in text.split() if stemmer.stem(t)]
    return " ".join(tokens)


def load_glossary(language="English"):
    # TODO: Read this from a file/database
    if language == "English":
        glossary = [{"Arabic": "حى بن يقظان", language: "Hay bin Yaqdhan"}]
    else:
        glossary = []

    if glossary:
        # Stem the tokens to handle Arabic's morphological complexity
        for d in glossary:
            d["Arabic_stemmed"] = stem_arabic(d["Arabic"])

    return glossary


def find_glossary_items_in_text(stemmed_text, glossary):
    # TODO: If the glossary grows larger then this function will need to be reimplemented
    # such that the implementation is more efficient
    glossary_items_in_text = [
        d for d in glossary if re.findall(rf"\b{d['Arabic_stemmed']}\b", stemmed_text)
    ]
    return glossary_items_in_text


def translate_normal_paragraph(paragraph, target_lang="English", use_glossary=True):
    # normal text goes to the llm
    system_prompt = (
        f"You are a translator. Translate the user's Arabic text into "
        f"{target_lang}. Reply with only the translation, "
        f"no explanations or extra text."
    )

    if use_glossary:
        # TODO: Load this once and cache it, instead of loading it for every paragraph
        glossary = load_glossary(language=target_lang)

        stemmed_text = stem_arabic(paragraph)
        glossary_items = find_glossary_items_in_text(stem_arabic(paragraph), glossary)

        prompt = ""
        if glossary_items:
            prompt += "\n* Use the following glossary items in translating the text (as is without any modification):\n"
            prompt += (
                "\n".join(
                    [
                        f"- {item['Arabic']} -> {item[target_lang]}"
                        for item in glossary_items
                    ]
                )
                + "\n\n"
            )
        prompt += paragraph
    else:
        prompt = paragraph

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content


def translate_quran_paragraph(segment, quran_json):
    # quran text comes from the json, never from the llm
    for surah_number, surah_data in quran_json.items():
        if normalize_arabic(surah_data["name_arabic"]) == normalize_arabic(segment["aya_name"]):
            ayahs = [surah_data["ayahs"][str(n)] for n in range(segment["aya_start"], segment["aya_end"] + 1)]
            return " ".join(ayahs)
    return segment["text"] # surah not found, keep the arabic as it is


def translate_paragraph_segments(paragraph, json_file=None, target_lang="English"):
    if json_file is None:
        json_file = find_quran_file(target_lang)
    with open(json_file, encoding="utf-8") as f:
        quran_json = json.load(f)

    translated_segments = []
    for segment_number, segment in enumerate(split_quran_and_normal_paragraph(paragraph), start=1):
        if segment["type"] == "quran":
            translated_text = translate_quran_paragraph(segment, quran_json)
        else:
            translated_text = translate_normal_paragraph(segment["text"], target_lang)
        # id = stable name for the segment, text = the translation, original = the arabic we got it from
        translated_segments.append({**segment, "id": f"seg_{segment_number}", "text": translated_text, "original": segment["text"]})

    return translated_segments


def translate_paragraph_and_build_response(paragraph, json_file=None, target_lang="English"):
    segments = translate_paragraph_segments(paragraph, json_file, target_lang)
    return {
        "paragraph": concatenate_paragraph_segements(segments),
        "parts": build_paragraph_display_parts(segments),
        "segments": segments,
    }



