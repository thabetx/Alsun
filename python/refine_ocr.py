"""Fix the OCR mistakes of an arabic text, without rewriting it.

The text comes from the OCR of a scanned book: mostly right, with the mistakes
the OCR usually makes (a wrong letter, a missing or extra dot, a lost hamza,
two words stuck together, a broken word). The point is to repair those, and
nothing else: the wording, the style and the length must stay as they are.

Before the llm is called, the parts the quran detector recognises are marked
with [[ ]]. The OCR often cuts an ayah in half, so the marks also tell the
model where an ayah probably starts and ends, and where it has to put back the
part that was lost.
"""

import copy
import html as html_module
import re
from concurrent.futures import ThreadPoolExecutor

from modify_paragraph import client
from quran_detect import quran_detector

# one llm call per paragraph, a few at a time: the quran detector is shared and locked,
# so the calls pile up on it, but the llm part of them runs side by side
PARALLEL_REFINE = 4

SYSTEM_PROMPT = (
    "You repair the text of an arabic book that was scanned and read by OCR. The text is almost "
    "correct, so your only job is to fix the mistakes the OCR made and to leave everything else "
    "exactly as it is. The mistakes to fix are these: a letter read as a similar one (ب where a ت "
    "belongs, ح where a خ, س where a ش, ص where a ض, ط where a ظ, ع where a غ, ف where a ق, ه where "
    "a ة, ا where a ى, د where a ذ, ر where a ز), a dot that is missing, extra or on the wrong "
    "letter, a hamza that is missing or wrong, a dot or a mark that came from the line above or "
    "from the line below, two words stuck together, one word cut in two, and a punctuation or a "
    "digit misread. This is a repair and not a rewrite: do not rephrase, do not summarize, do not "
    "shorten, do not lengthen, do not translate, do not modernize the language, and do not explain "
    "anything. Keep the author's own words, the grammar, the old spelling conventions of the book "
    "and the punctuation. If a word looks unusual but may really be what the author wrote, leave "
    "it exactly as it is. Never invent text that is not there, and never drop any text that is "
    "there. "
    "The parts of the text that are Quran are marked with a [[ before them and a ]] after them. "
    "The marks are only a hint and they are often missing: the detector that put them there might "
    "make mistakes, so an ayah the OCR cut in half may carry no marks at all, and words "
    "that are really Quran may sit outside them. The OCR very often cuts an ayah in half"
    "so what sits between the marks may be only the beginning or only "
    "the end of an ayah, and the words just before or just after the marks may well be the "
    "missing part of that same ayah. Fix all of that as well: put back what is missing so that "
    "each ayah is spelled correctly"
    "e.g. [[aya part 1]] missed aya part 2 [[aya part 3]]"
    "should become a single aya"
    "they aya might have part 4 that is not written, don't add it."
    "Reply with only the corrected text, without the [[ and the ]] marks, with no explanations and "
    "no extra text."
)

# the marks the model was given, and the ones it may have copied into its answer
OPEN_MARK = "[["
CLOSE_MARK = "]]"


def mark_detected_ayas(text, matches):
    # the detector counts words, not letters: the words are indexed the same way here
    words = text.split()
    marked = list(words)
    cursor = 0
    for ayah in sorted(matches, key=lambda match: match["startInText"]):
        start = ayah["startInText"]
        end = min(ayah["endInText"], len(words))
        # the same words can match more than one ayah, keep the first and skip the overlap
        if start < cursor or start >= end:
            continue
        marked[start] = f"{OPEN_MARK} {words[start]}"
        # appending keeps both marks when the ayah is only one word long
        marked[end - 1] = f"{marked[end - 1]} {CLOSE_MARK}"
        cursor = end

    return " ".join(marked)


def remove_aya_marks(text):
    # the model is told not to copy the marks, but it sometimes does: they are not part of the text
    without_marks = text.replace(OPEN_MARK, " ").replace(CLOSE_MARK, " ")
    return re.sub(r"\s+", " ", without_marks).strip()


def refine_ocr_text(text):
    """Return the text with its OCR mistakes fixed, or the text itself if the
    llm answer can't be used (empty, or nothing left of the original)."""
    marked_text = mark_detected_ayas(text, quran_detector(text))
    response = client.chat.completions.create(
        # TODO:
        model="gpt-6-luna",
        # model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": marked_text},
        ],
    )
    refined = remove_aya_marks(response.choices[0].message.content or "")
    return refined or text


# an ocr block holds its paragraph as "<p>the text</p>", and that wrapper is kept as it is.
# the dot matters: without it a greedy match would swallow the "</p><p>" of two paragraphs
PARAGRAPH_HTML = re.compile(r"(<p>)(.*?)(</p>)", re.DOTALL)


def paragraph_text(block_html):
    """The text of an ocr block, with no html in it at all.

    Datalab writes markup inside the paragraph: <br/> between the lines of the printed
    page, <sup> around a footnote number, <small> around a note of its own. None of that
    is text the author wrote, and it must never reach the llm nor the reader. A tag
    becomes a single space, so the words on its two sides stay apart the way the line
    break in the book keeps them apart."""
    match = PARAGRAPH_HTML.search(block_html or "")
    inside = match.group(2) if match else (block_html or "")
    return re.sub(r"\s+", " ", html_module.unescape(re.sub(r"<[^>]+>", " ", inside))).strip()


def with_paragraph_text(block_html, text):
    """The same ocr block, with its paragraph replaced by the fixed text. The text is
    escaped, so a real "&" or "<" in the arabic stays a character of the text."""
    escaped = html_module.escape(text)
    match = PARAGRAPH_HTML.search(block_html or "")
    if not match:
        return f"<p>{escaped}</p>"
    return block_html[: match.start(2)] + escaped + block_html[match.end(2) :]


def refine_block_html(block_html):
    """The fixed ocr block. A block without text, and a block whose llm call
    failed, are left the way they were: one bad paragraph must not lose a page."""
    text = paragraph_text(block_html)
    if not text.strip():
        return block_html
    try:
        refined = refine_ocr_text(text)
    except Exception:
        return block_html
    return with_paragraph_text(block_html, refined)


def refine_page(page):
    """The ocr json of one page with the text of every paragraph fixed, one llm
    call per paragraph. The json is the same as it came in: same blocks, same ids,
    same bbox, same polygon, same metadata. Only the text of the paragraphs and the
    text of the page itself, which is those paragraphs one after the other, are new."""
    refined = copy.deepcopy(page)
    blocks = []
    collect_text_blocks(refined, blocks)
    if not blocks:
        return refined

    with ThreadPoolExecutor(max_workers=PARALLEL_REFINE) as pool:
        # map keeps the order, so every block gets the answer that belongs to it
        fixed = list(pool.map(lambda block: refine_block_html(block.get("html") or ""), blocks))

    for block, block_html in zip(blocks, fixed):
        block["html"] = block_html
    refined["html"] = "".join(block.get("html") or "" for block in refined.get("children") or [])
    return refined


def collect_text_blocks(node, found):
    """Every block of the page that carries text, whatever its block_type is: the body
    text, but also the footnotes and the section headers, which the table shows as rows
    of their own. Page headers and footers hold no text and are skipped, and so is the
    page node itself, whose text is the text of its blocks."""
    for block in node.get("children") or []:
        if paragraph_text(block.get("html") or ""):
            found.append(block)
        else:
            collect_text_blocks(block, found)