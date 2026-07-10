"""AI logic: the role rubric changes the overall for identical raw metrics."""
from __future__ import annotations

import pytest

from app.core.scoring import METRIC_NAMES, ROLE_WEIGHTS, compute_overall
from app.schemas import MetricScores

ROLES = ("Data Scientist", "Algorithm Researcher", "AI Engineer")


def _metrics(**overrides):
    values = {name: 3 for name in METRIC_NAMES}
    values.update(overrides)
    return MetricScores(**values)


def test_rigor_heavy_profile_ranks_roles_per_weight_table():
    """rigor=5, rest=3: AR(0.15) > DS(0.10) > AI Engineer(0.00)."""
    metrics = _metrics(mathematical_rigor=5)
    ar = compute_overall(metrics, "Algorithm Researcher", 0)
    ds = compute_overall(metrics, "Data Scientist", 0)
    ai = compute_overall(metrics, "AI Engineer", 0)
    assert ar > ds > ai
    assert ar == pytest.approx(3.3)
    assert ds == pytest.approx(3.2)
    assert ai == pytest.approx(3.0)


def test_tradeoff_heavy_profile_favors_ai_engineer():
    """tradeoff=5, rest=3: AI Engineer(0.20) > AR(0.10) > DS(0.05)."""
    metrics = _metrics(tradeoff_awareness=5)
    ai = compute_overall(metrics, "AI Engineer", 0)
    ar = compute_overall(metrics, "Algorithm Researcher", 0)
    ds = compute_overall(metrics, "Data Scientist", 0)
    assert ai > ar > ds
    assert ai == pytest.approx(3.4)
    assert ds == pytest.approx(3.1)


def test_practicality_heavy_profile_favors_practical_roles():
    """practicality=5, rest=3: DS/AI Engineer (0.15) > AR (0.05)."""
    metrics = _metrics(practicality=5)
    ds = compute_overall(metrics, "Data Scientist", 0)
    ai = compute_overall(metrics, "AI Engineer", 0)
    ar = compute_overall(metrics, "Algorithm Researcher", 0)
    assert ds == ai == pytest.approx(3.3)
    assert ar == pytest.approx(3.1)
    assert ds > ar


def test_flat_profile_identical_across_roles():
    """Uniform metrics: weights sum to 1.0, so every role agrees."""
    for v in (1, 3, 5):
        metrics = _metrics(**{name: v for name in METRIC_NAMES})
        values = {compute_overall(metrics, role, 0) for role in ROLES}
        assert values == {float(v)}


def test_every_role_column_differs_from_base_somewhere():
    base = ROLE_WEIGHTS["base"]
    for role in ROLES:
        assert ROLE_WEIGHTS[role] != base, role


def test_live_flow_applies_session_role_rubric(db, make_session):
    """The same answer scored in AR vs AI Engineer sessions uses role weights."""
    from app.core.orchestrator import InterviewOrchestrator
    from app.core.scoring import compute_overall as co

    answer = (
        "The expected value satisfies the equation E[X] = sum over outcomes, "
        "with variance sigma^2 defined via the distribution; the proof uses "
        "the theorem of total expectation and an asymptotic bound O(log n)."
    )

    def _first_score(role):
        sess = make_session(role=role)
        orch = InterviewOrchestrator(sess["id"])
        orch.handle(db, {"type": "start"})
        msgs = orch.handle(
            db,
            {"type": "answer", "text": answer, "duration_seconds": 20.0,
             "input_mode": "text"},
        )
        return next(m for m in msgs if m["type"] == "score")

    ar = _first_score("Algorithm Researcher")
    ai = _first_score("AI Engineer")
    # deterministic heuristic gives identical raw metrics for the same text
    # against the same background rubric...
    assert ar["scores"] == ai["scores"]
    metrics = MetricScores.model_validate(ar["scores"])
    # ...and each session's overall matches its own role's weight column
    assert ar["overall"] == pytest.approx(co(metrics, "Algorithm Researcher", 0))
    assert ai["overall"] == pytest.approx(co(metrics, "AI Engineer", 0))
    assert ar["overall"] != ai["overall"], "rigor-heavy answer must split AR vs AIE"
