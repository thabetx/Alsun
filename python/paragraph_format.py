def build_paragraph_display_parts(segments):
    # what the user sees, one part per segment. The front wraps each part in its own element
    # (id + type) so a selection can be matched to a segment without character positions.
    # the quran style (" ") is added only here, never inside segment["text"]; the quotes
    # belong to the quran part, so selecting them counts as selecting the quran.
    parts = []
    for segment in segments:
        if segment["type"] == "quran":
            display_text = f'"{segment["text"]}"'
        else:
            display_text = segment["text"]
        parts.append({"id": segment["id"], "type": segment["type"], "text": display_text})

    return parts


def concatenate_paragraph_segements(segments):
    # one paragraph for the user; the segments list stays as the source of truth.
    parts = build_paragraph_display_parts(segments)
    return " ".join(part["text"] for part in parts)
