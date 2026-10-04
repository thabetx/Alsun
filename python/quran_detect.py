import QDetect.qdetect as qdetect
import codecs
import json
import re
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
from paragraph_format import concatenate_paragraph_segements, build_paragraph_display_parts

# reads OPENAI_API_KEY from a .env file (or the environment)
load_dotenv()
client = OpenAI()

# the quran translation jsons live in the data/ folder at the project root
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

quran_annotate = qdetect.qMatcherAnnotater() # built once, it takes ~6 seconds


def quran_detector(paragraph):
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

def translate_normal_paragraph(paragraph, target_lang="English"):
    # normal text goes to the llm
    system_prompt = (
        f"You are a translator. Translate the user's Arabic text into "
        f"{target_lang}. Reply with only the translation, "
        f"no explanations or extra text."
    )
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": paragraph},
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


def translate_paragraph_segments(paragraph, json_file=None):
    if json_file is None:
        json_file = DATA_DIR / "quran_en_hilali_khan.json"
    with open(json_file, encoding="utf-8") as f:
        quran_json = json.load(f)

    translated_segments = []
    for segment_number, segment in enumerate(split_quran_and_normal_paragraph(paragraph), start=1):
        if segment["type"] == "quran":
            translated_text = translate_quran_paragraph(segment, quran_json)
        else:
            translated_text = translate_normal_paragraph(segment["text"])
        # id = stable name for the segment, text = the translation, original = the arabic we got it from
        translated_segments.append({**segment, "id": f"seg_{segment_number}", "text": translated_text, "original": segment["text"]})

    return translated_segments


def translate_paragraph_and_build_response(paragraph, json_file=None):
    segments = translate_paragraph_segments(paragraph, json_file)
    return {
        "paragraph": concatenate_paragraph_segements(segments),
        "parts": build_paragraph_display_parts(segments),
        "segments": segments,
    }



