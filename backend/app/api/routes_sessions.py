"""Session endpoints incl. synchronous planning (DESIGN.md §3).

``POST /api/sessions`` runs the whole planning pipeline inline (< 30s):
load the question bank → (optional, capped) internet research agent →
planning agent → materialize Question rows from ``plan.section_questions``.
Every agent step degrades gracefully to a deterministic bank-only plan; this
endpoint must never 500 because an agent misbehaved.

Agent-B modules (llm/rag/agents) are imported lazily inside functions so the
app imports and runs even when they are absent.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import settings
from ..core import transcript as transcript_store
from ..core.parsing import parse_job_description, parse_resume
from ..core.question_selector import generate_fallback_item, select_questions
from ..database import get_db
from ..models import InterviewSession, Question, SourceCitation, User
from ..schemas import (
    TRACK_TOPICS,
    InterviewPlan,
    QuestionBankItem,
    SessionCreate,
    SessionOut,
    SourceCitationOut,
    TranscriptOut,
)
from ..security.crypto import encrypt_text

logger = logging.getLogger(__name__)

router = APIRouter()

BACKGROUND_SECTION = "background"
CANDIDATE_QUESTIONS_SECTION = "candidate questions"

_FALLBACK_BACKGROUND_POINTS = [
    "relevant experience",
    "clear narrative",
    "motivation for the role",
]

# Technical questions per topic section by mode: (n_topic_sections, per_section)
_MODE_SHAPE: Dict[str, Tuple[int, int]] = {
    "Quick Practice": (2, 2),
    "Standard": (4, 2),
    "Deep Research": (5, 3),
}


# ---------------------------------------------------------------- helpers
def session_to_out(sess: InterviewSession) -> SessionOut:
    plan = None
    if sess.plan:
        try:
            plan = InterviewPlan.model_validate(sess.plan)
        except Exception:  # noqa: BLE001
            logger.warning("Stored plan for %s is invalid", sess.id, exc_info=True)
    return SessionOut(
        id=sess.id,
        user_id=sess.user_id,
        role=sess.role,
        mode=sess.mode,
        difficulty=sess.difficulty,
        duration_minutes=sess.duration_minutes,
        language=sess.language,
        hint_policy=sess.hint_policy,
        interviewer_style=sess.interviewer_style,
        use_resume=sess.use_resume,
        use_job_description=sess.use_job_description,
        use_wiki=sess.use_wiki,
        allow_internet=sess.allow_internet,
        record_session=sess.record_session,
        disable_cloud_ai=sess.disable_cloud_ai,
        status=sess.status,
        overall_score=sess.overall_score,
        plan=plan,
        created_at=sess.created_at,
        completed_at=sess.completed_at,
    )


def load_bank() -> List[QuestionBankItem]:
    """Load seed + internet question banks; invalid items are skipped."""
    items: List[QuestionBankItem] = []
    seen: set = set()
    for path_str in (settings.question_bank_path, settings.internet_bank_path):
        path = Path(path_str)
        if not path.exists():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("Could not read question bank %s", path, exc_info=True)
            continue
        if not isinstance(raw, list):
            continue
        for entry in raw:
            try:
                item = QuestionBankItem.model_validate(entry)
            except Exception:  # noqa: BLE001
                continue
            if item.id in seen:
                continue
            seen.add(item.id)
            items.append(item)
    return items


class _NullRetriever:
    """Safe stand-in when app.rag is unavailable."""

    loaded = False

    def search(self, query: str, k: int = 5) -> List[Any]:  # noqa: ARG002
        return []


def _get_retriever() -> Any:
    try:
        from ..rag.retriever import get_retriever  # lazy: Agent B

        return get_retriever()
    except Exception:  # noqa: BLE001
        return _NullRetriever()


def _get_provider(disable_cloud_ai: bool) -> Optional[Any]:
    try:
        from ..llm.provider import get_provider  # lazy: Agent B

        # fast_only: synchronous session planning must finish well inside the
        # spec's 30s bound; the Claude CLI's 10-60s per-call variance does not
        # fit here (it still powers background report narratives).
        return get_provider(disable_cloud_ai=disable_cloud_ai, fast_only=True)
    except Exception:  # noqa: BLE001
        return None


def _fallback_plan(
    cfg: SessionCreate,
    bank: List[QuestionBankItem],
    extra_topics: List[str],
) -> Tuple[InterviewPlan, Dict[str, QuestionBankItem]]:
    """Deterministic bank-only plan used when the planning agent fails.

    Returns the plan plus a map of generated items (id -> item) for sections
    the bank could not fill, so question-row creation can resolve them.
    """
    n_sections, per_section = _MODE_SHAPE.get(cfg.mode, (3, 2))
    role_topics = TRACK_TOPICS.get(cfg.role, [])
    ordered_topics: List[str] = []
    for t in list(cfg.focus_topics) + extra_topics + role_topics:
        if t in role_topics and t not in ordered_topics:
            ordered_topics.append(t)
    if not ordered_topics:
        ordered_topics = list(role_topics) or ["General"]
    topics = ordered_topics[:n_sections]

    generated: Dict[str, QuestionBankItem] = {}
    section_questions: Dict[str, List[str]] = {BACKGROUND_SECTION: []}
    exclude: List[str] = []
    for topic in topics:
        picked = select_questions(bank, cfg.role, cfg.difficulty, [topic], per_section, exclude)
        while len(picked) < per_section:
            gen = generate_fallback_item(cfg.role, topic, cfg.difficulty, cfg.language)
            generated[gen.id] = gen
            picked.append(gen)
        section_questions[topic] = [q.id for q in picked]
        exclude.extend(q.id for q in picked)

    # One behavioral question when the bank offers any.
    behavioral = select_questions(bank, cfg.role, cfg.difficulty, ["Behavioral"], 1, exclude)
    sections = [BACKGROUND_SECTION] + topics
    if behavioral:
        sections.append("behavioral")
        section_questions["behavioral"] = [behavioral[0].id]
    sections.append(CANDIDATE_QUESTIONS_SECTION)
    section_questions[CANDIDATE_QUESTIONS_SECTION] = []

    plan = InterviewPlan(
        role=cfg.role,
        duration_minutes=cfg.duration_minutes,
        sections=sections,
        difficulty=cfg.difficulty,
        section_questions=section_questions,
        focus_topics=topics,
        rubric_notes={
            "overall": [
                "correctness and depth first",
                "clear structured communication",
                "practical trade-off awareness",
            ]
        },
    )
    return plan, generated


def _background_question_text(cfg: SessionCreate, provider: Optional[Any]) -> str:
    try:
        from ..llm.interviewer import background_question  # lazy: Agent B

        text = background_question(cfg.role, provider, cfg.language)
        if text and str(text).strip():
            return str(text).strip()
    except Exception:  # noqa: BLE001
        logger.debug("background_question unavailable", exc_info=True)
    return (
        "To start, tell me briefly about your background: your experience "
        "most relevant to the {0} role, and what kind of problems you enjoy "
        "working on.".format(cfg.role)
    )


def _materialize_questions(
    db: Session,
    sess: InterviewSession,
    cfg: SessionCreate,
    plan: InterviewPlan,
    bank_by_id: Dict[str, QuestionBankItem],
    provider: Optional[Any],
) -> None:
    """Create ordered Question rows from plan.section_questions."""
    order = 0
    for section in plan.sections:
        if section == BACKGROUND_SECTION:
            db.add(
                Question(
                    session_id=sess.id,
                    topic="Background",
                    difficulty=cfg.difficulty,
                    question_text=_background_question_text(cfg, provider),
                    source="generated",
                    expected_points=list(_FALLBACK_BACKGROUND_POINTS),
                    section=BACKGROUND_SECTION,
                    order_idx=order,
                    is_behavioral=True,
                )
            )
            order += 1
            continue
        if section == CANDIDATE_QUESTIONS_SECTION:
            continue  # no bank questions; handled live by the orchestrator
        want_he = (cfg.language or "en").lower().startswith("he")
        for qid in plan.section_questions.get(section, []):
            item = bank_by_id.get(qid)
            if item is None:
                logger.warning("Plan references unknown question id %s", qid)
                continue
            # Hebrew sessions use the pre-translated bank text + expected points
            # so the whole interview (and offline keyword scoring) works in
            # Hebrew without a live translation call. Falls back to English if a
            # given item wasn't translated.
            q_text = item.question_text
            q_points = list(item.expected_points)
            if want_he and getattr(item, "question_text_he", ""):
                q_text = item.question_text_he
                if getattr(item, "expected_points_he", None):
                    q_points = list(item.expected_points_he)
            db.add(
                Question(
                    session_id=sess.id,
                    topic=item.topic,
                    difficulty=item.difficulty,
                    question_text=q_text,
                    source=item.source,
                    expected_points=q_points,
                    section=section,
                    order_idx=order,
                    is_behavioral=item.is_behavioral,
                )
            )
            order += 1
    if order <= 1:
        # Safety net: guarantee at least a couple of technical questions.
        for topic in TRACK_TOPICS.get(cfg.role, ["General"])[:2]:
            gen = generate_fallback_item(cfg.role, topic, cfg.difficulty, cfg.language)
            db.add(
                Question(
                    session_id=sess.id,
                    topic=gen.topic,
                    difficulty=gen.difficulty,
                    question_text=gen.question_text,
                    source=gen.source,
                    expected_points=list(gen.expected_points),
                    section=topic,
                    order_idx=order,
                    is_behavioral=False,
                )
            )
            if topic not in plan.sections:
                plan.sections.insert(len(plan.sections) - 1 if CANDIDATE_QUESTIONS_SECTION in plan.sections else len(plan.sections), topic)
                plan.section_questions[topic] = [gen.id]
            order += 1


# ---------------------------------------------------------------- endpoints
@router.post("/api/sessions", response_model=SessionOut)
def create_session(payload: SessionCreate, db: Session = Depends(get_db)) -> SessionOut:
    user = db.get(User, payload.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")

    resume_text = payload.resume_text if payload.use_resume else None
    if resume_text and resume_text.lstrip().startswith("data:"):
        # PDF upload arrives as a base64 data URL in the string field;
        # normalize to extracted text before storage/planning.
        resume_text = str(parse_resume(resume_text, "resume.pdf")["raw_text"]) or None
    jd_text = payload.job_description if payload.use_job_description else None

    sess = InterviewSession(
        user_id=payload.user_id,
        role=payload.role,
        mode=payload.mode,
        difficulty=payload.difficulty,
        duration_minutes=payload.duration_minutes,
        language=payload.language,
        hint_policy=payload.hint_policy,
        interviewer_style=payload.interviewer_style,
        use_resume=payload.use_resume,
        use_job_description=payload.use_job_description,
        use_wiki=payload.use_wiki,
        allow_internet=payload.allow_internet,
        record_session=payload.record_session,
        disable_cloud_ai=payload.disable_cloud_ai,
        resume_text_enc=encrypt_text(resume_text),
        job_description_enc=encrypt_text(jd_text),
        status="planning",
    )
    db.add(sess)
    db.flush()

    provider = _get_provider(payload.disable_cloud_ai)
    bank = load_bank()

    # ---- research agent (only when the user allowed internet access)
    if payload.allow_internet:
        try:
            from ..agents.research_agent import research_questions  # lazy: Agent B

            new_items, citations = research_questions(
                payload.role, payload.difficulty, True, provider, session_id=sess.id
            )
            existing = {item.id for item in bank}
            for item in new_items or []:
                if item.id not in existing:
                    bank.append(item)
                    existing.add(item.id)
            if new_items:
                # Persist researched questions across sessions (spec §12.1
                # "Update question bank"); swallows its own failures.
                from ..agents.research_agent import merge_into_internet_bank

                merge_into_internet_bank(new_items)
            for cite in citations or []:
                db.add(
                    SourceCitation(
                        session_id=sess.id,
                        url=cite.url,
                        title=cite.title,
                        quality=cite.quality,
                        fetched_at=cite.fetched_at,
                        notes=cite.notes,
                    )
                )
        except Exception:  # noqa: BLE001
            logger.warning("Research agent failed; continuing bank-only", exc_info=True)

    # ---- derive extra topics from resume / job description
    extra_topics: List[str] = []
    try:
        if resume_text:
            extra_topics += list(parse_resume(resume_text, "resume.txt")["topics"])  # type: ignore[index]
        if jd_text:
            extra_topics += list(parse_job_description(jd_text)["topics"])  # type: ignore[index]
    except Exception:  # noqa: BLE001
        logger.warning("Resume/JD parsing failed", exc_info=True)

    # ---- planning agent with deterministic fallback
    plan: Optional[InterviewPlan] = None
    try:
        from ..agents.planning_agent import build_plan  # lazy: Agent B

        candidate = build_plan(
            payload, resume_text, jd_text,
            # Honor the "use local wiki" setup toggle during planning too.
            _get_retriever() if payload.use_wiki else _NullRetriever(),
            bank, provider,
        )
        plan = InterviewPlan.model_validate(
            candidate if isinstance(candidate, dict) else candidate.model_dump()
        )
        if not plan.sections:
            raise ValueError("planning agent returned no sections")
    except Exception:  # noqa: BLE001
        logger.warning("Planning agent failed; using fallback plan", exc_info=True)
        plan = None

    generated: Dict[str, QuestionBankItem] = {}
    if plan is None:
        plan, generated = _fallback_plan(payload, bank, extra_topics)

    bank_by_id = {item.id: item for item in bank}
    bank_by_id.update(generated)
    try:
        _materialize_questions(db, sess, payload, plan, bank_by_id, provider)
    except Exception:  # noqa: BLE001
        # Even a broken plan must not 500: rebuild deterministically.
        logger.exception("Question materialization failed; rebuilding fallback")
        db.query(Question).filter(Question.session_id == sess.id).delete(
            synchronize_session=False
        )
        plan, generated = _fallback_plan(payload, bank, extra_topics)
        bank_by_id = {item.id: item for item in bank}
        bank_by_id.update(generated)
        _materialize_questions(db, sess, payload, plan, bank_by_id, provider)

    sess.plan = plan.model_dump()
    sess.status = "ready"
    db.commit()
    db.refresh(sess)
    return session_to_out(sess)


@router.get("/api/sessions/{session_id}", response_model=SessionOut)
def get_session(session_id: str, db: Session = Depends(get_db)) -> SessionOut:
    sess = db.get(InterviewSession, session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session_to_out(sess)


@router.get("/api/sessions/{session_id}/transcript", response_model=TranscriptOut)
def get_session_transcript(session_id: str, db: Session = Depends(get_db)) -> TranscriptOut:
    sess = db.get(InterviewSession, session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="session not found")
    return transcript_store.get_transcript(db, session_id)


@router.get(
    "/api/sessions/{session_id}/sources", response_model=List[SourceCitationOut]
)
def get_session_sources(
    session_id: str, db: Session = Depends(get_db)
) -> List[SourceCitationOut]:
    sess = db.get(InterviewSession, session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="session not found")
    rows = (
        db.query(SourceCitation)
        .filter(SourceCitation.session_id == session_id)
        .order_by(SourceCitation.fetched_at)
        .all()
    )
    return [
        SourceCitationOut(
            id=r.id,
            session_id=r.session_id,
            url=r.url,
            title=r.title,
            quality=r.quality,  # type: ignore[arg-type]
            fetched_at=r.fetched_at,
            notes=r.notes or "",
        )
        for r in rows
    ]
