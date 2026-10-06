"""PDF -> structured JSON via Datalab API, cached per page (0-indexed).

Each page is written twice: `0.json` is what Datalab returned, and `0_refined.json`
is the same json after the llm fixed the text of every paragraph, one call each.
The refined file is what the app reads; it is built on the first load and reused
after that.
"""

import json
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
CACHE_DIR = ROOT / "data" / "ocr_cache"
REFINED_SUFFIX = "_refined"


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


def extract_pdf_segments(filename="two-pages.pdf", page_range="0-1"):
    """Convert a pdf from data/ and return its blocks json (cached per page)."""
    pdf = ROOT / "data" / filename
    if not pdf.exists():
        raise FileNotFoundError(f"PDF not found: {pdf}")
    return extract_segments_of_pdf(pdf, CACHE_DIR / pdf.stem, page_range)


def extract_segments_of_pdf(pdf, book, page_range):
    """Convert a pdf and return its blocks json (cached per page, in the folder `book`).

    page_range is 0-indexed ('0,2-4'). Only pages missing from the cache are
    sent to Datalab; e.g. a request for 0-5 with pages 1-3 cached queries
    datalab for '0,4-5'.
    """
    wanted = decompress_range(page_range)

    # whole-book cache is invalid if the pdf changed since it was cached
    meta_file = book / "meta.json"
    meta = {}
    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        fresh = meta.get("_source_mtime", 0) == pdf.stat().st_mtime
    except (json.JSONDecodeError, OSError):
        fresh = False
    if not fresh:
        meta = {"_source_mtime": pdf.stat().st_mtime}

    # which of the wanted pages are already on disk?
    have, missing = {}, []
    for p in wanted:
        f = book / f"{p}.json"
        if f.exists():
            try:
                have[p] = json.loads(f.read_text(encoding="utf-8"))
                continue
            except (json.JSONDecodeError, OSError):
                pass
        missing.append(p)

    # query datalab only for the missing pages (already 0-indexed)
    if missing:
        result = DatalabClient(api_key=datalab_api_key()).convert(
            str(pdf),
            options=ConvertOptions(
                output_format="json", mode="accurate", paginate=True,
                page_range=compress_range(missing),
            ),
        )
        data = result.json
        book.mkdir(parents=True, exist_ok=True)
        for page in data.get("children", []):
            if page.get("block_type") != "Page":
                continue
            n = int(page["id"].split("/page/")[1].split("/")[0])
            (book / f"{n}.json").write_text(
                json.dumps(page, ensure_ascii=False, indent=2), encoding="utf-8")
            have[n] = page
        meta["page_count"] = len(data.get("children", []))
        if data.get("metadata") is not None:
            meta["metadata"] = data["metadata"]
        meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    pages = [load_or_build_refined_page(book, p, have[p]) for p in wanted if p in have]
    return {"children": pages, "metadata": meta.get("metadata")}


def load_or_build_refined_page(book, page_number, raw_page):
    """The refined json of the page: `N_refined.json`. Built by the llm on the first
    load and read from disk on every load after that, so only the first load waits.

    The refined file goes stale when datalab writes the raw page again, which is the
    only thing that can change the text it was built from. The whole book mtime in
    meta.json is not enough: it stays behind as long as every page is cached, and
    datalab is only asked for the pages that are missing."""
    raw_file = book / f"{page_number}.json"
    target = book / f"{page_number}{REFINED_SUFFIX}.json"
    if target.exists():
        try:
            # an older refined file belongs to an older raw page. a raw page that is not
            # there to compare with leaves the refined one alone: it is the only copy of
            # that text left, and rebuilding it would throw the words away for nothing
            if not raw_file.exists() or target.stat().st_mtime_ns >= raw_file.stat().st_mtime_ns:
                return json.loads(target.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass  # a damaged cache is not worth keeping: refine the page again

    refined = refine_page(raw_page)
    book.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(refined, ensure_ascii=False, indent=2), encoding="utf-8")
    return refined


if __name__ == "__main__":
    print(extract_pdf_segments())