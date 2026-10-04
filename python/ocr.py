"""PDF -> structured JSON via Datalab API, cached per page (0-indexed)."""

import json
from pathlib import Path

from datalab_sdk import ConvertOptions, DatalabClient

API_KEY = "hOqLUjJtLx8Os_ZPtG1toGsRBoOVgiBbjwCeJqk8X00"
ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data" / "ocr_cache"


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
    """Convert a pdf from data/ and return its blocks json (cached per page).

    page_range is 0-indexed ('0,2-4'). Only pages missing from the cache are
    sent to Datalab; e.g. a request for 0-5 with pages 1-3 cached queries
    datalab for '0,4-5'.
    """
    pdf = ROOT / "data" / filename
    if not pdf.exists():
        raise FileNotFoundError(f"PDF not found: {pdf}")
    book = CACHE_DIR / pdf.stem
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
        result = DatalabClient(api_key=API_KEY).convert(
            str(pdf),
            options=ConvertOptions(
                output_format="json", mode="fast", paginate=True,
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

    pages = [have[p] for p in wanted if p in have]
    return {"children": pages, "metadata": meta.get("metadata")}


if __name__ == "__main__":
    print(extract_pdf_segments())