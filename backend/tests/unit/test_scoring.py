"""Unit tests: exact weight-table spot checks, hint penalty, bounds (§6)."""
from __future__ import annotations

import pytest

from app.core.scoring import METRIC_NAMES, ROLE_WEIGHTS, compute_overall, get_weights
from app.schemas import MetricScores


def _metrics(**overrides):
    values = {name: 3 for name in METRIC_NAMES}
    values.update(overrides)
    return MetricScores(**values)


M_MIXED = MetricScores(
    correctness=5, depth=4, clarity=4, structure=3, practicality=3,
    mathematical_rigor=2, tradeoff_awareness=4, communication=5,
)


def test_weight_columns_sum_to_one():
    for role, weights in ROLE_WEIGHTS.items():
        assert abs(sum(weights.values()) - 1.0) < 1e-9, role
        assert set(weights) == set(METRIC_NAMES)


@pytest.mark.parametrize(
    "role,expected",
    [
        ("Data Scientist", 3.90),
        ("Algorithm Researcher", 3.85),
        ("AI Engineer", 4.05),
        ("Totally Unknown Role", 4.15),  # base column fallback
    ],
)
def test_weighted_overall_exact_spot_checks(role, expected):
    """Hand-computed values from the DESIGN.md §6 weight table."""
    assert compute_overall(M_MIXED, role, 0) == pytest.approx(expected)


def test_role_differences_on_same_metrics():
    ds = compute_overall(M_MIXED, "Data Scientist", 0)
    ar = compute_overall(M_MIXED, "Algorithm Researcher", 0)
    ai = compute_overall(M_MIXED, "AI Engineer", 0)
    assert len({ds, ar, ai}) == 3, "role rubrics must differentiate this profile"


def test_base_fallback_used_for_unknown_role():
    assert get_weights("Prompt Wrangler") == ROLE_WEIGHTS["base"]
    assert get_weights("Data Scientist") == ROLE_WEIGHTS["Data Scientist"]


def test_perfect_and_floor_bounds():
    all5 = _metrics(**{name: 5 for name in METRIC_NAMES})
    all1 = _metrics(**{name: 1 for name in METRIC_NAMES})
    for role in ("Data Scientist", "Algorithm Researcher", "AI Engineer", "base"):
        assert compute_overall(all5, role, 0) == pytest.approx(5.0)
        assert compute_overall(all1, role, 0) == pytest.approx(1.0)


def test_hint_penalty_015_per_hint():
    all4 = _metrics(**{name: 4 for name in METRIC_NAMES})
    assert compute_overall(all4, "Data Scientist", 0) == pytest.approx(4.0)
    assert compute_overall(all4, "Data Scientist", 1) == pytest.approx(3.85)
    assert compute_overall(all4, "Data Scientist", 2) == pytest.approx(3.70)


def test_hint_penalty_floors_at_one():
    all1 = _metrics(**{name: 1 for name in METRIC_NAMES})
    assert compute_overall(all1, "Data Scientist", 5) == pytest.approx(1.0)
    all2 = _metrics(**{name: 2 for name in METRIC_NAMES})
    assert compute_overall(all2, "AI Engineer", 50) == pytest.approx(1.0)


def test_negative_hints_do_not_boost():
    all3 = _metrics()
    assert compute_overall(all3, "Data Scientist", -3) == pytest.approx(3.0)


def test_rounding_two_decimals():
    value = compute_overall(M_MIXED, "Data Scientist", 1)
    assert value == round(value, 2)


def test_mathematical_rigor_weighting_by_role():
    """rigor=5 (rest 3): AR (w=.15) > DS (.10) > AI Engineer/base (0.00)."""
    rig = _metrics(mathematical_rigor=5)
    assert compute_overall(rig, "Algorithm Researcher", 0) == pytest.approx(3.3)
    assert compute_overall(rig, "Data Scientist", 0) == pytest.approx(3.2)
    assert compute_overall(rig, "AI Engineer", 0) == pytest.approx(3.0)
    assert compute_overall(rig, "base-unknown", 0) == pytest.approx(3.0)
