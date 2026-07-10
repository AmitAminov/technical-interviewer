"""AI logic: using hints lowers the overall score for the same answer."""
from __future__ import annotations

from app.core.orchestrator import InterviewOrchestrator
from app.core.scoring import compute_overall
from app.llm.scorer import evaluate_answer
from app.schemas import QuestionBankItem

ITEM = QuestionBankItem(
    id="hp-1",
    role="AI Engineer",
    topic="Embeddings",
    difficulty="Mid-level",
    question_text="What are embeddings and why are they useful?",
    expected_points=[
        "dense vector representation",
        "semantic similarity",
        "learned from data",
    ],
)

ANSWER = (
    "Embeddings are a dense vector representation of items such as words or "
    "documents, learned from data so that semantic similarity corresponds to "
    "closeness in the vector space. For example, similar sentences map to "
    "nearby vectors, which enables search and clustering; however, the "
    "quality depends on the training corpus."
)


def test_same_answer_scores_lower_with_hints(offline_provider):
    metrics, _ = evaluate_answer(ITEM, ANSWER, "AI Engineer", [], offline_provider)
    no_hints = compute_overall(metrics, "AI Engineer", 0)
    one_hint = compute_overall(metrics, "AI Engineer", 1)
    three_hints = compute_overall(metrics, "AI Engineer", 3)
    assert no_hints > one_hint > three_hints
    import pytest

    assert no_hints - one_hint == pytest.approx(0.15)


def test_hint_penalty_applies_in_live_flow(db, make_session):
    """Two identical sessions/answers; the hinted one gets a lower overall."""

    def _run(with_hints):
        sess = make_session(hint_policy="on_request")
        orch = InterviewOrchestrator(sess["id"])
        orch.handle(db, {"type": "start"})
        if with_hints:
            orch.handle(db, {"type": "hint_request"})
            orch.handle(db, {"type": "hint_request"})
        msgs = orch.handle(
            db,
            {"type": "answer", "text": ANSWER, "duration_seconds": 30.0,
             "input_mode": "text"},
        )
        return next(m for m in msgs if m["type"] == "score")

    clean = _run(with_hints=False)
    hinted = _run(with_hints=True)
    # identical metrics (same deterministic scorer, same text) ...
    assert clean["scores"] == hinted["scores"]
    # ... but the hinted overall is 2 x 0.15 lower (floored at 1.0)
    assert hinted["overall"] < clean["overall"]
    expected = max(1.0, round(clean["overall"] - 0.30, 2))
    assert abs(hinted["overall"] - expected) <= 0.011  # float rounding slack


def test_report_counts_total_hints(db, make_session):
    from app.core.report_generator import generate_report

    sess = make_session(hint_policy="on_request")
    orch = InterviewOrchestrator(sess["id"])
    orch.handle(db, {"type": "start"})
    orch.handle(db, {"type": "hint_request"})
    orch.handle(db, {"type": "hint_request"})
    orch.handle(db, {"type": "hint_request"})
    # answer everything to completion
    from app.models import InterviewSession

    for _ in range(20):
        if db.get(InterviewSession, sess["id"]).status == "completed":
            break
        orch.handle(
            db,
            {"type": "answer", "text": ANSWER, "duration_seconds": 15.0,
             "input_mode": "text"},
        )
    report = generate_report(db, sess["id"])
    assert report.hints_used_total == 3
