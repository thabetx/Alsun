from glossary import (
    build_protected_correction,
    build_protected_instructions,
    missing_translations,
    protected_translations,
)
from llm import chat_text
from modify_paragraph import client


def check_fragment_range(segment, fragment_start, fragment_end):
    # quran is never modified, not even a part of it
    if segment["type"] == "quran":
        raise ValueError("quran segments are never modified")
    if not 0 <= fragment_start < fragment_end <= len(segment["text"]):
        raise ValueError("the selected part is outside the segment text")


def suggest_fragment_replacement(segment, fragment_start, fragment_end, instructions, model=None, glossary=None):
    # only a suggestion: nothing is changed until the user accepts it
    check_fragment_range(segment, fragment_start, fragment_end)
    selected_text = segment["text"][fragment_start:fragment_end]

    system_prompt = (
        "You edit one selected part of a translated text. Apply the user's instructions "
        "to the selected part only. The full text is given only as context to read. "
        "Reply with only the new version of the selected part, no explanations or extra text."
    )
    # the approved terms of the user's glossary that are in the selected part must stay in it
    protected = protected_translations(segment.get("original"), selected_text, glossary)
    if protected:
        system_prompt += build_protected_instructions(protected)
    user_prompt = (
        f"Instructions: {instructions}\n\n"
        f"Full text (context only): {segment['text']}\n\n"
        f"Selected part: {selected_text}"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    replacement = chat_text(client, messages, model).strip()

    missing = missing_translations(replacement, protected)
    if missing:  # one more try, telling the model what it changed
        retry_messages = messages + [
            {"role": "assistant", "content": replacement},
            {"role": "user", "content": build_protected_correction(missing)},
        ]
        replacement = chat_text(client, retry_messages, model).strip()
        if missing_translations(replacement, protected):
            raise ValueError("the assistant changed an approved glossary term")
    return replacement


def apply_fragment_replacement(segment, fragment_start, fragment_end, expected_text, replacement):
    # called after the user accepts; returns a new segment, the old one is not changed
    check_fragment_range(segment, fragment_start, fragment_end)
    selected_text = segment["text"][fragment_start:fragment_end]

    # the text changed after the selection, so the positions are not valid anymore
    if selected_text != expected_text:
        raise ValueError("the selected part changed, select it again")

    # keep the spaces around the selected part so the words do not stick together
    leading_spaces = selected_text[:len(selected_text) - len(selected_text.lstrip())]
    trailing_spaces = selected_text[len(selected_text.rstrip()):]
    new_text = (
        segment["text"][:fragment_start]
        + leading_spaces + replacement.strip() + trailing_spaces
        + segment["text"][fragment_end:]
    )
    return {**segment, "text": new_text}
