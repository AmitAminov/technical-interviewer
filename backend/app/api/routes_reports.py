"""Report endpoints (DESIGN.md §3, §9) — with recovery via regenerate."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..core.report_generator import generate_report, load_report, report_status
from ..database import get_db
from ..models import InterviewSession
from ..schemas import ReportOut

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/sessions/{session_id}/report", response_model=ReportOut)
def get_report(session_id: str, db: Session = Depends(get_db)) -> ReportOut:
    sess = db.get(InterviewSession, session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="session not found")
    status = report_status(db, session_id)
    if status == "absent":
        raise HTTPException(status_code=404, detail="not ready")
    report = load_report(db, session_id)
    if report is None:
        # A row exists but generation failed / content unreadable.
        raise HTTPException(
            status_code=500,
            detail="report generation failed — POST "
            "/api/sessions/{0}/report/regenerate to retry".format(session_id),
        )
    return report


@router.post("/api/sessions/{session_id}/report/regenerate", response_model=ReportOut)
def regenerate_report(session_id: str, db: Session = Depends(get_db)) -> ReportOut:
    sess = db.get(InterviewSession, session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="session not found")
    try:
        return generate_report(db, session_id)
    except Exception:  # noqa: BLE001
        logger.exception("Report regeneration failed for %s", session_id)
        raise HTTPException(status_code=500, detail="report generation failed")
