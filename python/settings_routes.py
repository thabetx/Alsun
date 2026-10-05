# Endpoints of the settings window: what the user can choose (models, quran translations),
# and the change of the quran translation of rows that are already translated.

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from llm import model_options
from quran_detect import find_quran_source, quran_source_options, swap_quran_source

router = APIRouter()


@router.get("/settings/options")
def settings_options():
    return {"models": model_options(), "quran_sources": quran_source_options()}


class RowSegments(BaseModel):
    id: str
    segments: List[Dict[str, Any]]


class SwapQuranSourceRequest(BaseModel):
    target_lang: str
    quran_source: str
    rows: List[RowSegments]


@router.post("/quran/swap-source")
def swap_quran_source_of_rows(request: SwapQuranSourceRequest):
    # no llm here: the ayahs are written again from the file of the chosen quran translation
    try:
        find_quran_source(request.target_lang, request.quran_source)  # refused even if there are no rows
        rows = [
            {"id": row.id, "segments": swap_quran_source(row.segments, request.target_lang, request.quran_source)}
            for row in request.rows
        ]
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    return {"rows": rows}
