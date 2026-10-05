import re


def normalize_arabic(name):
    # make arabic text comparable: no tashkeel, one form of alef / taa marbuta / yaa
    name = re.sub(r"[ً-ٰـ]", "", name)
    name = re.sub(r"[أإآٱ]", "ا", name)
    return name.replace("ة", "ه").replace("ى", "ي")


# ---------- long texts ----------
# A model with a small context window (see MAX_INPUT_CHARS in llm.py) can't read a long paragraph at once.
# The paragraph is cut at the end of sentences, and the pieces are translated one by one.

_SENTENCE_END = re.compile(r"(?<=[.!?\u061F\u061B])\s+")  # . ! ? and the arabic ? and ;
_CLAUSE_END = re.compile(r"(?<=[,\u060C;:])\s+")  # , and the arabic comma, for a sentence that is still too long


def _cut_words(text, max_chars):
    # the last way: whole words, as many as fit
    pieces, current = [], ""
    for word in text.split():
        while len(word) > max_chars:  # a word longer than the limit is cut (it does not happen in real text)
            if current:
                pieces.append(current)
                current = ""
            pieces.append(word[:max_chars])
            word = word[max_chars:]
        if current and len(current) + 1 + len(word) > max_chars:
            pieces.append(current)
            current = word
        else:
            current = f"{current} {word}" if current else word
    if current:
        pieces.append(current)
    return pieces


def _cut_long_sentence(sentence, max_chars):
    if len(sentence) <= max_chars:
        return [sentence]
    clauses = _CLAUSE_END.split(sentence)
    if len(clauses) == 1:
        return _cut_words(sentence, max_chars)
    pieces = []
    for clause in clauses:
        pieces.extend(_cut_long_sentence(clause, max_chars) if len(clause) > max_chars else [clause])
    return pieces


def split_into_chunks(text, max_chars):
    # The text cut into pieces of at most max_chars, at the end of a sentence when it can be (else at a comma,
    # else between words). The pieces joined with a space have all the words of the text, in the same order.
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []

    pieces = []
    for sentence in _SENTENCE_END.split(text):
        pieces.extend(_cut_long_sentence(sentence, max_chars))

    chunks, current = [], ""
    for piece in pieces:
        if current and len(current) + 1 + len(piece) > max_chars:
            chunks.append(current)
            current = piece
        else:
            current = f"{current} {piece}" if current else piece
    if current:
        chunks.append(current)
    return chunks
