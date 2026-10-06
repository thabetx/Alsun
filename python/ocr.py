"""PDF -> structured JSON via Datalab API, refined by the llm.

For the pages asked for it runs Datalab and then the llm rewrites the text of every
paragraph. Nothing is kept between two requests: the browser keeps the ocr of a whole
book in localStorage (web/ocr-store.js), so a book that has already been read never
comes back here. Every ask pays for the pages it names.
"""

import os
from pathlib import Path

from datalab_sdk import ConvertOptions, DatalabClient

from refine_ocr import refine_page

API_KEY = "hOqLUjJtLx8Os_ZPtG1toGsRBoOVgiBbjwCeJqk8X00"


def datalab_api_key():
    # DATALAB_API_KEY in the .env file wins; the key written above is only what is used if there is none, so
    # nothing stops working. Put the key in .env and take it out of this file.
    return os.environ.get("DATALAB_API_KEY", "").strip() or API_KEY


ROOT = Path(__file__).resolve().parent.parent


def decompress_range(page_range):
    """'0,2-4' -> [0, 2, 3, 4] (0-indexed, deduped, sorted)."""
    pages = set()
    for token in page_range.replace(" ", "").split(","):
        if not token:
            continue
        if "-" in token:
            a, b = token.split("-")
            pages.update(range(int(a), int(b) + 1))
        else:
            pages.add(int(token))
    return sorted(pages)


def compress_range(pages):
    """[0, 4, 5] -> '0,4-5' (keeps the given indexing)."""
    out, start, prev = [], None, None
    for p in pages:
        if start is None:
            start = prev = p
        elif p == prev + 1:
            prev = p
        else:
            out.append(str(start) if start == prev else f"{start}-{prev}")
            start = prev = p
    if start is not None:
        out.append(str(start) if start == prev else f"{start}-{prev}")
    return ",".join(out)


def extract_pdf_segments(pdf, page_range):
    """Convert a pdf and return its blocks json for the asked pages, refined by the llm.

    page_range is 0-indexed ('0,2-4'). Nothing is kept between two requests; a book
    that has already been read is served whole from the browser (web/ocr-store.js).
    """
    wanted = decompress_range(page_range)
    result = DatalabClient(api_key=datalab_api_key()).convert(
        str(pdf),
        options=ConvertOptions(
            output_format="json", mode="accurate", paginate=True,
            page_range=compress_range(wanted),
        ),
    )
    by_page = {}
    for page in result.json.get("children", []):
        if page.get("block_type") != "Page":
            continue
        by_page[int(page["id"].split("/page/")[1].split("/")[0])] = page
    pages = [refine_page(by_page[p]) for p in wanted if p in by_page]
    return {"children": pages, "metadata": result.json.get("metadata")}


if __name__ == "__main__":
    print(extract_pdf_segments(ROOT / "data" / "two-pages.pdf", "0-1"))