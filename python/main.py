# Server entry point for the visualizer + translation agent.
#
# Serves the web app and exposes POST /translate, which delegates the actual
# translation work to quran_detect.py (quran ayahs come from the quran json
# files, normal text goes to the LLM). No translation logic lives here.
#
# Run it with:
#   serve.bat   (or: uvicorn python.main:app --reload)
# Then open http://127.0.0.1:8000 in your browser.

import sys
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Project root is one level up from this file (python/ -> project root).
ROOT = Path(__file__).resolve().parent.parent

# Load OPENAI_API_KEY from the .env file into the environment.
load_dotenv(ROOT / ".env")

# Make the python/ modules importable (quran_detect, paragraph_format, ...).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from quran_detect import translate_paragraph_and_build_response  # noqa: E402
from ocr import extract_pdf_segments  # noqa: E402
from assistant_routes import router as assistant_router, GlossaryEntry, checked_glossary  # noqa: E402
from pypdf import PdfReader  # noqa: E402

app = FastAPI()

# AI assistant, merge and re-translation endpoints.
app.include_router(assistant_router)

# Serve everything in web/ (index.html, css, js, images) at the root URL.
app.mount("/web", StaticFiles(directory=ROOT / "web"), name="web")

# Serve the data/ files (PDFs + JSON) used by the visualizer.
app.mount("/data", StaticFiles(directory=ROOT / "data"), name="data")


@app.get("/")
def serve_homepage():
    return FileResponse(ROOT / "web" / "index.html")


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


@app.post("/translate")
def translate(request: TranslateRequest):
    try:
        result = translate_paragraph_and_build_response(
            request.text, target_lang=request.target_lang, glossary=checked_glossary(request.glossary)
        )
    except ValueError as error:  # a language we have no quran translation for
        raise HTTPException(status_code=400, detail=str(error))
    # the frontend shows result["paragraph"]; segments are kept for editing.
    return {"translation": result["paragraph"], "parts": result["parts"], "segments": result["segments"]}