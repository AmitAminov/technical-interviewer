"""Interview state machine (DESIGN.md §4 flow, spec §6.3).

One :class:`InterviewOrchestrator` instance is created per WebSocket
connection by ``app.ws.interview_ws``. Every handler method takes an ORM
session and returns a list of server->client message dicts (exact shapes from
DESIGN.md §4); the WS layer only serializes and sends.

Durable state (current question pointer, section index, elapsed seconds,
status) is persisted to the ``interview_sessions`` row on every step so a
reconnecting client resumes cleanly. Elapsed time is accumulated with
``time.monotonic`` deltas while status is "active" (pause stops the clock).

All Agent-B modules (llm/rag) are imported lazily inside functions with
deterministic offline fallbacks, so the interview runs end-to-end with no
network, no API key, and even with those packages absent.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..models import Answer, InterviewSession, Question, Score, TranscriptEntry
from ..schemas import MetricScores
from ..security.crypto import decrypt_text, encrypt_text
from . import hints as hints_mod
from . import transcript as transcript_store
from .scoring import compute_overall

logger = logging.getLogger(__name__)

CANDIDATE_QUESTIONS_SECTION = "candidate questions"


# --------------------------------------------------------------------------
# Offline fallbacks for Agent-B interviewer functions (used only when the
# app.llm package is unavailable or raises).
# --------------------------------------------------------------------------
def _is_he(language: str) -> bool:
    return (language or "en").lower().startswith("he")


def _fallback_greeting(style: str, role: str, name: str, language: str = "en") -> str:
    if _is_he(language):
        return (
            "שלום {n}, נעים להכיר! אני אראיין אותך היום לתפקיד {r}. קח את "
            "הזמן וחשוב בקול — בוא נתחיל.".format(n=name or "there", r=role)
        )
    openers = {
        "Friendly": "Hi {n}, great to meet you!",
        "Strict": "Good day, {n}.",
        "Research professor": "Welcome, {n}.",
        "Startup CTO": "Hey {n}, thanks for jumping on!",
        "Big-tech interviewer": "Hello {n}, thanks for joining.",
    }
    opener = openers.get(style, "Hello {n},").format(n=name or "there")
    return (
        "{0} I'll be your interviewer today for the {1} position. Take your "
        "time and think out loud — let's get started.".format(opener, role)
    )


def _fallback_background_question(role: str, language: str = "en") -> str:
    if _is_he(language):
        return (
            "בתור התחלה, ספר לי בקצרה על הרקע שלך: הניסיון הרלוונטי ביותר "
            "לתפקיד {0}, ואילו בעיות אתה נהנה לפתור.".format(role)
        )
    return (
        "To start, tell me briefly about your background: your experience "
        "most relevant to the {0} role, and what kind of problems you enjoy "
        "working on.".format(role)
    )


def _fallback_checkin(style: str, language: str = "en") -> str:
    if _is_he(language):
        return (
            "אין לחץ — שמתי לב שהיה שקט. תרצה עוד רגע לחשוב, או שרמז יעזור?"
        )
    return (
        "No rush — I noticed it's been quiet. Would you like a bit more time, "
        "or would a hint help?"
    )


def _fallback_closing(style: str, language: str = "en") -> str:
    if _is_he(language):
        return (
            "בזה מסתיים הראיון — תודה, התמדת יפה. אני מכין עכשיו את דוח המשוב "
            "המפורט שלך; הוא יהיה מוכן עוד רגע."
        )
    return (
        "That wraps up our interview — thank you, you did well to stick with "
        "it. I'm compiling your detailed feedback report now; it will be "
        "ready in just a moment."
    )


def _fallback_evaluate(question: Question, text: str) -> "tuple[MetricScores, str]":
    """Emergency heuristic scorer used only if app.llm.scorer is unavailable."""
    words = (text or "").split()
    if len(words) < 8:
        return (
            MetricScores(
                correctness=1, depth=1, clarity=1, structure=1, practicality=1,
                mathematical_rigor=1, tradeoff_awareness=1, communication=1,
            ),
            "The answer was empty or too short to evaluate.",
        )
    lowered = (text or "").lower()
    points = [str(p) for p in (question.expected_points or [])]
    covered = 0
    for p in points:
        kws = [w for w in p.lower().split() if len(w) > 3]
        if kws and any(k in lowered for k in kws):
            covered += 1
    ratio = covered / len(points) if points else 0.5
    base = 2 + int(round(ratio * 2))  # 2..4
    tradeoff = 3 if any(t in lowered for t in ("trade-off", "tradeoff", "however", "depends")) else 2
    rigor = 3 if any(ch.isdigit() for ch in lowered) else 2
    return (
        MetricScores(
            correctness=base, depth=base, clarity=3, structure=3,
            practicality=base, mathematical_rigor=rigor,
            tradeoff_awareness=tradeoff, communication=3,
        ),
        "Heuristic evaluation: covered {0} of {1} expected points.".format(
            covered, len(points)
        ),
    )


class InterviewOrchestrator:
    """Per-connection state machine; handlers return server message lists."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._last_monotonic: Optional[float] = None
        # hints given for the question currently awaiting an answer
        self._hints_pending: Dict[str, int] = {}
        self._followed_up: set = set()
        self._awaiting_followup: Optional[str] = None
        self._partial_entry_id: Optional[str] = None
        # set once per connection: rebuilds hint/followup state from the DB
        # so a reconnect keeps the hint penalty and max-1-followup invariants
        self._state_restored = False
        # question_text -> bank item, built lazily for follow-up lookups
        self._bank_by_text: Optional[Dict[str, Any]] = None
        self._provider: Any = None
        self._provider_loaded = False
        #: WS layer checks this after each handle(); when True it schedules
        #: background report generation and later sends {"type":"report_ready"}.
        self.report_pending = False

    # ---------------------------------------------------------------- infra
    def _get_provider(self, sess: InterviewSession) -> Optional[Any]:
        if self._provider_loaded:
            return self._provider
        self._provider_loaded = True
        try:
            from ..llm.provider import get_provider  # lazy: Agent B

            # fast_only: the live conversational loop must meet the <2.5s
            # response target, so the slow Claude CLI runtime is excluded here
            # (it still powers planning and report generation).
            self._provider = get_provider(
                disable_cloud_ai=bool(sess.disable_cloud_ai), fast_only=True
            )
        except Exception:  # noqa: BLE001
            logger.warning("LLM provider unavailable; using offline fallbacks")
            self._provider = None
        return self._provider

    def _tick(self, sess: InterviewSession) -> None:
        """Accumulate monotonic elapsed time while the session is active."""
        now = time.monotonic()
        if sess.status == "active" and self._last_monotonic is not None:
            sess.elapsed_seconds = float(sess.elapsed_seconds or 0.0) + max(
                0.0, now - self._last_monotonic
            )
        self._last_monotonic = now

    @staticmethod
    def _remaining(sess: InterviewSession) -> float:
        total = float(sess.duration_minutes) * 60.0
        return max(0.0, total - float(sess.elapsed_seconds or 0.0))

    @staticmethod
    def _sections(sess: InterviewSession) -> List[str]:
        plan = sess.plan or {}
        sections = list(plan.get("sections") or [])
        if not sections:
            sections = ["background", CANDIDATE_QUESTIONS_SECTION]
        return sections

    @staticmethod
    def _questions(db: Session, sess: InterviewSession) -> List[Question]:
        return (
            db.query(Question)
            .filter(Question.session_id == sess.id)
            .order_by(Question.order_idx)
            .all()
        )

    def _current_question(self, db: Session, sess: InterviewSession) -> Optional[Question]:
        qs = self._questions(db, sess)
        idx = int(sess.current_question_idx or 0)
        if 0 <= idx < len(qs):
            return qs[idx]
        return None

    # ------------------------------------------------------------- messages
    def _state_msg(self, sess: InterviewSession) -> Dict[str, Any]:
        status = sess.status if sess.status in ("active", "paused", "completed") else "active"
        return {
            "type": "state",
            "status": status,
            "elapsed_seconds": round(float(sess.elapsed_seconds or 0.0), 2),
            "remaining_seconds": round(self._remaining(sess), 2),
        }

    def _interviewer_msg(
        self,
        db: Session,
        sess: InterviewSession,
        kind: str,
        text: str,
        section: str,
        question_id: Optional[str],
        question_index: int,
        total_questions: int,
        persist: bool = True,
    ) -> Dict[str, Any]:
        if persist and text:
            transcript_store.add_entry(db, sess.id, "interviewer", text)
        return {
            "type": "interviewer",
            "kind": kind,
            "text": text,
            "section": section,
            "question_id": question_id,
            "question_index": question_index,
            "total_questions": total_questions,
        }

    @staticmethod
    def _error(message: str) -> Dict[str, Any]:
        return {"type": "error", "message": message}

    # ------------------------------------------------------------- dispatch
    def handle(self, db: Session, message: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Process one client message; returns server messages to send."""
        mtype = str(message.get("type") or "")
        sess = db.get(InterviewSession, self.session_id)
        if sess is None:
            return [self._error("session not found")]
        self._tick(sess)
        if not self._state_restored:
            self._state_restored = True
            if sess.status in ("active", "paused"):
                self._restore_connection_state(db, sess)
        handlers = {
            "start": self._on_start,
            "answer": self._on_answer,
            "partial_transcript": self._on_partial,
            "hint_request": self._on_hint_request,
            "silence": self._on_silence,
            "interrupt": self._on_interrupt,
            "barge_in": self._on_barge_in,
            "pause": self._on_pause,
            "resume": self._on_resume,
            "skip": self._on_skip,
            "end": self._on_end,
            "more_time_response": self._on_more_time_response,
        }
        handler = handlers.get(mtype)
        if handler is None:
            db.commit()
            return [self._error("unknown message type: {0}".format(mtype))]
        try:
            msgs = handler(db, sess, message)
        finally:
            db.commit()
        return msgs

    def _restore_connection_state(self, db: Session, sess: InterviewSession) -> None:
        """Rebuild per-connection state from the DB after a WS reconnect.

        The hint count and followup bookkeeping live on the connection, but
        DESIGN.md §11 requires the server to resume from session state: the
        hint penalty (§8) and the max-1-followup rule (§4) must survive a
        mid-question drop.
        """
        import re

        question = self._current_question(db, sess)

        # Questions that already have an Answer row were answered before the
        # drop; the only way the index did not advance past them is that a
        # followup was issued and is still awaiting its answer.
        if question is not None:
            answered = (
                db.query(Answer).filter(Answer.question_id == question.id).count()
            )
            if answered > 0:
                self._followed_up.add(question.id)
                self._awaiting_followup = question.id

        # Hints already given for the open question: replay the transcript's
        # "(hint, level N)" entries newer than both the question's asked_at
        # and its last answer (post-answer level-5 explanations and previous
        # questions' hints are older by construction).
        if question is not None and self._awaiting_followup is None:
            cutoff = question.asked_at
            rows = (
                db.query(TranscriptEntry)
                .filter(TranscriptEntry.session_id == sess.id)
                .filter(TranscriptEntry.speaker == "interviewer")
                .order_by(TranscriptEntry.ts, TranscriptEntry.id)
                .all()
            )
            level = 0
            for row in rows:
                if cutoff is not None and row.ts < cutoff:
                    continue
                match = re.match(r"^\(hint, level (\d)\)", decrypt_text(row.text_enc))
                if match:
                    level = max(level, int(match.group(1)))
            if level > 0:
                self._hints_pending[question.id] = min(
                    level, hints_mod.MAX_PRE_ANSWER_HINT_LEVEL
                )

    def on_disconnect(self, db: Session) -> None:
        """Persist elapsed time when the socket drops."""
        sess = db.get(InterviewSession, self.session_id)
        if sess is None:
            return
        self._tick(sess)
        db.commit()

    # ------------------------------------------------------------- handlers
    def _on_start(self, db: Session, sess: InterviewSession, _m: Dict) -> List[Dict]:
        if sess.status == "completed":
            msgs = [self._state_msg(sess)]
            from .report_generator import report_status

            if report_status(db, sess.id) == "ready":
                msgs.append({"type": "report_ready", "session_id": sess.id})
            return msgs
        if sess.status in ("created", "planning", "ready"):
            # Fresh start: greeting + first (background) question.
            sess.status = "active"
            self._last_monotonic = time.monotonic()
            provider = self._get_provider(sess)
            user_name = sess.user.name if sess.user is not None else "there"
            try:
                from ..llm.interviewer import greeting  # lazy: Agent B

                text = greeting(sess.interviewer_style, sess.role, user_name,
                                provider, sess.language)
            except Exception:  # noqa: BLE001
                text = _fallback_greeting(sess.interviewer_style, sess.role,
                                          user_name, sess.language)
            total = len(self._questions(db, sess))
            msgs = [
                self._interviewer_msg(
                    db, sess, "greeting", text,
                    section=self._sections(sess)[0], question_id=None,
                    question_index=int(sess.current_question_idx or 0),
                    total_questions=total,
                )
            ]
            msgs += self._ask_current(db, sess)
            msgs.append(self._state_msg(sess))
            return msgs
        # Reconnect while active/paused: resume from persisted state.
        sess.status = "active"
        self._last_monotonic = time.monotonic()
        msgs = [self._state_msg(sess)]
        msgs += self._ask_current(db, sess, reask=True)
        return msgs

    def _on_partial(self, db: Session, sess: InterviewSession, m: Dict) -> List[Dict]:
        """Persist the latest partial transcript as a safety net (upsert)."""
        text = str(m.get("text") or "")
        if not text.strip():
            return []
        if self._partial_entry_id is not None:
            updated = transcript_store.update_entry(db, self._partial_entry_id, text)
            if updated is not None:
                return []
        entry = transcript_store.add_entry(db, sess.id, "candidate", text)
        self._partial_entry_id = entry.id
        return []

    def _persist_candidate_text(self, db: Session, sess: InterviewSession, text: str) -> None:
        """Finalize the partial entry with the full answer, or append fresh."""
        if self._partial_entry_id is not None:
            updated = transcript_store.update_entry(db, self._partial_entry_id, text)
            self._partial_entry_id = None
            if updated is not None:
                return
        transcript_store.add_entry(db, sess.id, "candidate", text)

    def _on_answer(self, db: Session, sess: InterviewSession, m: Dict) -> List[Dict]:
        if sess.status == "completed":
            return [self._state_msg(sess)]
        if sess.status == "paused":
            sess.status = "active"
        text = str(m.get("text") or "").strip()
        try:
            duration = float(m.get("duration_seconds") or 0.0)
        except (TypeError, ValueError):
            duration = 0.0
        self._persist_candidate_text(db, sess, text or "(no answer)")

        question = self._current_question(db, sess)
        if question is None:
            # Candidate-questions phase (or plan exhausted): answer their
            # question with an ack, then close out the interview.
            msgs = [self._candidate_questions_ack(db, sess, text)]
            msgs += self._finish(db, sess)
            return msgs

        hints_used = self._hints_pending.pop(question.id, 0)
        # All 4 pre-answer hints consumed: the level-5 full explanation is
        # served right after scoring (spec §7.4) and counts as a hint, so the
        # penalty below already reflects hints_used=5.
        give_full_explanation = hints_used >= hints_mod.MAX_PRE_ANSWER_HINT_LEVEL
        if give_full_explanation:
            hints_used = hints_mod.MAX_HINT_LEVEL
        answer = Answer(
            question_id=question.id,
            transcript_enc=encrypt_text(text),
            duration_seconds=duration,
            hints_used=hints_used,
        )
        db.add(answer)
        db.flush()

        msgs: List[Dict] = []
        metrics, feedback, overall = self._score_answer(db, sess, question, answer, text)
        msgs.append(
            {
                "type": "score",
                "question_id": question.id,
                "scores": metrics.model_dump(),
                "overall": overall,
                "feedback": feedback,
            }
        )

        if give_full_explanation:
            explanation = hints_mod.full_explanation(
                question, self._get_provider(sess), sess.language
            )
            transcript_store.add_entry(
                db, sess.id, "interviewer",
                "(hint, level {0}) {1}".format(hints_mod.MAX_HINT_LEVEL, explanation),
            )
            msgs.append(
                {
                    "type": "hint",
                    "level": hints_mod.MAX_HINT_LEVEL,
                    "text": explanation,
                    "question_id": question.id,
                    "hints_used": hints_used,
                }
            )

        was_followup = self._awaiting_followup == question.id
        if was_followup:
            self._awaiting_followup = None
        else:
            fu_text = self._maybe_followup(sess, question, text, metrics)
            if fu_text:
                self._followed_up.add(question.id)
                self._awaiting_followup = question.id
                total = len(self._questions(db, sess))
                msgs.append(
                    self._interviewer_msg(
                        db, sess, "followup", fu_text,
                        section=question.section, question_id=question.id,
                        question_index=int(sess.current_question_idx or 0),
                        total_questions=total,
                    )
                )
                msgs.append(self._state_msg(sess))
                return msgs

        # Adaptive hint offer after a weak scored answer (DESIGN.md §8).
        if sess.hint_policy == "adaptive" and metrics.correctness <= 2:
            total = len(self._questions(db, sess))
            msgs.append(
                self._interviewer_msg(
                    db, sess, "ack",
                    ("זו הייתה שאלה מהקשות יותר — זכור שאתה יכול לבקש רמז בכל "
                     "רגע ואני אכוון אותך לכיוון הנכון.")
                    if _is_he(sess.language) else
                    "That one was on the tougher side — remember you can ask "
                    "for a hint any time and I'll nudge you in the right "
                    "direction.",
                    section=question.section, question_id=question.id,
                    question_index=int(sess.current_question_idx or 0),
                    total_questions=total,
                )
            )

        # Advance to the next question / section / closing.
        sess.current_question_idx = int(sess.current_question_idx or 0) + 1
        if self._remaining(sess) <= 0.0:
            # Time is up: jump straight to the candidate-questions wrap-up.
            sess.current_question_idx = len(self._questions(db, sess))
        msgs += self._ask_current(db, sess)
        msgs.append(self._state_msg(sess))
        return msgs

    def _on_hint_request(self, db: Session, sess: InterviewSession, _m: Dict) -> List[Dict]:
        if sess.hint_policy == "none":
            return [self._error("Hints are disabled for this session.")]
        question = self._current_question(db, sess)
        if question is None:
            return [self._error("There is no open question to hint on.")]
        used = self._hints_pending.get(question.id, 0)
        if used >= hints_mod.MAX_PRE_ANSWER_HINT_LEVEL:
            return [self._error(
                "All 4 pre-answer hint levels have already been given for "
                "this question. The level-5 full explanation comes after "
                "your answer is scored (spec §7.4)."
            )]
        return self._send_hint(db, sess, question, used)

    def _send_hint(
        self, db: Session, sess: InterviewSession, question: Question, used: int
    ) -> List[Dict]:
        provider = self._get_provider(sess)
        level, text = hints_mod.next_hint(question, used, provider, sess.language)
        self._hints_pending[question.id] = used + 1
        transcript_store.add_entry(
            db, sess.id, "interviewer", "(hint, level {0}) {1}".format(level, text)
        )
        return [
            {
                "type": "hint",
                "level": level,
                "text": text,
                "question_id": question.id,
                "hints_used": used + 1,
            }
        ]

    def _on_silence(self, db: Session, sess: InterviewSession, _m: Dict) -> List[Dict]:
        if sess.status != "active":
            return []
        provider = self._get_provider(sess)
        try:
            from ..llm.interviewer import checkin_after_silence  # lazy: Agent B

            text = checkin_after_silence(sess.interviewer_style, provider,
                                         sess.language)
        except Exception:  # noqa: BLE001
            text = _fallback_checkin(sess.interviewer_style, sess.language)
        question = self._current_question(db, sess)
        total = len(self._questions(db, sess))
        return [
            self._interviewer_msg(
                db, sess, "checkin", text,
                section=question.section if question is not None else self._current_section_name(sess),
                question_id=question.id if question is not None else None,
                question_index=int(sess.current_question_idx or 0),
                total_questions=total,
            )
        ]

    def _on_more_time_response(
        self, db: Session, sess: InterviewSession, m: Dict
    ) -> List[Dict]:
        wants_more = bool(m.get("wants_more_time"))
        question = self._current_question(db, sess)
        total = len(self._questions(db, sess))
        if wants_more or question is None:
            return [
                self._interviewer_msg(
                    db, sess, "ack", "Of course — take your time, there's no rush.",
                    section=question.section if question is not None else self._current_section_name(sess),
                    question_id=question.id if question is not None else None,
                    question_index=int(sess.current_question_idx or 0),
                    total_questions=total,
                )
            ]
        # Doesn't want more time: only the adaptive policy may volunteer a
        # hint (spec §7.4: on_request hints come exclusively from an explicit
        # hint_request, since every hint costs a scoring penalty).
        if sess.hint_policy == "adaptive":
            used = self._hints_pending.get(question.id, 0)
            if used < hints_mod.MAX_PRE_ANSWER_HINT_LEVEL:
                return self._send_hint(db, sess, question, used)
        if sess.hint_policy == "on_request":
            return [
                self._interviewer_msg(
                    db, sess, "ack",
                    ("אין בעיה. אם תרצה כיוון, בקש רמז בכל רגע — אחרת אשמח "
                     "לשמוע את הניסיון הטוב ביותר שלך.")
                    if _is_he(sess.language) else
                    "No problem. If you'd like a nudge, ask for a hint any "
                    "time — otherwise I'm happy to hear your best attempt.",
                    section=question.section, question_id=question.id,
                    question_index=int(sess.current_question_idx or 0),
                    total_questions=total,
                )
            ]
        # Hints unavailable: gently repeat the question.
        repeat = (
            "אחזור על השאלה: {0}" if _is_he(sess.language)
            else "Let me repeat the question: {0}"
        ).format(question.question_text)
        return [
            self._interviewer_msg(
                db, sess, "question", repeat,
                section=question.section, question_id=question.id,
                question_index=int(sess.current_question_idx or 0),
                total_questions=total, persist=False,
            )
        ]

    def _on_interrupt(self, db: Session, sess: InterviewSession, _m: Dict) -> List[Dict]:
        # Client cancels TTS locally; server just acknowledges state (no-op).
        return [self._state_msg(sess)]

    def _on_barge_in(self, db: Session, sess: InterviewSession, m: Dict) -> List[Dict]:
        """Candidate talked over the interviewer: persist the interjection and
        (optionally) speak a short adaptive reply, then continue normally."""
        text = str(m.get("text") or "").strip()
        if text:
            self._on_partial(db, sess, {"text": text})
        if sess.status != "active":
            return [self._state_msg(sess)]
        question = self._current_question(db, sess)
        section = question.section if question is not None else self._sections(sess)[0]
        provider = self._get_provider(sess)
        reply = ""
        try:
            from ..llm.interviewer import barge_in_reply  # lazy: Agent B

            reply = barge_in_reply(
                question_text=(question.question_text if question is not None else ""),
                interjection=text,
                section=section,
                style=sess.interviewer_style,
                provider=provider,
                language=sess.language,
            )
        except Exception:  # noqa: BLE001
            reply = ""
        msgs: List[Dict] = []
        if reply and reply.strip():
            msgs.append(
                self._interviewer_msg(
                    db, sess, "reply", reply.strip(),
                    section=section,
                    question_id=(question.id if question is not None else None),
                    question_index=int(sess.current_question_idx or 0),
                    total_questions=len(self._questions(db, sess)),
                )
            )
        msgs.append(self._state_msg(sess))
        return msgs

    def _on_pause(self, db: Session, sess: InterviewSession, _m: Dict) -> List[Dict]:
        if sess.status == "active":
            sess.status = "paused"
        self._last_monotonic = None
        transcript_store.add_entry(db, sess.id, "system", "Interview paused.")
        return [self._state_msg(sess)]

    def _on_resume(self, db: Session, sess: InterviewSession, _m: Dict) -> List[Dict]:
        if sess.status == "completed":
            return [self._state_msg(sess)]
        sess.status = "active"
        self._last_monotonic = time.monotonic()
        transcript_store.add_entry(db, sess.id, "system", "Interview resumed.")
        msgs = [self._state_msg(sess)]
        msgs += self._ask_current(db, sess, reask=True)
        return msgs

    def _on_skip(self, db: Session, sess: InterviewSession, _m: Dict) -> List[Dict]:
        if sess.status != "active":
            return [self._state_msg(sess)]
        question = self._current_question(db, sess)
        if question is None:
            return self._finish(db, sess)
        transcript_store.add_entry(
            db, sess.id, "system", "Question skipped: {0}".format(question.question_text)
        )
        self._hints_pending.pop(question.id, None)
        if self._awaiting_followup == question.id:
            self._awaiting_followup = None
        sess.current_question_idx = int(sess.current_question_idx or 0) + 1
        msgs = self._ask_current(db, sess)
        msgs.append(self._state_msg(sess))
        return msgs

    def _on_end(self, db: Session, sess: InterviewSession, _m: Dict) -> List[Dict]:
        if sess.status == "completed":
            return [self._state_msg(sess)]
        return self._finish(db, sess)

    # ------------------------------------------------------------ mechanics
    def _current_section_name(self, sess: InterviewSession) -> str:
        sections = self._sections(sess)
        idx = min(max(int(sess.current_section_idx or 0), 0), len(sections) - 1)
        return sections[idx]

    def _ask_current(
        self, db: Session, sess: InterviewSession, reask: bool = False
    ) -> List[Dict]:
        """Emit (section_change +) the current question, or wrap-up prompts."""
        if sess.status == "completed":
            return []
        qs = self._questions(db, sess)
        idx = int(sess.current_question_idx or 0)
        sections = self._sections(sess)
        msgs: List[Dict] = []

        if idx >= len(qs):
            # All planned question rows done → candidate-questions section.
            if CANDIDATE_QUESTIONS_SECTION in sections:
                target = sections.index(CANDIDATE_QUESTIONS_SECTION)
                if int(sess.current_section_idx or 0) != target:
                    sess.current_section_idx = target
                    msgs.append(
                        {
                            "type": "section_change",
                            "section": CANDIDATE_QUESTIONS_SECTION,
                            "section_index": target,
                            "total_sections": len(sections),
                        }
                    )
                wrap = (
                    "לפני שנסיים — אילו שאלות יש לך אליי על התפקיד, הצוות או "
                    "העבודה?"
                    if _is_he(sess.language) else
                    "Before we wrap up — what questions do you have for "
                    "me about the role, the team, or the work?"
                )
                msgs.append(
                    self._interviewer_msg(
                        db, sess, "question", wrap,
                        section=CANDIDATE_QUESTIONS_SECTION, question_id=None,
                        question_index=len(qs), total_questions=len(qs),
                        persist=not reask,
                    )
                )
                return msgs
            return self._finish(db, sess)

        question = qs[idx]
        # Section change detection against the plan's section list.
        if question.section in sections:
            target = sections.index(question.section)
            if int(sess.current_section_idx or 0) != target:
                sess.current_section_idx = target
                msgs.append(
                    {
                        "type": "section_change",
                        "section": question.section,
                        "section_index": target,
                        "total_sections": len(sections),
                    }
                )
        text = question.question_text if reask else self._phrase(sess, question)
        if question.asked_at is None:
            question.asked_at = datetime.utcnow()
        msgs.append(
            self._interviewer_msg(
                db, sess, "question", text,
                section=question.section, question_id=question.id,
                question_index=idx, total_questions=len(qs),
                persist=not reask,
            )
        )
        return msgs

    def _phrase(self, sess: InterviewSession, question: Question) -> str:
        provider = self._get_provider(sess)
        try:
            from ..llm.interviewer import phrase_question  # lazy: Agent B

            text = phrase_question(question, sess.interviewer_style, provider,
                                   sess.language)
            if text and str(text).strip():
                return str(text).strip()
        except Exception:  # noqa: BLE001
            logger.debug("phrase_question unavailable; using bank text", exc_info=True)
        return question.question_text

    def _bank_item_for(self, question: Question) -> Optional[Any]:
        """Resolve the bank item backing an ORM question row (or None).

        Question rows are materialized with fresh UUIDs and carry no
        ``followups`` column, so the bank item is recovered by matching the
        verbatim-copied ``question_text`` against the loaded bank.
        Deterministic and fully offline; generated questions (background,
        fallback) simply have no bank item.
        """
        if self._bank_by_text is None:
            try:
                from ..api.routes_sessions import load_bank  # lazy

                self._bank_by_text = {}
                for item in load_bank():
                    self._bank_by_text[item.question_text] = item
                    # Hebrew sessions store the translated text on the row, so
                    # also key on it to recover the bank item (for follow-ups).
                    if getattr(item, "question_text_he", ""):
                        self._bank_by_text[item.question_text_he] = item
            except Exception:  # noqa: BLE001
                logger.debug("question bank unavailable for follow-ups", exc_info=True)
                self._bank_by_text = {}
        return self._bank_by_text.get(question.question_text)

    def _maybe_followup(
        self,
        sess: InterviewSession,
        question: Question,
        answer_text: str,
        metrics: Optional[MetricScores],
    ) -> Optional[str]:
        """At most one follow-up per question, decided by the interviewer LLM."""
        if question.id in self._followed_up:
            return None
        provider = self._get_provider(sess)
        # Prefer the bank item: it carries the curated ``followups`` list the
        # offline decide_followup path serves deterministically (spec §13.4).
        item: Any = self._bank_item_for(question) or question
        try:
            from ..llm.interviewer import decide_followup  # lazy: Agent B

            fu = decide_followup(item, answer_text, metrics, provider,
                                 sess.language)
            if fu and str(fu).strip():
                return str(fu).strip()
        except Exception:  # noqa: BLE001
            logger.debug("decide_followup unavailable", exc_info=True)
        return None

    def _score_answer(
        self,
        db: Session,
        sess: InterviewSession,
        question: Question,
        answer: Answer,
        text: str,
    ) -> "tuple[MetricScores, str, float]":
        provider = self._get_provider(sess)
        context: List[str] = []
        if sess.use_wiki:
            try:
                from ..rag.retriever import get_retriever  # lazy: Agent B

                retriever = get_retriever()
                if getattr(retriever, "loaded", False):
                    context = [
                        r.text for r in retriever.search(question.question_text, k=3)
                    ]
            except Exception:  # noqa: BLE001
                logger.debug("retriever unavailable for scoring context", exc_info=True)
        metrics: Optional[MetricScores] = None
        feedback = ""
        try:
            from ..llm.scorer import evaluate_answer  # lazy: Agent B

            metrics, feedback = evaluate_answer(
                question, text, sess.role, context, provider,
                language=sess.language,
            )
        except Exception:  # noqa: BLE001
            logger.warning("evaluate_answer unavailable; heuristic fallback", exc_info=True)
        if metrics is None:
            metrics, feedback = _fallback_evaluate(question, text)
        overall = compute_overall(metrics, sess.role, answer.hints_used or 0)
        score = Score(
            answer_id=answer.id,
            overall=overall,
            feedback=feedback or "",
            **metrics.model_dump(),
        )
        db.add(score)
        return metrics, feedback or "", overall

    def _candidate_questions_ack(
        self, db: Session, sess: InterviewSession, text: str
    ) -> Dict[str, Any]:
        provider = self._get_provider(sess)
        reply = (
            "זו שאלה מצוינת — במסגרת התרגול הזו אשאיר את הפרטים לחברה שאליה "
            "אתה מכוון, אבל זה בדיוק סוג הדבר ששווה לשאול מראיין אמיתי."
            if _is_he(sess.language) else
            "That's a great question — in this practice setting I'll leave "
            "the specifics to your target company, but it's exactly the kind "
            "of thing worth asking a real interviewer."
        )
        if text and provider is not None and getattr(provider, "name", "offline") != "offline":
            try:
                generated = provider.complete_text(
                    system=(
                        "You are a {0} technical interviewer. The candidate just "
                        "asked you a question at the end of the interview. Answer "
                        "briefly and warmly in 2-3 sentences.{1}".format(
                            sess.interviewer_style,
                            " Reply in Hebrew (עברית)." if _is_he(sess.language) else "",
                        )
                    ),
                    prompt=text,
                    max_tokens=200,
                )
                if generated and generated.strip():
                    reply = generated.strip()
            except Exception:  # noqa: BLE001
                pass
        total = len(self._questions(db, sess))
        return self._interviewer_msg(
            db, sess, "ack", reply,
            section=CANDIDATE_QUESTIONS_SECTION, question_id=None,
            question_index=total, total_questions=total,
        )

    def _finish(self, db: Session, sess: InterviewSession) -> List[Dict]:
        """Closing message, mark completed, flag background report generation."""
        provider = self._get_provider(sess)
        try:
            from ..llm.interviewer import closing  # lazy: Agent B

            text = closing(sess.interviewer_style, provider, sess.language)
        except Exception:  # noqa: BLE001
            text = _fallback_closing(sess.interviewer_style, sess.language)
        sess.status = "completed"
        sess.completed_at = datetime.utcnow()
        self._last_monotonic = None
        self.report_pending = True
        total = len(self._questions(db, sess))
        msgs = [
            self._interviewer_msg(
                db, sess, "closing", text,
                section=self._current_section_name(sess), question_id=None,
                question_index=total, total_questions=total,
            ),
            self._state_msg(sess),
        ]
        return msgs
