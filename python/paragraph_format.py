def concatenate_paragraph_segements(segments):
    # one paragraph for the user; the segments list stays as the source of truth.
    # the quran style (" ") is added only here, never inside segment["text"]
    parts = []
    for segment in segments:
        if segment["type"] == "quran":
            parts.append(f'"{segment["text"]}"')
        else:
            parts.append(segment["text"])

    return " ".join(parts)
