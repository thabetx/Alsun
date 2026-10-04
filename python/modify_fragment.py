from modify_paragraph import client


def check_fragment_range(segment, fragment_start, fragment_end):
    # quran is never modified, not even a part of it
    if segment["type"] == "quran":
        raise ValueError("quran segments are never modified")
    if not 0 <= fragment_start < fragment_end <= len(segment["text"]):
        raise ValueError("the selected part is outside the segment text")


def suggest_fragment_replacement(segment, fragment_start, fragment_end, instructions):
    # only a suggestion: nothing is changed until the user accepts it
    check_fragment_range(segment, fragment_start, fragment_end)
    selected_text = segment["text"][fragment_start:fragment_end]

    system_prompt = (
        "You edit one selected part of a translated text. Apply the user's instructions "
        "to the selected part only. The full text is given only as context to read. "
        "Reply with only the new version of the selected part, no explanations or extra text."
    )
    user_prompt = (
        f"Instructions: {instructions}\n\n"
        f"Full text (context only): {segment['text']}\n\n"
        f"Selected part: {selected_text}"
    )
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return response.choices[0].message.content.strip()


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
