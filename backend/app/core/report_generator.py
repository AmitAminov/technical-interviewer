"""Final report generation (DESIGN.md §9, spec §8) — recoverable.

Every numeric field of :class:`~app.schemas.ReportOut` is computed
deterministically from the DB. Narrative fields (communication_feedback,
technical_feedback, transcript_summary, suggested_study_plan) use the LLM
provider when available, always with an offline-composed fallback, so report
generation succeeds with no network and no API key in well under 30s.

The finished report is stored Fernet-encrypted in the ``reports`` table. Any
unexpected failure sets ``Report.generation_failed=True``; the
``POST /api/sessions/{id}/report/regenerate`` endpoint re-runs generation.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..models import Answer, InterviewSession, Question, Report, Score
from ..schemas import (
    DIFFICULTIES,
    TRACK_TOPICS,
    AnswerHighlight,
    NextInterviewRec,
    ReportOut,
    TimePerQuestion,
)
from ..security.crypto import decrypt_text, encrypt_text
from . import transcript as transcript_store

logger = logging.getLogger(__name__)

# Difficulty modifier for role_readiness (DESIGN.md §9): readiness toward a
# target level is judged more strictly as the target rises — Junior x1.0
# scaling linearly down to Staff/Lead-level x0.9.
DIFFICULTY_READINESS_MODIFIER: Dict[str, float] = {
    "Junior": 1.0,
    "Mid-level": 0.975,
    "Senior": 0.95,
    "Research-level": 0.925,
    "Staff/Lead-level": 0.9,
}

_WORD_RE = re.compile(r"[a-z0-9']+")
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "is", "are", "be", "as", "at", "by", "it", "its", "this", "that",
    "you", "your", "how", "what", "when", "why", "vs",
}


def _keywords(text: str) -> set:
    return {w for w in _WORD_RE.findall((text or "").lower()) if w not in _STOPWORDS}


def _point_covered(point: str, answer_words: set) -> bool:
    """A point counts as covered when most of its keywords appear in the answer."""
    kws = _keywords(point)
    if not kws:
        return True
    hit = sum(1 for k in kws if k in answer_words)
    return hit >= max(1, (len(kws) + 1) // 2)


def _get_provider(disable_cloud_ai: bool) -> Optional[Any]:
    try:
        from ..llm.provider import get_provider  # lazy: Agent B module

        return get_provider(disable_cloud_ai=disable_cloud_ai)
    except Exception:  # noqa: BLE001
        return None


def _get_retriever() -> Optional[Any]:
    try:
        from ..rag.retriever import get_retriever  # lazy: Agent B module

        return get_retriever()
    except Exception:  # noqa: BLE001
        return None


def _split_narratives(
    combined: Optional[str], offline_comm: str, offline_tech: str, offline_summary: str
) -> "tuple[str, str, str]":
    """Parse the [COMMUNICATION]/[TECHNICAL]/[SUMMARY] sections out of one
    combined provider response; any missing section falls back offline."""
    parts = {"COMMUNICATION": "", "TECHNICAL": "", "SUMMARY": ""}
    if combined:
        current: Optional[str] = None
        for line in combined.splitlines():
            stripped = line.strip()
            marker = stripped.strip("[]").upper() if stripped.startswith("[") else None
            if marker in parts:
                current = marker
                continue
            if current is not None:
                parts[current] += line + "\n"
    return (
        parts["COMMUNICATION"].strip() or offline_comm,
        parts["TECHNICAL"].strip() or offline_tech,
        parts["SUMMARY"].strip() or offline_summary,
    )


def _complete_text(provider: Optional[Any], system: str, prompt: str) -> Optional[str]:
    # The offline chain link returns canned templates; our score-derived
    # composed narratives are more informative, so skip the call entirely.
    if provider is None or getattr(provider, "name", "offline") == "offline":
        return None
    try:
        text = provider.complete_text(system=system, prompt=prompt, max_tokens=600)
        text = (text or "").strip()
        return text or None
    except Exception:  # noqa: BLE001
        logger.warning("provider.complete_text failed for report narrative", exc_info=True)
        return None


def _difficulty_shift(difficulty: str, steps: int) -> str:
    if difficulty not in DIFFICULTIES:
        return difficulty
    idx = min(len(DIFFICULTIES) - 1, max(0, DIFFICULTIES.index(difficulty) + steps))
    return DIFFICULTIES[idx]


class _AnswerRecord:
    """Joined view of one answered question, decrypted."""

    def __init__(self, question: Question, answer: Answer, score: Optional[Score]):
        self.question = question
        self.answer = answer
        self.score = score
        self.text = decrypt_text(answer.transcript_enc) or ""


def _collect(db: Session, session_id: str) -> Tuple[List[Question], List[_AnswerRecord]]:
    questions = (
        db.query(Question)
        .filter(Question.session_id == session_id)
        .order_by(Question.order_idx)
        .all()
    )
    records: List[_AnswerRecord] = []
    for q in questions:
        for ans in sorted(q.answers, key=lambda a: a.created_at):
            records.append(_AnswerRecord(q, ans, ans.score))
    return questions, records


def build_report(db: Session, session_id: str) -> ReportOut:
    """Compute a full ReportOut from the DB (pure aggregation + narratives)."""
    sess = db.get(InterviewSession, session_id)
    if sess is None:
        raise ValueError("session not found: {0}".format(session_id))

    questions, records = _collect(db, session_id)
    scored = [r for r in records if r.score is not None]

    # ---- overall (0-100) = mean per-answer overall (1-5) x 20
    overalls = [float(r.score.overall) for r in scored]
    mean_overall = sum(overalls) / len(overalls) if overalls else 0.0
    overall_score = int(max(0, min(100, round(mean_overall * 20))))

    # ---- role readiness with documented difficulty modifier
    modifier = DIFFICULTY_READINESS_MODIFIER.get(sess.difficulty, 1.0)
    role_readiness = int(max(0, min(100, round(overall_score * modifier))))

    # ---- per-topic mean overall (1-5 scale, 2dp)
    topic_acc: Dict[str, List[float]] = {}
    for r in scored:
        topic_acc.setdefault(r.question.topic, []).append(float(r.score.overall))
    topic_scores = {
        topic: round(sum(vals) / len(vals), 2) for topic, vals in topic_acc.items()
    }

    # ---- best / weakest answers (technical answers preferred for highlights)
    ranked = sorted(scored, key=lambda r: (-float(r.score.overall), r.question.order_idx))
    technical_ranked = [r for r in ranked if not r.question.is_behavioral] or ranked

    def _highlight(rec: _AnswerRecord, best: bool) -> AnswerHighlight:
        why = (rec.score.feedback or "").strip()
        if not why:
            why = (
                "Strong coverage of the expected points with a clear structure."
                if best
                else "Key expected points were missing or under-explained."
            )
        return AnswerHighlight(
            question=rec.question.question_text,
            score=float(rec.score.overall),
            why=why,
        )

    # Split the ranking so no answer appears as both a best and a weakest
    # highlight (with one scored answer, weakest is simply empty).
    n = len(technical_ranked)
    best_count = min(3, (n + 1) // 2)
    weakest_count = min(3, n - best_count)
    best_answers = [_highlight(r, True) for r in technical_ranked[:best_count]]
    weakest_answers = [
        _highlight(r, False)
        for r in list(reversed(technical_ranked))[:weakest_count]
    ]

    # ---- missing concepts: uncovered expected_points + RAG wiki suggestions
    missing_concepts: List[str] = []
    for r in scored:
        answer_words = _keywords(r.text)
        for point in r.question.expected_points or []:
            if not _point_covered(str(point), answer_words):
                p = str(point).strip()
                if p and p not in missing_concepts:
                    missing_concepts.append(p)
    weak_topics = [t for t, s in sorted(topic_scores.items(), key=lambda kv: kv[1]) if s < 3.5]
    retriever = _get_retriever()
    if retriever is not None and getattr(retriever, "loaded", False):
        for topic in weak_topics[:3]:
            try:
                for res in retriever.search(topic, k=2):
                    name = str(getattr(res, "source", "")).rsplit("/", 1)[-1]
                    name = name[:-3] if name.endswith(".md") else name
                    name = name.replace("-", " ").replace("_", " ").strip()
                    if name and name not in missing_concepts:
                        missing_concepts.append(name)
            except Exception:  # noqa: BLE001
                logger.warning("RAG lookup for missing concepts failed", exc_info=True)
    missing_concepts = missing_concepts[:25]

    # ---- deterministic metric aggregates used by narratives
    def _metric_mean(name: str) -> float:
        vals = [float(getattr(r.score, name)) for r in scored]
        return round(sum(vals) / len(vals), 2) if vals else 0.0

    comm_mean = _metric_mean("communication")
    clarity_mean = _metric_mean("clarity")
    structure_mean = _metric_mean("structure")
    correctness_mean = _metric_mean("correctness")
    depth_mean = _metric_mean("depth")
    strong_topics = [t for t, s in sorted(topic_scores.items(), key=lambda kv: -kv[1]) if s >= 4.0]

    hints_total = sum(int(r.answer.hints_used or 0) for r in records)

    # ---- offline narrative fallbacks (always available)
    def _band(v: float) -> str:
        if v >= 4.0:
            return "strong"
        if v >= 3.0:
            return "solid"
        if v >= 2.0:
            return "developing"
        return "weak"

    offline_comm = (
        "Communication was {0} (avg {1}/5), with clarity {2}/5 and structure "
        "{3}/5 across {4} scored answer(s). ".format(
            _band((comm_mean + clarity_mean) / 2 if scored else 0.0),
            comm_mean, clarity_mean, structure_mean, len(scored),
        )
        + (
            "Answers were generally well organized; keep leading with a short "
            "summary before diving into detail."
            if structure_mean >= 3.5
            else "Practice structuring answers: state the headline conclusion "
            "first, then walk through reasoning step by step, and close with "
            "trade-offs or an example."
        )
    )
    offline_tech = (
        "Technical performance averaged {0}/5 for correctness and {1}/5 for "
        "depth. ".format(correctness_mean, depth_mean)
        + (
            "Strongest topics: {0}. ".format(", ".join(strong_topics[:3]))
            if strong_topics
            else ""
        )
        + (
            "Focus areas: {0}. ".format(", ".join(weak_topics[:3]))
            if weak_topics
            else ""
        )
        + (
            "Several expected points went unmentioned — review the missing "
            "concepts list and rehearse explaining them out loud."
            if missing_concepts
            else "Expected points were covered well overall."
        )
    )
    offline_summary = (
        "A {0} {1} interview for the {2} role at {3} difficulty. {4} question(s) "
        "were asked and {5} answer(s) scored, with an overall score of {6}/100. "
        "{7} hint(s) were used.".format(
            sess.mode,
            "{0}-minute".format(sess.duration_minutes),
            sess.role,
            sess.difficulty,
            len(questions),
            len(scored),
            overall_score,
            hints_total,
        )
    )

    # Hebrew report: concise Hebrew offline narratives (the LLM path also gets a
    # Hebrew directive below) so a Hebrew interview yields a Hebrew report.
    want_he = (sess.language or "en").lower().startswith("he")
    if want_he:
        offline_comm = (
            "התקשורת קיבלה ציון ממוצע {0}/5 (בהירות {1}/5, מבנה {2}/5) על פני {3} "
            "תשובות שנוקדו. מומלץ לפתוח כל תשובה במסקנה קצרה ואז לפרט את ההנמקה "
            "ולסגור עם שיקולי יתרונות/חסרונות.".format(
                round((comm_mean + clarity_mean) / 2, 1) if scored else 0.0,
                clarity_mean, structure_mean, len(scored),
            )
        )
        offline_tech = (
            "הביצועים הטכניים: נכונות {0}/5, עומק {1}/5. ".format(
                correctness_mean, depth_mean
            )
            + ("נושאים חזקים: {0}. ".format(", ".join(strong_topics[:3])) if strong_topics else "")
            + ("נושאים לחיזוק: {0}. ".format(", ".join(weak_topics[:3])) if weak_topics else "")
            + ("כדאי לחזור על המושגים החסרים ולתרגל הסבר שלהם בקול." if missing_concepts
               else "רוב הנקודות המצופות כוסו היטב.")
        )
        offline_summary = (
            "ראיון {0} לתפקיד {1} ברמת {2}. נשאלו {3} שאלות ונוקדו {4} תשובות, "
            "עם ציון כולל {5}/100. נעשה שימוש ב-{6} רמזים.".format(
                sess.mode, sess.role, sess.difficulty, len(questions),
                len(scored), overall_score, hints_total,
            )
        )

    # ---- study plan (>= 3 items, deterministic fallback)
    study_plan: List[str] = []
    if want_he:
        for topic in weak_topics[:4]:
            study_plan.append(
                "חזור על {0}: כתוב סיכום של עמוד אחד וענה בקול על שתי שאלות "
                "תרגול.".format(topic)
            )
        for concept in missing_concepts[:3]:
            item = "למד את המושג \"{0}\" והיה מוכן להסביר אותו בשתי דקות.".format(concept)
            if item not in study_plan:
                study_plan.append(item)
        for g in (
            "בצע ראיון דמה מתוזמן, כשכל תשובה נמשכת פחות מ-4 דקות ובמבנה של "
            "מסקנה-תחילה.",
            "עבור התשובה החלשה ביותר שלך מהמפגש, כתוב את התשובה האידיאלית "
            "ותרגל אותה פעמיים.",
            "בחר נושא חזק אחד והכן סיפור מקרה עמוק יותר עם מספרים קונקרטיים "
            "ושיקולי יתרונות/חסרונות.",
        ):
            if len(study_plan) >= 3:
                break
            study_plan.append(g)
    else:
        for topic in weak_topics[:4]:
            study_plan.append(
                "Review {0}: write a one-page summary and answer two practice "
                "questions out loud.".format(topic)
            )
        for concept in missing_concepts[:3]:
            item = "Study the concept \"{0}\" and be ready to explain it in 2 minutes.".format(concept)
            if item not in study_plan:
                study_plan.append(item)
        generic = [
            "Do a timed mock interview answering each question in under 4 minutes "
            "with a conclusion-first structure.",
            "For your weakest answer from this session, write out the ideal answer "
            "and rehearse it twice.",
            "Pick one strong topic and prepare a deeper war story with concrete "
            "metrics and trade-offs.",
        ]
        for g in generic:
            if len(study_plan) >= 3:
                break
            study_plan.append(g)

    # ---- narratives via provider (offline compose is the guaranteed fallback)
    provider = _get_provider(bool(sess.disable_cloud_ai))
    system = "You are an expert technical interview coach writing a candidate report."
    facts = (
        "Role: {0}. Difficulty: {1}. Overall: {2}/100. Topic scores: {3}. "
        "Missing concepts: {4}. Hints used: {5}.".format(
            sess.role, sess.difficulty, overall_score,
            json.dumps(topic_scores), ", ".join(missing_concepts[:8]) or "none",
            hints_total,
        )
    )
    # Single combined call: three sequential provider calls could exceed the
    # 30s report budget on the Claude CLI runtime (~10-20s per call).
    combined = _complete_text(
        provider, system,
        facts + " Communication avg {0}/5, clarity {1}/5, structure {2}/5, "
        "correctness avg {3}/5, depth {4}/5.\n"
        "Write exactly three sections, each introduced by its marker on its "
        "own line:\n[COMMUNICATION]\n2-4 sentences of concrete communication "
        "feedback.\n[TECHNICAL]\n2-4 sentences of concrete technical "
        "feedback.\n[SUMMARY]\n3-5 sentences summarizing the interview for "
        "the candidate.".format(
            comm_mean, clarity_mean, structure_mean, correctness_mean, depth_mean
        )
        + (" Write the content of all three sections in fluent modern Hebrew "
           "(עברית); keep the [COMMUNICATION]/[TECHNICAL]/[SUMMARY] markers in "
           "English." if want_he else ""),
    )
    communication_feedback, technical_feedback, transcript_summary = (
        _split_narratives(combined, offline_comm, offline_tech, offline_summary)
    )

    # ---- recommended next interview (heuristic per DESIGN.md §9)
    if overall_score >= 85:
        next_difficulty = _difficulty_shift(sess.difficulty, +1)
    elif overall_score < 50:
        next_difficulty = _difficulty_shift(sess.difficulty, -1)
    else:
        next_difficulty = sess.difficulty
    focus = weak_topics[:3] or list(topic_scores.keys())[:2] or TRACK_TOPICS.get(
        sess.role, []
    )[:2]
    recommended = NextInterviewRec(
        role=sess.role,
        mode=sess.mode,
        difficulty=next_difficulty,
        focus_topics=focus,
    )

    # ---- per-question timing (sum of answer durations)
    time_per_question: List[TimePerQuestion] = []
    for q in questions:
        secs = sum(float(a.duration_seconds or 0.0) for a in q.answers)
        time_per_question.append(
            TimePerQuestion(
                question_id=q.id, question_text=q.question_text, seconds=round(secs, 2)
            )
        )

    return ReportOut(
        session_id=session_id,
        overall_score=overall_score,
        role_readiness=role_readiness,
        topic_scores=topic_scores,
        best_answers=best_answers,
        weakest_answers=weakest_answers,
        missing_concepts=missing_concepts,
        communication_feedback=communication_feedback,
        technical_feedback=technical_feedback,
        suggested_study_plan=study_plan,
        recommended_next_interview=recommended,
        questions_asked=[q.question_text for q in questions],
        transcript_summary=transcript_summary,
        hints_used_total=hints_total,
        time_per_question=time_per_question,
        created_at=datetime.utcnow(),
    )


def _store(db: Session, session_id: str, report: Optional[ReportOut], failed: bool) -> Report:
    row = db.query(Report).filter(Report.session_id == session_id).one_or_none()
    if row is None:
        row = Report(session_id=session_id)
        db.add(row)
    row.generation_failed = failed
    row.created_at = datetime.utcnow()
    row.content_enc = (
        encrypt_text(report.model_dump_json()) if report is not None else None
    )
    db.commit()
    return row


def generate_report(db: Session, session_id: str) -> ReportOut:
    """Generate + persist (encrypted) the report; recoverable on failure.

    On any unexpected error a Report row with ``generation_failed=True`` is
    stored and the exception re-raised, so the regenerate endpoint can recover.
    """
    try:
        report = build_report(db, session_id)
    except Exception:
        logger.exception("Report generation failed for session %s", session_id)
        try:
            _store(db, session_id, None, failed=True)
        except Exception:  # noqa: BLE001 - never mask the original error
            logger.exception("Could not persist generation_failed marker")
        raise
    _store(db, session_id, report, failed=False)
    sess = db.get(InterviewSession, session_id)
    if sess is not None:
        sess.overall_score = float(report.overall_score)
        db.commit()
    # Autosave a system transcript line so the transcript reflects completion.
    try:
        transcript_store.add_entry(db, session_id, "system", "Report generated.")
    except Exception:  # noqa: BLE001
        pass
    return report


def generate_and_store(session_id: str) -> ReportOut:
    """Thread-friendly entry point: opens its own DB session."""
    from ..database import SessionLocal

    db = SessionLocal()
    try:
        return generate_report(db, session_id)
    finally:
        db.close()


def load_report(db: Session, session_id: str) -> Optional[ReportOut]:
    """Return the stored report if present and valid, else None."""
    row = db.query(Report).filter(Report.session_id == session_id).one_or_none()
    if row is None or row.generation_failed or not row.content_enc:
        return None
    try:
        from .textfix import fix_mojibake

        payload = fix_mojibake(decrypt_text(row.content_enc) or "")
        return ReportOut.model_validate(json.loads(payload))
    except Exception:  # noqa: BLE001
        logger.warning("Stored report for %s is unreadable", session_id, exc_info=True)
        return None


def report_status(db: Session, session_id: str) -> str:
    """'ready' | 'failed' | 'absent' — used by the report endpoints."""
    row = db.query(Report).filter(Report.session_id == session_id).one_or_none()
    if row is None:
        return "absent"
    if row.generation_failed or not row.content_enc:
        return "failed"
    return "ready"
