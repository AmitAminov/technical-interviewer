"""Misc endpoints: health, question bank, RAG search, QA run, resume parsing.

DESIGN.md §3. All Agent-B integrations are lazy + fault-tolerant so these
endpoints work (with degraded answers) even when app.llm / app.rag /
app.agents are missing.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Query, UploadFile
from pydantic import BaseModel, Field

from ..config import PROJECT_ROOT, settings
from ..core.parsing import parse_job_description, parse_resume
from ..schemas import QuestionBankItem
from .routes_sessions import load_bank

logger = logging.getLogger(__name__)

router = APIRouter()


class RagSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    k: int = Field(default=5, ge=1, le=25)


@router.get("/api/health")
def health() -> Dict[str, Any]:
    llm_provider = "offline"
    try:
        from ..llm.provider import get_provider  # lazy: Agent B

        llm_provider = get_provider().name
    except Exception:  # noqa: BLE001
        pass
    wiki_index_loaded = False
    try:
        from ..rag.retriever import get_retriever  # lazy: Agent B

        wiki_index_loaded = bool(get_retriever().loaded)
    except Exception:  # noqa: BLE001
        pass
    voice_engine = "unavailable"
    try:
        from .routes_voice import probe_voice_engine

        voice_engine = probe_voice_engine()  # cached ~10s, ~0.5s worst case
    except Exception:  # noqa: BLE001
        pass
    lipsync_engine = "unavailable"
    try:
        from .routes_deepfake import probe_lipsync_engine

        lipsync_engine = probe_lipsync_engine()  # cached ~10s
    except Exception:  # noqa: BLE001
        pass
    return {
        "status": "ok",
        "version": settings.version,
        "llm_provider": llm_provider,
        "wiki_index_loaded": wiki_index_loaded,
        "voice_engine": voice_engine,
        "lipsync_engine": lipsync_engine,
    }


@router.get("/api/question-bank", response_model=List[QuestionBankItem])
def question_bank(
    role: Optional[str] = Query(default=None),
    difficulty: Optional[str] = Query(default=None),
    topic: Optional[str] = Query(default=None),
) -> List[QuestionBankItem]:
    items = load_bank()
    if role:
        items = [i for i in items if i.role == role]
    if difficulty:
        items = [i for i in items if i.difficulty == difficulty]
    if topic:
        items = [i for i in items if i.topic == topic]
    return items


@router.post("/api/rag/search")
def rag_search(payload: RagSearchRequest) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    try:
        from ..rag.retriever import get_retriever  # lazy: Agent B

        retriever = get_retriever()
        if retriever.loaded:
            results = [r.model_dump() for r in retriever.search(payload.query, k=payload.k)]
    except Exception:  # noqa: BLE001
        logger.warning("RAG search failed", exc_info=True)
    return {"results": results}


@router.post("/api/qa/run")
def qa_run() -> Dict[str, Any]:
    """Run the Codex QA agent (may take on the order of a minute)."""
    try:
        from ..agents.qa_agent import format_report, run_qa  # lazy: Agent B

        report = run_qa(str(PROJECT_ROOT))
        return {"report": format_report(report), "passed": report.status == "PASS"}
    except Exception:  # noqa: BLE001
        logger.exception("QA agent run failed")
        return {"report": "QA Status: FAIL\nCritical Issues:\n- QA agent unavailable or crashed\n", "passed": False}


@router.post("/api/parse-resume")
async def parse_resume_upload(file: UploadFile = File(...)) -> Dict[str, Any]:
    """Convenience endpoint (extension beyond the contract's REST list):
    the SetupPage uploads a .pdf/.txt resume here and receives
    ``{raw_text, skills, topics}`` to place into ``SessionCreate.resume_text``.
    """
    data = await file.read()
    return parse_resume(data, file.filename or "")


class JDParseRequest(BaseModel):
    text: str = ""


@router.post("/api/parse-job-description")
def parse_jd(payload: JDParseRequest) -> Dict[str, Any]:
    """Companion convenience endpoint for job-description text."""
    return parse_job_description(payload.text)
