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

from dotenv import load_dotenv
from fastapi import FastAPI
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

app = FastAPI()

# Serve everything in web/ (index.html, css, js, images) at the root URL.
app.mount("/web", StaticFiles(directory=ROOT / "web"), name="web")

# Serve the data/ files (PDFs + JSON) used by the visualizer.
app.mount("/data", StaticFiles(directory=ROOT / "data"), name="data")


@app.get("/")
def serve_homepage():
    return FileResponse(ROOT / "web" / "index.html")


# This describes the JSON body the frontend must send to /translate.
# FastAPI uses it to validate the request automatically.
class TranslateRequest(BaseModel):
    text: str
    target_lang: str  # "English" or "French"


@app.post("/translate")
def translate(request: TranslateRequest):
    result = translate_paragraph_and_build_response(request.text)
    # the frontend shows result["paragraph"]; segments are kept for editing.
    return {"translation": result["paragraph"], "segments": result["segments"]}