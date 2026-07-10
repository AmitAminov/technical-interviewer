"""Privacy / deletion endpoints (DESIGN.md §3, §11).

- DELETE /api/sessions/{id} — full cascade delete (questions, answers,
  scores, transcript, citations, report, session row).
- DELETE /api/sessions/{id}/transcript — transcript entries plus the
  encrypted per-answer transcripts and resume/JD blobs.
- DELETE /api/sessions/{id}/recording — MVP: "recording" is only the
  record_session flag (no A/V is ever stored; documented per DESIGN.md §11).
  Deleting clears the flag.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..core import transcript as transcript_store
from ..database import get_db
from ..models import Answer, InterviewSession, Question
from ..security.crypto import encrypt_text

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_session(db: Session, session_id: str) -> InterviewSession:
    sess = db.get(InterviewSession, session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="session not found")
    return sess


@router.delete("/api/sessions/{session_id}")
def delete_session(session_id: str, db: Session = Depends(get_db)) -> dict:
    sess = _get_session(db, session_id)
    # ORM cascades handle questions→answers→scores, transcript, citations, report.
    db.delete(sess)
    db.commit()
    logger.info("Fully deleted session %s", session_id)
    return {"status": "deleted", "session_id": session_id}


@router.delete("/api/sessions/{session_id}/transcript")
def delete_session_transcript(session_id: str, db: Session = Depends(get_db)) -> dict:
    _get_session(db, session_id)
    removed = transcript_store.delete_transcript(db, session_id, commit=False)
    # Also wipe per-answer encrypted transcripts and resume/JD source texts.
    answer_ids = (
        db.query(Answer.id)
        .join(Question, Answer.question_id == Question.id)
        .filter(Question.session_id == session_id)
        .all()
    )
    for (answer_id,) in answer_ids:
        answer = db.get(Answer, answer_id)
        if answer is not None:
            answer.transcript_enc = encrypt_text("")
    sess = db.get(InterviewSession, session_id)
    if sess is not None:
        sess.resume_text_enc = None
        sess.job_description_enc = None
    db.commit()
    return {"status": "deleted", "session_id": session_id, "entries_removed": removed}


@router.delete("/api/sessions/{session_id}/recording")
def delete_session_recording(session_id: str, db: Session = Depends(get_db)) -> dict:
    sess = _get_session(db, session_id)
    # MVP: no audio/video is ever persisted; recording == record_session flag.
    sess.record_session = False
    db.commit()
    return {
        "status": "deleted",
        "session_id": session_id,
        "note": "No A/V media is stored in the MVP; the recording flag was cleared.",
    }
