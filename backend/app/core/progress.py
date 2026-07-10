"""Cross-session progress tracking + personalized study curriculum (spec §16).

``build_progress`` aggregates a user's *completed* interview sessions into:

- ``sessions``: chronological history with overall score / role readiness
  (taken from the stored encrypted report when present, falling back to
  ``InterviewSession.overall_score``).
- ``readiness_trend``: role-readiness (0-100) per session over time.
- ``topic_trends``: per-topic mean answer score (0-5) per session, computed
  directly from per-question :class:`~app.models.Score` rows.
- ``current_weak_topics`` / ``current_strong_topics``: topics averaged over
  the user's last two sessions — weak below :data:`WEAK_THRESHOLD` (weakest
  first), strong at/above :data:`STRONG_THRESHOLD` (strongest first).
- ``curriculum``: deterministic study recommendations built from weak topics
  and reports' ``missing_concepts``, weighted by recency and frequency. No
  LLM calls; wiki references come from the local RAG retriever when its
  index is loaded (and are simply empty otherwise).
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..models import Answer, InterviewSession, Question, Score
from ..schemas import CurriculumItem, ProgressOut, ProgressSessionOut, TrendPoint
from .report_generator import load_report

logger = logging.getLogger(__name__)

# Topic-average thresholds (0-5 scale) for current weak/strong classification.
WEAK_THRESHOLD = 3.0
STRONG_THRESHOLD = 4.0

# A topic scoring below this in a single session becomes a curriculum
# candidate (matches report_generator's weak-topic convention).
CURRICULUM_TOPIC_THRESHOLD = 3.5

# Recency weights for curriculum aggregation: most recent session weighs 3,
# the one before it 2, everything older 1.
RECENCY_WEIGHTS = (3, 2)
DEFAULT_WEIGHT = 1

MAX_CURRICULUM_ITEMS = 15


def _session_topic_means(db: Session, session_id: str) -> Dict[str, float]:
    """Mean per-answer overall (1-5) per topic for one session, 2dp."""
    rows = (
        db.query(Question.topic, Score.overall)
        .join(Answer, Answer.question_id == Question.id)
        .join(Score, Score.answer_id == Answer.id)
        .filter(Question.session_id == session_id)
        .all()
    )
    acc: Dict[str, List[float]] = {}
    for topic, overall in rows:
        acc.setdefault(str(topic), []).append(float(overall))
    return {t: round(sum(v) / len(v), 2) for t, v in acc.items()}


def _wiki_refs(concept: str, k: int = 2) -> List[str]:
    """Wiki source names for a concept via the RAG retriever; never raises."""
    try:
        from ..rag.retriever import get_retriever  # lazy: optional module

        retriever = get_retriever()
        if retriever is None or not getattr(retriever, "loaded", False):
            return []
        refs: List[str] = []
        for res in retriever.search(concept, k=k):
            name = str(getattr(res, "source", "")).strip()
            if name and name not in refs:
                refs.append(name)
        return refs
    except Exception:  # noqa: BLE001 - wiki refs are best-effort only
        logger.warning("wiki ref lookup failed for %r", concept, exc_info=True)
        return []


def classify_topics(topic_avgs: Dict[str, float]) -> Tuple[List[str], List[str]]:
    """(weak_topics, strong_topics) from topic -> average score (0-5).

    Weak: avg < WEAK_THRESHOLD, weakest first. Strong: avg >= STRONG_THRESHOLD,
    strongest first. Ties break alphabetically for determinism.
    """
    weak = sorted(
        (t for t, s in topic_avgs.items() if s < WEAK_THRESHOLD),
        key=lambda t: (topic_avgs[t], t.lower()),
    )
    strong = sorted(
        (t for t, s in topic_avgs.items() if s >= STRONG_THRESHOLD),
        key=lambda t: (-topic_avgs[t], t.lower()),
    )
    return weak, strong


class _Candidate:
    """Aggregation bucket for one curriculum concept (case-insensitive key)."""

    __slots__ = ("title", "weight", "source_sessions", "topic_scores", "missing_count")

    def __init__(self, title: str):
        self.title = title
        self.weight = 0
        self.source_sessions: List[str] = []
        self.topic_scores: List[float] = []  # per-session means where weak
        self.missing_count = 0

    def add_session(self, session_id: str) -> None:
        if session_id not in self.source_sessions:
            self.source_sessions.append(session_id)


def _reason(cand: _Candidate) -> str:
    """Deterministic reason template naming topic, scores and session counts."""

    def _plural(n: int) -> str:
        return "session" if n == 1 else "sessions"

    parts: List[str] = []
    if cand.topic_scores:
        n = len(cand.topic_scores)
        avg = sum(cand.topic_scores) / n
        parts.append(
            "Scored {0:.1f}/5 on {1} across {2} {3}".format(
                avg, cand.title, n, _plural(n)
            )
        )
    if cand.missing_count:
        if parts:
            parts.append(
                "; missing: flagged as an uncovered concept in {0} {1}".format(
                    cand.missing_count, _plural(cand.missing_count)
                )
            )
        else:
            parts.append(
                "Missing concept: not covered in your answers in {0} {1}".format(
                    cand.missing_count, _plural(cand.missing_count)
                )
            )
    return "".join(parts) + "."


def _build_curriculum(
    sessions_desc: List[InterviewSession],
    topic_means_by_session: Dict[str, Dict[str, float]],
    missing_by_session: Dict[str, List[str]],
) -> List[CurriculumItem]:
    """Recency+frequency weighted, case-insensitively deduped study items.

    ``sessions_desc`` must be most-recent-first; the most recent session's
    concepts weigh 3, the next 2, older ones 1. Priority is assigned by
    weighted-rank tertiles (1=now, 2=next, 3=later).
    """
    candidates: Dict[str, _Candidate] = {}

    def _get(title: str) -> _Candidate:
        key = title.strip().lower()
        if key not in candidates:
            candidates[key] = _Candidate(title.strip())
        return candidates[key]

    for idx, sess in enumerate(sessions_desc):
        weight = RECENCY_WEIGHTS[idx] if idx < len(RECENCY_WEIGHTS) else DEFAULT_WEIGHT
        for topic, mean in sorted(topic_means_by_session.get(sess.id, {}).items()):
            if mean < CURRICULUM_TOPIC_THRESHOLD:
                cand = _get(topic)
                cand.weight += weight
                cand.topic_scores.append(mean)
                cand.add_session(sess.id)
        for concept in missing_by_session.get(sess.id, []):
            concept = str(concept).strip()
            if not concept:
                continue
            cand = _get(concept)
            cand.weight += weight
            cand.missing_count += 1
            cand.add_session(sess.id)

    ranked = sorted(
        candidates.values(), key=lambda c: (-c.weight, c.title.lower())
    )[:MAX_CURRICULUM_ITEMS]
    if not ranked:
        return []

    n = len(ranked)
    first_cut = (n + 2) // 3  # ceil(n/3)
    second_cut = (2 * n + 2) // 3  # ceil(2n/3)
    items: List[CurriculumItem] = []
    for i, cand in enumerate(ranked):
        priority = 1 if i < first_cut else (2 if i < second_cut else 3)
        items.append(
            CurriculumItem(
                title=cand.title,
                reason=_reason(cand),
                wiki_refs=_wiki_refs(cand.title),
                priority=priority,
                source_sessions=list(cand.source_sessions),
            )
        )
    return items


def build_progress(db: Session, user_id: str) -> ProgressOut:
    """Aggregate all of a user's completed sessions into a ProgressOut.

    Deterministic; no LLM calls. An empty history yields empty lists/dicts.
    """
    completed: List[InterviewSession] = (
        db.query(InterviewSession)
        .filter(
            InterviewSession.user_id == user_id,
            InterviewSession.status == "completed",
        )
        .order_by(InterviewSession.created_at.asc(), InterviewSession.id.asc())
        .all()
    )

    sessions_out: List[ProgressSessionOut] = []
    readiness_trend: List[TrendPoint] = []
    topic_trends: Dict[str, List[TrendPoint]] = {}
    topic_means_by_session: Dict[str, Dict[str, float]] = {}
    missing_by_session: Dict[str, List[str]] = {}

    for sess in completed:
        report = load_report(db, sess.id)
        overall: Optional[float]
        readiness: Optional[int]
        if report is not None:
            overall = float(report.overall_score)
            readiness = int(report.role_readiness)
            missing_by_session[sess.id] = list(report.missing_concepts or [])
        elif sess.overall_score is not None:
            overall = float(sess.overall_score)
            readiness = int(max(0, min(100, round(sess.overall_score))))
        else:
            overall = None
            readiness = None

        sessions_out.append(
            ProgressSessionOut(
                id=sess.id,
                created_at=sess.created_at,
                role=sess.role,
                mode=sess.mode,
                difficulty=sess.difficulty,
                overall_score=overall,
                role_readiness=readiness,
            )
        )
        if readiness is not None:
            readiness_trend.append(
                TrendPoint(
                    session_id=sess.id, created_at=sess.created_at, score=readiness
                )
            )

        means = _session_topic_means(db, sess.id)
        topic_means_by_session[sess.id] = means
        for topic, mean in means.items():
            topic_trends.setdefault(topic, []).append(
                TrendPoint(session_id=sess.id, created_at=sess.created_at, score=mean)
            )

    # ---- current weak/strong topics: average over the last two sessions.
    recent = completed[-2:]
    recent_acc: Dict[str, List[float]] = {}
    for sess in recent:
        for topic, mean in topic_means_by_session.get(sess.id, {}).items():
            recent_acc.setdefault(topic, []).append(mean)
    recent_avgs = {t: round(sum(v) / len(v), 2) for t, v in recent_acc.items()}
    weak, strong = classify_topics(recent_avgs)

    curriculum = _build_curriculum(
        list(reversed(completed)), topic_means_by_session, missing_by_session
    )

    return ProgressOut(
        user_id=user_id,
        sessions=sessions_out,
        readiness_trend=readiness_trend,
        topic_trends=topic_trends,
        current_weak_topics=weak,
        current_strong_topics=strong,
        curriculum=curriculum,
    )
