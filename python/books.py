"""The books of the app: the sample pdfs in data/ and the pdfs the users upload.

A book is named by a short text, `book`:
  - the file name of a sample ("yaqzan.pdf"): a pdf that is in data/
  - the id of an uploaded book ("3fa9c1d2b7e04a58"): the first 16 characters of the sha256 of its bytes, so the
    same file uploaded twice is one book (and its ocr is not paid for twice)

An uploaded pdf is kept in uploads/ (outside data/, which the server shows to everyone) with its ocr cache next to
it. The name the user gave the file is only text to show: no path is ever made from it.
"""

import hashlib
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PyPdfError

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DIR = ROOT / "data"
UPLOAD_DIR = ROOT / "uploads"

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB
MAX_PAGES = 200  # every page is read by the ocr, which is paid by the page
MAX_NAME_CHARS = 120

# a sample pdf in data/: any letters (also arabic) and spaces are fine, but no folder separators and no control
# characters, so a path is never followed
SAMPLE_NAME = re.compile(r"[\w][\w\s._-]{0,80}\.pdf")
UPLOAD_ID = re.compile(r"[0-9a-f]{16}")


@dataclass(frozen=True)
class Book:
    book: str  # the text that names it (see above)
    name: str  # what the user sees
    path: Path  # the pdf
    pages: int
    size: int
    sample: bool

    def as_dict(self):
        # "modified" is when the pdf itself last changed. The browser keeps the ocr of a book in
        # localStorage (web/ocr-store.js) and uses this to know that the file it read before is not
        # this one any more; seconds, so the number stays exact in a javascript Number.
        try:
            modified = int(self.path.stat().st_mtime)
        except OSError:
            modified = 0
        return {"id": self.book, "name": self.name, "pages": self.pages, "size": self.size,
                "sample": self.sample, "modified": modified}


def clean_name(name):
    # only text to show: the folders, the control characters and the length are taken off
    name = (name or "").replace("\\", "/").split("/")[-1]
    name = "".join(char for char in name if char.isprintable()).strip()
    return name[:MAX_NAME_CHARS] or "book.pdf"


def read_pdf(data):
    # Gives the number of pages, or raises ValueError with a message for the user.
    if not data:
        raise ValueError("the file is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError(f"the file is bigger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    if not data.startswith(b"%PDF-"):
        raise ValueError("the file is not a pdf")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ValueError("the pdf is protected by a password")
        pages = len(reader.pages)
    except ValueError:
        raise
    except (PyPdfError, OSError, KeyError, TypeError, AttributeError, RecursionError) as error:
        raise ValueError("the pdf can not be read") from error
    if pages == 0:
        raise ValueError("the pdf has no pages")
    if pages > MAX_PAGES:
        raise ValueError(f"the pdf has more than {MAX_PAGES} pages")
    return pages


def save_upload(data, name):
    # Keeps an uploaded pdf and gives its Book. The same bytes give the same book.
    pages = read_pdf(data)
    book_id = hashlib.sha256(data).hexdigest()[:16]
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    pdf = UPLOAD_DIR / f"{book_id}.pdf"
    if not pdf.exists():
        pdf.write_bytes(data)
    meta = {"name": clean_name(name), "pages": pages, "size": len(data)}
    meta_file = UPLOAD_DIR / f"{book_id}.json"
    if not meta_file.exists():  # the name of the first upload stays
        meta_file.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return find_book(book_id)


def find_book(book):
    # The Book of this text, or FileNotFoundError (there is no such book) or ValueError (it is not a book name at all).
    if UPLOAD_ID.fullmatch(book or ""):
        pdf = UPLOAD_DIR / f"{book}.pdf"
        if not pdf.is_file():
            raise FileNotFoundError(f"no book {book}")
        try:
            meta = json.loads((UPLOAD_DIR / f"{book}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
        return Book(
            book=book, name=meta.get("name") or "book.pdf", path=pdf,
            pages=int(meta.get("pages") or count_pages(pdf)), size=pdf.stat().st_size, sample=False,
        )

    if SAMPLE_NAME.fullmatch(book or ""):
        pdf = SAMPLE_DIR / book
        if not pdf.is_file():
            raise FileNotFoundError(f"no book {book}")
        return Book(
            book=book, name=book, path=pdf,
            pages=count_pages(pdf), size=pdf.stat().st_size, sample=True,
        )

    raise ValueError("the book name is not valid")


def count_pages(pdf):
    return len(PdfReader(str(pdf)).pages)


PAGE_RANGE = re.compile(r"\d{1,4}(-\d{1,4})?(,\d{1,4}(-\d{1,4})?)*")
MAX_PAGES_PER_REQUEST = 10


def check_page_range(page_range, pages):
    # "0-4,7": 0-indexed pages of the book. Gives the same text, or raises ValueError.
    if not PAGE_RANGE.fullmatch(page_range or ""):
        raise ValueError("the page range is not valid")
    wanted = set()
    for token in page_range.split(","):
        first, _, last = token.partition("-")
        first, last = int(first), int(last or first)
        if first > last:
            raise ValueError("the page range is not valid")
        wanted.update(range(first, last + 1))
        if len(wanted) > MAX_PAGES_PER_REQUEST:
            raise ValueError(f"more than {MAX_PAGES_PER_REQUEST} pages in one request")
    if max(wanted) >= pages:
        raise ValueError("the page range is outside the book")
    return page_range
