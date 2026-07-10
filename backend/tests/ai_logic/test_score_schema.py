"""AI logic: evaluate_answer output always validates the MetricScores schema."""
from __future__ import annotations

from app.core.scoring import METRIC_NAMES
from app.llm.scorer import evaluate_answer
from app.schemas import MetricScores, QuestionBankItem

ITEM = QuestionBankItem(
    id="schema-1",
    role="AI Engineer",
    topic="RAG",
    difficulty="Mid-level",
    question_text="How does retrieval-augmented generation work?",
    expected_points=[
        "retriever finds relevant chunks",
        "chunks injected into the prompt as context",
        "reduces hallucination",
        "embedding similarity search",
    ],
)

ANSWER = (
    "Retrieval-augmented generation first embeds the user query, then a "
    "retriever runs an embedding similarity search over an index of document "
    "chunks; the top relevant chunks are injected into the prompt as context "
    "so the model grounds its response, which reduces hallucination in "
    "practice. However, there is a trade-off with prompt length and latency."
)


def test_output_is_valid_metricscores(offline_provider):
    metrics, feedback = evaluate_answer(ITEM, ANSWER, "AI Engineer", [],
                                        offline_provider)
    assert isinstance(metrics, MetricScores)
    # round-trip through schema validation (would raise on out-of-range ints)
    MetricScores.model_validate(metrics.model_dump())
    for name in METRIC_NAMES:
        value = getattr(metrics, name)
        assert isinstance(value, int)
        assert 1 <= value <= 5
    assert isinstance(feedback, str) and feedback.strip()


def test_deterministic_same_input_same_scores(offline_provider):
    a = evaluate_answer(ITEM, ANSWER, "AI Engineer", [], offline_provider)
    b = evaluate_answer(ITEM, ANSWER, "AI Engineer", [], offline_provider)
    assert a[0].model_dump() == b[0].model_dump()
    assert a[1] == b[1]


def test_provider_none_still_returns_valid_schema():
    metrics, feedback = evaluate_answer(ITEM, ANSWER, "AI Engineer", [], None)
    MetricScores.model_validate(metrics.model_dump())
    assert feedback


def test_offline_provider_complete_json_returns_schema_instance(offline_provider):
    """The offline chain answers EvaluationResult requests with valid models."""
    from app.llm.scorer import (
        ANSWER_BEGIN, ANSWER_END, POINTS_BEGIN, POINTS_END, EvaluationResult,
    )

    prompt = "\n".join([
        POINTS_BEGIN, "- retriever finds relevant chunks", POINTS_END,
        ANSWER_BEGIN, ANSWER, ANSWER_END,
    ])
    result = offline_provider.complete_json("grade", prompt, EvaluationResult)
    assert isinstance(result, EvaluationResult)
    MetricScores.model_validate(result.metrics.model_dump())


def test_ws_score_message_shape_matches_contract(db, make_session):
    """The WS 'score' message carries exactly the 8 contract metrics."""
    from app.core.orchestrator import InterviewOrchestrator

    sess = make_session()
    orch = InterviewOrchestrator(sess["id"])
    orch.handle(db, {"type": "start"})
    msgs = orch.handle(
        db,
        {"type": "answer", "text": ANSWER, "duration_seconds": 20.0,
         "input_mode": "text"},
    )
    score = next(m for m in msgs if m["type"] == "score")
    assert set(score["scores"]) == set(METRIC_NAMES)
    MetricScores.model_validate(score["scores"])
    assert isinstance(score["overall"], float)
    assert 1.0 <= score["overall"] <= 5.0
    assert score["question_id"]
    assert isinstance(score["feedback"], str)
