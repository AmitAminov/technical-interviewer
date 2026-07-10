"""Unit tests: difficulty tiering logic and the /api/question-bank filter."""
from __future__ import annotations

from app.core.question_selector import _difficulty_ring
from app.schemas import DIFFICULTIES


def test_ring_exact_first():
    tiers = _difficulty_ring("Senior")
    assert tiers[0] == ["Senior"]


def test_ring_widens_one_step_at_a_time():
    tiers = _difficulty_ring("Senior")
    # Senior is index 2: step 1 -> Mid-level + Research-level,
    # step 2 -> Junior + Staff/Lead-level.
    assert tiers[1] == ["Mid-level", "Research-level"]
    assert tiers[2] == ["Junior", "Staff/Lead-level"]


def test_ring_covers_all_difficulties():
    for diff in DIFFICULTIES:
        tiers = _difficulty_ring(diff)
        flattened = [d for tier in tiers for d in tier]
        assert sorted(flattened) == sorted(DIFFICULTIES)


def test_ring_edge_difficulty():
    tiers = _difficulty_ring("Junior")
    assert tiers[0] == ["Junior"]
    assert tiers[1] == ["Mid-level"]


def test_ring_unknown_difficulty_safe():
    tiers = _difficulty_ring("Impossible")
    assert tiers[0] == ["Impossible"]
    assert list(DIFFICULTIES) in tiers


def test_question_bank_endpoint_difficulty_filter(client):
    resp = client.get("/api/question-bank", params={"difficulty": "Senior"})
    assert resp.status_code == 200
    items = resp.json()
    assert items, "seed bank has Senior questions"
    assert all(i["difficulty"] == "Senior" for i in items)


def test_question_bank_endpoint_combined_filters(client):
    resp = client.get(
        "/api/question-bank",
        params={"role": "AI Engineer", "difficulty": "Mid-level"},
    )
    assert resp.status_code == 200
    items = resp.json()
    assert items
    assert all(
        i["role"] == "AI Engineer" and i["difficulty"] == "Mid-level" for i in items
    )


def test_question_bank_endpoint_topic_filter(client):
    resp = client.get(
        "/api/question-bank", params={"role": "Data Scientist", "topic": "SQL"}
    )
    assert resp.status_code == 200
    items = resp.json()
    assert items
    assert all(i["topic"] == "SQL" for i in items)
