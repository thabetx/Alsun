import json

from glossary import (
    build_protected_correction,
    missing_translations,
    protected_translations,
)
from llm import chat_text
from modify_paragraph import client
from paragraph_format import concatenate_paragraph_segements, build_paragraph_display_parts


def collect_normal_texts(paragraphs):
    # one item per normal segment of every selected paragraph; quran is never collected.
    # key = position in this list, it is how we put the llm answer back in the right place
    items = []
    places = []
    for paragraph_number, paragraph in enumerate(paragraphs):
        for segment_number, segment in enumerate(paragraph):
            if segment["type"] == "normal" and segment["text"].strip():
                items.append({"key": str(len(items)), "text": segment["text"]})
                places.append((paragraph_number, segment_number))

    return items, places


def build_modify_messages(items, instructions, protected_by_key=None):
    # protected_by_key = for each item, the approved glossary translations that must stay in its text
    protected_by_key = protected_by_key or {}
    system_prompt = (
        "You edit several translated texts. Apply the user's instructions to each text "
        "separately and keep the meaning of each one. Reply with only JSON in this shape: "
        '{"items": [{"key": "...", "text": "..."}]} with the same keys, one item for every '
        "text you received, and no explanations."
    )
    sent_items = [
        {**item, "keep": protected_by_key[item["key"]]} if protected_by_key.get(item["key"]) else item
        for item in items
    ]
    if any(protected_by_key.values()):
        system_prompt += (
            ' An item with a "keep" list has approved glossary terms: every string of the list must stay in the new '
            "text of that item exactly as written (same spelling), even when you shorten, simplify or rephrase it."
        )
    user_prompt = json.dumps({"instructions": instructions, "items": sent_items}, ensure_ascii=False)
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def ask_llm_to_modify_texts(items, instructions, model=None, protected_by_key=None):
    return chat_text(client, build_modify_messages(items, instructions, protected_by_key), model, json_output=True)


def read_modified_texts(llm_answer, items):
    # the answer is used only if every text came back; otherwise nothing is changed
    try:
        answer_items = json.loads(llm_answer)["items"]
        modified_texts = {answer_item["key"]: answer_item["text"] for answer_item in answer_items}
    except (ValueError, KeyError, TypeError):
        raise ValueError("the llm answer is not in the expected format")

    expected_keys = {item["key"] for item in items}
    if len(answer_items) != len(items) or set(modified_texts) != expected_keys:
        raise ValueError("the llm answer does not have the same texts we sent")
    for text in modified_texts.values():
        if not isinstance(text, str) or not text.strip():
            raise ValueError("the llm returned an empty text")

    return modified_texts


def collect_protected_terms(paragraphs, items, places, glossary):
    # for every item, the approved translations of the user's glossary that its text carries (see glossary.py)
    protected_by_key = {}
    for item, (paragraph_number, segment_number) in zip(items, places):
        segment = paragraphs[paragraph_number][segment_number]
        protected = protected_translations(segment.get("original"), segment["text"], glossary)
        if protected:
            protected_by_key[item["key"]] = protected
    return protected_by_key


def terms_lost(modified_texts, protected_by_key):
    # the keys whose new text lost an approved term, with the terms it lost
    lost = {}
    for key, protected in protected_by_key.items():
        missing = missing_translations(modified_texts[key], protected)
        if missing:
            lost[key] = missing
    return lost


def modify_many_paragraphs_with_report(paragraphs, instructions, model=None, glossary=None):
    # paragraphs = a list of selected paragraphs, each one is a list of segments.
    # all normal texts go to the llm in ONE call; quran stays exactly as it is.
    # A text that carries approved glossary terms must keep them: if the answer loses one, the llm is told once
    # and asked again; a text that still loses one is left as it was.
    # Gives (the new paragraphs, the numbers of the paragraphs where a text was left as it was because of that).
    items, places = collect_normal_texts(paragraphs)
    if not items:
        return [list(paragraph) for paragraph in paragraphs], []

    protected_by_key = collect_protected_terms(paragraphs, items, places, glossary)
    messages = build_modify_messages(items, instructions, protected_by_key)
    first_answer = chat_text(client, messages, model, json_output=True)
    modified_texts = read_modified_texts(first_answer, items)

    left_as_it_was = set()
    lost = terms_lost(modified_texts, protected_by_key)
    if lost:
        every_term = sorted({term for terms in lost.values() for term in terms})
        retry_messages = messages + [
            {"role": "assistant", "content": first_answer},
            {"role": "user", "content": build_protected_correction(every_term)},
        ]
        try:
            retried_texts = read_modified_texts(chat_text(client, retry_messages, model, json_output=True), items)
        except ValueError:  # the second answer is not usable
            retried_texts = {}
        for key in lost:
            if key in retried_texts and not missing_translations(retried_texts[key], protected_by_key[key]):
                modified_texts[key] = retried_texts[key]
            else:
                left_as_it_was.add(key)

    modified_paragraphs = [list(paragraph) for paragraph in paragraphs]
    blocked_paragraphs = set()
    for item, (paragraph_number, segment_number) in zip(items, places):
        segment = paragraphs[paragraph_number][segment_number]
        if item["key"] in left_as_it_was:
            blocked_paragraphs.add(paragraph_number)
            continue
        modified_paragraphs[paragraph_number][segment_number] = {**segment, "text": modified_texts[item["key"]]}

    return modified_paragraphs, sorted(blocked_paragraphs)


def modify_many_paragraphs(paragraphs, instructions, model=None, glossary=None):
    return modify_many_paragraphs_with_report(paragraphs, instructions, model, glossary)[0]


def modify_many_paragraphs_and_build_response(paragraphs, instructions, model=None, glossary=None):
    modified_paragraphs, glossary_blocked_rows = modify_many_paragraphs_with_report(
        paragraphs, instructions, model, glossary
    )

    rows = []
    for modified_segments in modified_paragraphs:
        rows.append({
            "paragraph": concatenate_paragraph_segements(modified_segments),
            "parts": build_paragraph_display_parts(modified_segments),
            "segments": modified_segments,
        })

    # paragraphs with no normal text (only quran) can't be modified, the user must be told
    quran_only_rows = [
        row_number for row_number, paragraph in enumerate(paragraphs)
        if paragraph and all(segment["type"] == "quran" for segment in paragraph)
    ]
    # rows where a text was left as it was, because the llm kept changing an approved term of the glossary
    return {"rows": rows, "quran_only_rows": quran_only_rows, "glossary_blocked_rows": glossary_blocked_rows}
