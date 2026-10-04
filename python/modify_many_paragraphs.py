import json

from modify_paragraph import client
from paragraph_format import concatenate_paragraph_segements, build_paragraph_display_parts


def collect_normal_texts(paragraphs):
    # one item per normal segment of every selected paragraph; quran is never collected.
    # key = position in this list, it is how we put the llm answer back in the right place
    items = []
    places = []
    for paragraph_number, paragraph in enumerate(paragraphs):
        for segment_number, segment in enumerate(paragraph):
            if segment["type"] == "normal":
                items.append({"key": str(len(items)), "text": segment["text"]})
                places.append((paragraph_number, segment_number))

    return items, places


def ask_llm_to_modify_texts(items, instructions):
    system_prompt = (
        "You edit several translated texts. Apply the user's instructions to each text "
        "separately and keep the meaning of each one. Reply with only JSON in this shape: "
        '{"items": [{"key": "...", "text": "..."}]} with the same keys, one item for every '
        "text you received, and no explanations."
    )
    user_prompt = json.dumps({"instructions": instructions, "items": items}, ensure_ascii=False)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return response.choices[0].message.content


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


def modify_many_paragraphs(paragraphs, instructions):
    # paragraphs = a list of selected paragraphs, each one is a list of segments.
    # all normal texts go to the llm in ONE call; quran stays exactly as it is
    items, places = collect_normal_texts(paragraphs)
    if not items:
        return [list(paragraph) for paragraph in paragraphs]

    modified_texts = read_modified_texts(ask_llm_to_modify_texts(items, instructions), items)

    modified_paragraphs = [list(paragraph) for paragraph in paragraphs]
    for item, (paragraph_number, segment_number) in zip(items, places):
        segment = paragraphs[paragraph_number][segment_number]
        modified_paragraphs[paragraph_number][segment_number] = {**segment, "text": modified_texts[item["key"]]}

    return modified_paragraphs


def modify_many_paragraphs_and_build_response(paragraphs, instructions):
    modified_paragraphs = modify_many_paragraphs(paragraphs, instructions)

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
    return {"rows": rows, "quran_only_rows": quran_only_rows}
