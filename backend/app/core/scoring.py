"""Weighted scoring formula per DESIGN.md §6 (spec §7.5).

Raw 1–5 metrics come from ``app.llm.scorer.evaluate_answer``; this module only
combines them. :func:`compute_overall` is pure and unit-testable.
"""
from __future__ import annotations

from typing import Dict

from ..config import settings
from ..schemas import MetricScores

METRIC_NAMES = [
    "correctness",
    "depth",
    "clarity",
    "structure",
    "practicality",
    "mathematical_rigor",
    "tradeoff_awareness",
    "communication",
]

# Exact weight table from DESIGN.md §6. Each column sums to 1.0.
# "base" is the spec's suggested formula, used for unknown roles.
ROLE_WEIGHTS: Dict[str, Dict[str, float]] = {
    "base": {
        "correctness": 0.30,
        "depth": 0.20,
        "clarity": 0.15,
        "structure": 0.10,
        "practicality": 0.10,
        "mathematical_rigor": 0.00,
        "tradeoff_awareness": 0.10,
        "communication": 0.05,
    },
    "Data Scientist": {
        "correctness": 0.30,
        "depth": 0.15,
        "clarity": 0.10,
        "structure": 0.10,
        "practicality": 0.15,
        "mathematical_rigor": 0.10,
        "tradeoff_awareness": 0.05,
        "communication": 0.05,
    },
    "Algorithm Researcher": {
        "correctness": 0.25,
        "depth": 0.20,
        "clarity": 0.10,
        "structure": 0.10,
        "practicality": 0.05,
        "mathematical_rigor": 0.15,
        "tradeoff_awareness": 0.10,
        "communication": 0.05,
    },
    "AI Engineer": {
        "correctness": 0.25,
        "depth": 0.15,
        "clarity": 0.10,
        "structure": 0.10,
        "practicality": 0.15,
        "mathematical_rigor": 0.00,
        "tradeoff_awareness": 0.20,
        "communication": 0.05,
    },
}


def get_weights(role: str) -> Dict[str, float]:
    """Return the weight column for a role (base column for unknown roles)."""
    return ROLE_WEIGHTS.get(role, ROLE_WEIGHTS["base"])


def compute_overall(metrics: MetricScores, role: str, hints_used: int = 0) -> float:
    """Weighted overall score in [1.0, 5.0], rounded to 2 decimal places.

    Hint penalty (DESIGN.md §6): ``overall = max(1.0, overall - 0.15 * hints_used)``.
    Pure function — no I/O, no randomness.
    """
    weights = get_weights(role)
    overall = 0.0
    for name in METRIC_NAMES:
        overall += weights[name] * float(getattr(metrics, name))
    penalty = settings.hint_penalty_per_hint * max(0, int(hints_used))
    overall = max(1.0, overall - penalty)
    return round(overall, 2)
