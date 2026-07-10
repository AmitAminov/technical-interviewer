"""Unit tests: hint levels 1..5 and the three hint policies (DESIGN.md §8).

Levels 1-4 are served pre-answer; level 5 (full explanation) is only served
after the answer has been scored (spec §7.4).
"""
from __future__ import annotations

import pytest

from app.core.hints import (
    MAX_HINT_LEVEL,
    MAX_PRE_ANSWER_HINT_LEVEL,
    full_explanation,
    next_hint,
    offline_hint,
)
from app.core.orchestrator import InterviewOrchestrator
from app.schemas import QuestionBankItem

QUESTION = QuestionBankItem(
    id="hint-q1",
    role="Data Scientist",
    topic="Statistics",
    difficulty="Mid-level",
    question_text="Explain the bias-variance trade-off.",
    expected_points=[
        "definition of bias and variance",
        "decomposition of expected error",
        "model complexity relationship",
        "regularization as a control",
    ],
)


# ------------------------------------------------------------- hint mechanics
def test_next_hint_levels_ascend_1_to_5():
    seen = []
    for used in range(5):
        level, text = next_hint(QUESTION, used, provider=None)
        assert level == used + 1
        assert text.strip()
        seen.append(text)
    # each level produces distinct guidance
    assert len(set(seen)) == 5


def test_next_hint_caps_at_level_5():
    level, text = next_hint(QUESTION, 9, provider=None)
    assert level == MAX_HINT_LEVEL
    assert text.strip()


def test_offline_hints_grow_from_expected_points():
    level3 = offline_hint(QUESTION, 3)
    for point in QUESTION.expected_points:
        assert point in level3  # structured outline covers every point
    level1 = offline_hint(QUESTION, 1)
    assert QUESTION.expected_points[0].rstrip(".") in level1


def test_offline_hint_without_points_still_works():
    bare = QuestionBankItem(
        id="bare", role="AI Engineer", topic="RAG", difficulty="Junior",
        question_text="What is RAG?", expected_points=[],
    )
    for level in range(1, 6):
        assert offline_hint(bare, level).strip()


def test_full_explanation_covers_every_expected_point():
    text = full_explanation(QUESTION, provider=None)
    for point in QUESTION.expected_points:
        assert point in text
    assert text == offline_hint(QUESTION, MAX_HINT_LEVEL)


# ------------------------------------------------------------- hint policies
def _start(db, session_id):
    orch = InterviewOrchestrator(session_id)
    msgs = orch.handle(db, {"type": "start"})
    assert any(m["type"] == "interviewer" and m["kind"] == "question" for m in msgs)
    return orch


def test_policy_none_rejects_hint_request(db, make_session):
    sess = make_session(hint_policy="none")
    orch = _start(db, sess["id"])
    msgs = orch.handle(db, {"type": "hint_request"})
    assert len(msgs) == 1
    assert msgs[0]["type"] == "error"
    assert "disabled" in msgs[0]["message"].lower()


def test_policy_on_request_serves_levels_1_to_4_then_defers_level_5(db, make_session):
    sess = make_session(hint_policy="on_request")
    orch = _start(db, sess["id"])
    for expected_level in range(1, MAX_PRE_ANSWER_HINT_LEVEL + 1):
        msgs = orch.handle(db, {"type": "hint_request"})
        assert msgs[0]["type"] == "hint"
        assert msgs[0]["level"] == expected_level
        assert msgs[0]["hints_used"] == expected_level
        assert msgs[0]["text"].strip()
        assert msgs[0]["question_id"]
    # fifth request: level 5 is the full explanation, held until after scoring
    msgs = orch.handle(db, {"type": "hint_request"})
    assert msgs[0]["type"] == "error"
    assert "scored" in msgs[0]["message"].lower()


def test_full_explanation_emitted_after_scoring_with_all_hints(db, make_session):
    from app.core.scoring import compute_overall
    from app.models import Answer, Question
    from app.schemas import MetricScores

    sess = make_session(hint_policy="on_request")
    orch = _start(db, sess["id"])
    for _ in range(MAX_PRE_ANSWER_HINT_LEVEL):
        msgs = orch.handle(db, {"type": "hint_request"})
        assert msgs[0]["type"] == "hint"
    msgs = orch.handle(
        db,
        {"type": "answer",
         "text": "The bias variance trade-off relates model complexity to error decomposition.",
         "duration_seconds": 20.0, "input_mode": "text"},
    )
    types = [m["type"] for m in msgs]
    score_idx = types.index("score")
    hint_idx = types.index("hint")
    assert hint_idx == score_idx + 1, "full explanation follows the score"
    hint5 = msgs[hint_idx]
    assert hint5["level"] == MAX_HINT_LEVEL
    assert hint5["hints_used"] == MAX_HINT_LEVEL
    assert hint5["text"].strip()
    # the full explanation counts as a hint: persisted and penalized
    answer = (
        db.query(Answer)
        .join(Question, Answer.question_id == Question.id)
        .filter(Question.session_id == sess["id"])
        .one()
    )
    assert answer.hints_used == MAX_HINT_LEVEL
    score = msgs[score_idx]
    metrics = MetricScores.model_validate(score["scores"])
    assert score["overall"] == compute_overall(metrics, "Data Scientist", MAX_HINT_LEVEL)


def test_policy_adaptive_silence_checkin_then_hint(db, make_session):
    sess = make_session(hint_policy="adaptive")
    orch = _start(db, sess["id"])
    # client-detected silence -> check-in asking about more time / hint
    msgs = orch.handle(db, {"type": "silence", "seconds": 13.0})
    assert msgs[0]["type"] == "interviewer"
    assert msgs[0]["kind"] == "checkin"
    # candidate does NOT want more time -> adaptive hint offer
    msgs = orch.handle(db, {"type": "more_time_response", "wants_more_time": False})
    assert msgs[0]["type"] == "hint"
    assert msgs[0]["level"] == 1


def test_policy_adaptive_offers_hint_after_weak_answer(db, make_session):
    sess = make_session(hint_policy="adaptive")
    orch = _start(db, sess["id"])
    msgs = orch.handle(
        db,
        {"type": "answer", "text": "no idea", "duration_seconds": 5.0,
         "input_mode": "text"},
    )
    acks = [m for m in msgs if m.get("type") == "interviewer" and m.get("kind") == "ack"]
    assert acks, "adaptive policy should offer help after a weak answer"
    assert "hint" in acks[0]["text"].lower()


def test_hints_used_recorded_on_answer(db, make_session):
    from app.models import Answer, Question

    sess = make_session(hint_policy="on_request")
    orch = _start(db, sess["id"])
    orch.handle(db, {"type": "hint_request"})
    orch.handle(db, {"type": "hint_request"})
    msgs = orch.handle(
        db,
        {"type": "answer",
         "text": "The bias variance trade-off relates model complexity to error decomposition.",
         "duration_seconds": 20.0, "input_mode": "text"},
    )
    score = next(m for m in msgs if m["type"] == "score")
    answers = (
        db.query(Answer)
        .join(Question, Answer.question_id == Question.id)
        .filter(Question.session_id == sess["id"])
        .all()
    )
    assert len(answers) == 1
    assert answers[0].hints_used == 2
    assert score["overall"] >= 1.0
