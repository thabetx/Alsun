# Endpoints of the AI assistant, the merge and the re-translation.
# They only call the functions of the other modules; no logic lives here.
# The front keeps the rows / segments and sends them back, so the server keeps nothing.

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from merge_rows import build_rows_response, explain_merge_problem, merge_rows, unmerge_row
from modify_fragment import apply_fragment_replacement, suggest_fragment_replacement
from modify_many_paragraphs import modify_many_paragraphs_and_build_response
from glossary import clean_glossary
from llm import resolve_model, track_fallbacks
from retranslate_original import retranslate_edited_original

router = APIRouter()


class ModelChoice(BaseModel):
    provider: str
    model: str


def checked_model(choice):
    # the model the user chose in the settings (None = the default one); ValueError -> 400
    return resolve_model(None if choice is None else {"provider": choice.provider, "model": choice.model})


class GlossaryEntry(BaseModel):
    arabic: str
    translation: str


def checked_glossary(entries):
    # the glossary of the user comes with the request: checked here, ValueError -> 400
    return clean_glossary([{"arabic": entry.arabic, "translation": entry.translation} for entry in entries])


class FragmentRequest(BaseModel):
    segment: Dict[str, Any]
    fragment_start: int
    fragment_end: int
    instructions: str
    model: Optional[ModelChoice] = None
    glossary: List[GlossaryEntry] = []  # the terms of the user: the assistant keeps their translations


class ApplyFragmentRequest(BaseModel):
    segment: Dict[str, Any]
    fragment_start: int
    fragment_end: int
    expected_text: str
    replacement: str


class ModifyRowsRequest(BaseModel):
    paragraphs: List[List[Dict[str, Any]]]
    instructions: str
    model: Optional[ModelChoice] = None
    glossary: List[GlossaryEntry] = []


class RetranslateRequest(BaseModel):
    old_segments: List[Dict[str, Any]]
    new_original_text: str
    target_lang: str = "English"
    glossary: List[GlossaryEntry] = []
    quran_source: Optional[str] = None  # id of the quran translation (see QURAN_SOURCES in quran_detect.py)
    model: Optional[ModelChoice] = None


class MergeRequest(BaseModel):
    rows: List[Dict[str, Any]]
    selected_row_ids: List[str]


class UnmergeRequest(BaseModel):
    rows: List[Dict[str, Any]]
    merged_row_id: str


def refuse_with_message(error):
    # a ValueError of our functions is a message for the user, not a server crash
    return HTTPException(status_code=400, detail=str(error))


@router.post("/assistant/suggest-fragment")
def suggest_fragment(request: FragmentRequest):
    try:
        with track_fallbacks() as fallbacks:
            replacement = suggest_fragment_replacement(
                request.segment, request.fragment_start, request.fragment_end, request.instructions,
                checked_model(request.model), checked_glossary(request.glossary),
            )
    except ValueError as error:
        raise refuse_with_message(error)
    return {"replacement": replacement, **({"fallbacks": fallbacks} if fallbacks else {})}


@router.post("/assistant/apply-fragment")
def apply_fragment(request: ApplyFragmentRequest):
    try:
        segment = apply_fragment_replacement(
            request.segment, request.fragment_start, request.fragment_end,
            request.expected_text, request.replacement,
        )
    except ValueError as error:
        raise refuse_with_message(error)
    return {"segment": segment}


@router.post("/assistant/modify-rows")
def modify_rows(request: ModifyRowsRequest):
    try:
        with track_fallbacks() as fallbacks:
            answer = modify_many_paragraphs_and_build_response(
                request.paragraphs, request.instructions, checked_model(request.model), checked_glossary(request.glossary)
            )
    except ValueError as error:
        raise refuse_with_message(error)
    return {**answer, **({"fallbacks": fallbacks} if fallbacks else {})}


@router.post("/retranslate")
def retranslate(request: RetranslateRequest):
    try:
        with track_fallbacks() as fallbacks:
            answer = retranslate_edited_original(
                request.old_segments, request.new_original_text,
                target_lang=request.target_lang, glossary=checked_glossary(request.glossary),
                quran_source=request.quran_source, model=checked_model(request.model),
            )
    except ValueError as error:
        raise refuse_with_message(error)
    return {**answer, **({"fallbacks": fallbacks} if fallbacks else {})}


@router.post("/rows/merge-problem")
def merge_problem(request: MergeRequest):
    # only the ids and the order of the rows are needed to answer
    return {"problem": explain_merge_problem(request.rows, request.selected_row_ids)}


@router.post("/rows/merge")
def merge(request: MergeRequest):
    try:
        merged_rows = merge_rows(request.rows, request.selected_row_ids)
    except ValueError as error:
        raise refuse_with_message(error)

    ids_before = {row["id"] for row in request.rows}
    merged_row = next(row for row in merged_rows if row["id"] not in ids_before)
    return {"row": merged_row, "view": build_rows_response([merged_row])["rows"][0]}


@router.post("/rows/unmerge")
def unmerge(request: UnmergeRequest):
    try:
        rows_after = unmerge_row(request.rows, request.merged_row_id)
    except ValueError as error:
        raise refuse_with_message(error)

    merged_row = next(row for row in request.rows if row["id"] == request.merged_row_id)
    restored_ids = [source["id"] for source in merged_row["merged_from"]]
    restored_rows = [row for row in rows_after if row["id"] in restored_ids]
    return {"rows": restored_rows, "views": build_rows_response(restored_rows)["rows"]}
