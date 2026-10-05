import re
from collections import Counter

from quran_detect import (
    normalize_arabic,
    translate_paragraph_segments,
    concatenate_paragraph_segements,
    build_paragraph_display_parts,
)

# an ayah that was recognised before and is not recognised now, but most of its words are
# still in the text, is probably damaged by a spelling mistake (not removed on purpose)
DAMAGED_AYAH_WORDS_RATIO = 0.6


def find_ayahs_of_segment(segment):
    # a quran segment is one ayah (or a few in a row); a segment the user wrote in place of an ayah he deleted
    # remembers them in "replaced_quran" (each one with its arabic words)
    if segment["type"] == "quran":
        return [segment]
    return segment.get("replaced_quran", [])


def build_quran_fingerprint(segments):
    # which ayahs a paragraph has: (surah, aya start, aya end) for every quran segment
    return [
        (normalize_arabic(ayah["aya_name"]), ayah["aya_start"], ayah["aya_end"])
        for segment in segments for ayah in find_ayahs_of_segment(segment)
    ]


def describe_ayah(fingerprint_item):
    surah_name, aya_start, aya_end = fingerprint_item
    return {"aya_name": surah_name, "aya_start": aya_start, "aya_end": aya_end}


def read_arabic_words(text):
    # only arabic letters, no tashkeel, one form of alef / taa marbuta / yaa
    return re.findall(r"[ء-ي]+", normalize_arabic(text))


def ayah_words_still_in_text(ayah_original, new_original_text):
    ayah_words = read_arabic_words(ayah_original)
    if not ayah_words:
        return False
    new_words = set(read_arabic_words(new_original_text))
    words_found = sum(1 for word in ayah_words if word in new_words)
    return words_found / len(ayah_words) >= DAMAGED_AYAH_WORDS_RATIO


def compare_quran_before_and_after(old_segments, new_segments, new_original_text):
    old_counter = Counter(build_quran_fingerprint(old_segments))
    new_counter = Counter(build_quran_fingerprint(new_segments))

    removed_counter = old_counter - new_counter
    added = [describe_ayah(item) for item in (new_counter - old_counter).elements()]
    unchanged = sum((old_counter & new_counter).values())

    removed, damaged = [], []
    for old_ayah in (ayah for segment in old_segments for ayah in find_ayahs_of_segment(segment)):
        item = (normalize_arabic(old_ayah["aya_name"]), old_ayah["aya_start"], old_ayah["aya_end"])
        if removed_counter[item] > 0:
            removed_counter[item] -= 1
            if ayah_words_still_in_text(old_ayah["original"], new_original_text):
                damaged.append(describe_ayah(item))
            else:
                removed.append(describe_ayah(item))

    return {"removed": removed, "added": added, "damaged": damaged, "unchanged": unchanged}


def retranslate_edited_original(
    old_segments, new_original_text, json_file=None, target_lang="English", glossary=None, quran_source=None, model=None
):
    # the user changed the arabic text: translate the row again and tell what happened to the ayahs
    new_segments = translate_paragraph_segments(
        new_original_text, json_file, target_lang, glossary, quran_source, model
    )
    quran_changes = compare_quran_before_and_after(old_segments, new_segments, new_original_text)
    needs_review = bool(quran_changes["removed"] or quran_changes["added"] or quran_changes["damaged"])

    return {
        "paragraph": concatenate_paragraph_segements(new_segments),
        "parts": build_paragraph_display_parts(new_segments),
        "segments": new_segments,
        # the old translation (with the manual and assistant edits) goes to the edit history
        "previous_segments": old_segments,
        "quran_changes": quran_changes,
        "needs_review": needs_review,
    }
