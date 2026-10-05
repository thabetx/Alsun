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
from fastapi import FastAPI, HTTPException
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

# Project root is one level up from this file (python/ -> project root).
ROOT = Path(__file__).resolve().parent.parent

# Load OPENAI_API_KEY from the .env file into the environment.
load_dotenv(ROOT / ".env")

# Make the python/ modules importable (quran_detect, paragraph_format, ...).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from quran_detect import (  # noqa: E402
    split_quran_and_normal_paragraph,
    translate_paragraph_and_build_response,
)
from ocr import extract_pdf_segments  # noqa: E402
from assistant_routes import (  # noqa: E402
    router as assistant_router, GlossaryEntry, ModelChoice, checked_glossary, checked_model,
)
from settings_routes import router as settings_router  # noqa: E402
from llm import track_fallbacks  # noqa: E402
from pypdf import PdfReader  # noqa: E402

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


@app.get("/ocr")
def ocr(filename: str = "two-pages.pdf"):
    """Run Datalab OCR on a whole PDF from data/ and return the JSON."""
    pdf = ROOT / "data" / filename
    n = len(PdfReader(str(pdf)).pages)
    return extract_pdf_segments(filename, page_range=f"0-{n - 1}")


# This describes the JSON body the frontend must send to /translate.
# FastAPI uses it to validate the request automatically.
class TranslateRequest(BaseModel):
    text: str
    target_lang: str  # a key of QURAN_FILES in quran_detect.py: "English", "French", ...
    glossary: List[GlossaryEntry] = []  # the terms of the user for target_lang (see glossary.py)
    quran_source: Optional[str] = None  # id of the quran translation (see QURAN_SOURCES in quran_detect.py)
    model: Optional[ModelChoice] = None  # the model the user chose in the settings (see llm.py)


@app.post("/translate")
def translate(request: TranslateRequest):
    try:
        with track_fallbacks() as fallbacks:
            result = translate_paragraph_and_build_response(
                request.text, target_lang=request.target_lang, glossary=checked_glossary(request.glossary),
                quran_source=request.quran_source, model=checked_model(request.model),
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
