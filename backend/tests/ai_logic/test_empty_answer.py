"""AI logic: empty/near-empty answers score all 1s and never crash."""
from __future__ import annotations

import pytest

from app.core.scoring import METRIC_NAMES
from app.llm.scorer import evaluate_answer
from app.schemas import QuestionBankItem

ITEM = QuestionBankItem(
    id="empty-1",
    role="Data Scientist",
    topic="Statistics",
    difficulty="Junior",
    question_text="What is the central limit theorem?",
    expected_points=["sampling distribution of the mean", "normality as n grows"],
)


@pytest.mark.parametrize("text", ["", "   ", "\n\t", "uh", "I don't know", "pass"])
def test_empty_or_tiny_answers_score_all_ones(offline_provider, text):
    metrics, feedback = evaluate_answer(ITEM, text, "Data Scientist", [],
                                        offline_provider)
    for name in METRIC_NAMES:
        assert getattr(metrics, name) == 1, "{0} must be 1 for empty answer".format(name)
    assert feedback.strip(), "feedback explains the minimum score"
    assert "empty or too short" in feedback


def test_empty_answer_feedback_lists_expected_points(offline_provider):
    _, feedback = evaluate_answer(ITEM, "", "Data Scientist", [], offline_provider)
    for point in ITEM.expected_points:
        assert point in feedback


def test_orchestrator_survives_empty_answer_end_to_end(db, make_session):
    from app.core.orchestrator import InterviewOrchestrator

    sess = make_session()
    orch = InterviewOrchestrator(sess["id"])
    orch.handle(db, {"type": "start"})
    msgs = orch.handle(
        db,
        {"type": "answer", "text": "", "duration_seconds": 0.0,
         "input_mode": "voice"},
    )
    score = next(m for m in msgs if m["type"] == "score")
    assert all(v == 1 for v in score["scores"].values())
    assert score["overall"] == 1.0
    # the interview moves on to the next question instead of crashing
    assert any(
        m["type"] == "interviewer" and m["kind"] == "question" for m in msgs
    )


def test_none_ish_payload_fields_do_not_crash(db, make_session):
    from app.core.orchestrator import InterviewOrchestrator

    sess = make_session()
    orch = InterviewOrchestrator(sess["id"])
    orch.handle(db, {"type": "start"})
    msgs = orch.handle(
        db, {"type": "answer", "text": None, "duration_seconds": None}
    )
    assert any(m["type"] == "score" for m in msgs)
