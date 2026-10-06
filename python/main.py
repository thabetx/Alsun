# Server entry point for the visualizer + translation agent.
#
# Serves the web app and exposes GET /ocr (the Datalab blocks json, refined by the
# llm, see ocr.py), POST /translate, which delegates the actual translation work to
# quran_detect.py (quran ayahs come from the quran json files, normal text goes to
# the LLM), and POST /detect-ayas. No translation logic lives here.
#
# Run it with:
#   serve.bat   (or: uvicorn python.main:app --reload)
# Then open http://127.0.0.1:8000 in your browser.

import sys
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

# Project root is one level up from this file (python/ -> project root).
ROOT = Path(__file__).resolve().parent.parent

# Load OPENAI_API_KEY from the .env file into the environment.
load_dotenv(ROOT / ".env")

# Make the python/ modules importable (quran_detect, paragraph_format, ...).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from quran_detect import (  # noqa: E402
    detector_is_ready,
    split_quran_and_normal_paragraph,
    translate_paragraph_and_build_response,
    warm_up_detector_in_background,
)
from books import (  # noqa: E402
    MAX_PAGES_PER_REQUEST, MAX_UPLOAD_BYTES, check_page_range, find_book, save_upload,
)
from ocr import extract_pdf_segments  # noqa: E402
from assistant_routes import (  # noqa: E402
    router as assistant_router, GlossaryEntry, ModelChoice, checked_glossary, checked_model,
)
from settings_routes import router as settings_router  # noqa: E402
from llm import track_fallbacks  # noqa: E402

app = FastAPI()

# AI assistant, merge and re-translation endpoints.
app.include_router(assistant_router)
app.include_router(settings_router)

# ---------- the pages ----------
#   /      the home page (upload the book, choose the language)
#   /app   the viewer: the arabic text and the translation side by side
# Any other address that does not exist gets the page web/404.html (see not_found_page below).
# The old addresses of the two files still work: they go to the new ones.
# These routes come before the mount of web/, which would answer for the same files.

@app.get("/", include_in_schema=False)
def serve_home_page():
    return FileResponse(ROOT / "web" / "home.html")


@app.get("/app", include_in_schema=False)
def serve_viewer_page():
    return FileResponse(ROOT / "web" / "index.html")


@app.get("/web/home.html", include_in_schema=False)
def old_home_address():
    return RedirectResponse("/", status_code=307)


@app.get("/web/index.html", include_in_schema=False)
def old_viewer_address():
    return RedirectResponse("/app", status_code=307)


@app.get("/health")
def health():
    # for serve.bat (it opens the browser when this answers) and for anything that watches the server
    return {"status": "ok", "detector": "ready" if detector_is_ready() else "not loaded yet"}


@app.post("/warmup")
def warmup():
    # The page calls this when the user chooses a book: the quran detector (the slow part to build) starts to load
    # in the background, so the translation does not wait for it. It does nothing if it is loaded or loading.
    warm_up_detector_in_background()
    return {"detector": "ready" if detector_is_ready() else "loading"}


@app.exception_handler(StarletteHTTPException)
async def not_found_page(request, error):
    # A browser that opens an address that does not exist sees our page; everything else (a script asking for
    # a file, an api call) gets the usual short answer.
    asks_for_a_page = request.method == "GET" and "text/html" in request.headers.get("accept", "")
    if error.status_code == 404 and asks_for_a_page:
        return FileResponse(ROOT / "web" / "404.html", status_code=404)
    return await http_exception_handler(request, error)


# Serve everything in web/ (css, js, images) at /web.
app.mount("/web", StaticFiles(directory=ROOT / "web"), name="web")

# Serve the data/ files (PDFs + JSON) used by the visualizer.
app.mount("/data", StaticFiles(directory=ROOT / "data"), name="data")


# ---------- the books: the samples of data/ and the pdfs the users upload (see books.py) ----------

@app.post("/books")
async def upload_book(request: Request, name: str = "book.pdf"):
    """The pdf is the body of the request (no form). Gives the book: {id, name, pages, size}."""
    declared = request.headers.get("content-length", "")
    too_big = HTTPException(status_code=413, detail=f"the file is bigger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    if declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
        raise too_big
    data = bytearray()
    async for chunk in request.stream():  # the size is checked while the file arrives, not after
        data.extend(chunk)
        if len(data) > MAX_UPLOAD_BYTES:
            raise too_big
    try:
        book = await run_in_threadpool(save_upload, bytes(data), name)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    return book.as_dict()


def book_or_error(book_id):
    try:
        return find_book(book_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="there is no such book")
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@app.get("/books/{book_id}")
def book_info(book_id: str):
    return book_or_error(book_id).as_dict()


@app.get("/books/{book_id}/pdf")
def book_pdf(book_id: str):
    return FileResponse(book_or_error(book_id).path, media_type="application/pdf")  # shown in the page, not saved


@app.get("/ocr")
def ocr(book: Optional[str] = None, page_range: Optional[str] = None, filename: Optional[str] = None):
    """The Datalab blocks json of some pages of a book, fixed by the llm (kept by the browser, see ocr.py).

    page_range is 0-indexed ("0-4,7"), at most MAX_PAGES_PER_REQUEST pages: the front reads a long book
    a few pages at a time. A short book can be asked without it. `filename` is the old name of `book`.
    """
    found = book_or_error(book or filename or "فقه الاستدراك.pdf")
    if page_range is None and found.pages > MAX_PAGES_PER_REQUEST:
        raise HTTPException(status_code=400, detail="the page range is not valid")
    try:
        wanted = check_page_range(page_range or f"0-{found.pages - 1}", found.pages)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    try:
        return extract_pdf_segments(found.path, wanted)
    except Exception as error:  # noqa: BLE001 - the ocr service is outside, whatever it raises is "the ocr failed"
        raise HTTPException(status_code=502, detail=f"the ocr failed: {type(error).__name__}")


# This describes the JSON body the frontend must send to /translate.
# FastAPI uses it to validate the request automatically.
class TranslateRequest(BaseModel):
    text: str
    target_lang: str  # a key of QURAN_FILES in quran_detect.py: "English", "French", ...
    glossary: List[GlossaryEntry] = []  # the terms of the user for target_lang (see glossary.py)
    quran_source: Optional[str] = None  # id of the quran translation (see QURAN_SOURCES in quran_detect.py)
    model: Optional[ModelChoice] = None  # the model the user chose in the settings (see llm.py)
    trusted_terms: bool = True  # the trusted Islamic terms (see trusted_terms.py), unless the user turned them off in the settings


@app.post("/translate")
def translate(request: TranslateRequest):
    try:
        with track_fallbacks() as fallbacks:
            result = translate_paragraph_and_build_response(
                request.text, target_lang=request.target_lang, glossary=checked_glossary(request.glossary),
                quran_source=request.quran_source, model=checked_model(request.model),
                use_trusted_terms=request.trusted_terms,
            )
    except ValueError as error:  # a language we have no quran translation for, a bad choice, no model answering
        raise HTTPException(status_code=400, detail=str(error))
    # the frontend shows result["paragraph"]; segments are kept for editing.
    answer = {"translation": result["paragraph"], "parts": result["parts"], "segments": result["segments"]}
    if fallbacks:  # the chosen model did not answer, another one did (see llm.py)
        answer["fallbacks"] = fallbacks
    return answer


# This describes the JSON body the frontend must send to /detect-ayas.
class DetectAyahsRequest(BaseModel):
    text: str


@app.post("/detect-ayas")
def detect_ayas(request: DetectAyahsRequest):
    # the detector only, no llm: the segments say what is quran and what is normal text,
    # their "text" is the arabic itself (nothing was translated).
    return {"segments": split_quran_and_normal_paragraph(request.text)}
