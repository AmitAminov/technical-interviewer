"""Unit tests: bank filtering, no-duplicate selection, difficulty fallback."""
from __future__ import annotations

from app.core.question_selector import generate_fallback_item, select_questions
from app.schemas import QuestionBankItem


def _item(id, role="Data Scientist", topic="SQL", difficulty="Mid-level"):
    return QuestionBankItem(
        id=id,
        role=role,
        topic=topic,
        difficulty=difficulty,
        question_text="Question {0}?".format(id),
        expected_points=["point one", "point two"],
    )


MINI_BANK = [
    _item("sql-j1", difficulty="Junior"),
    _item("sql-j2", difficulty="Junior"),
    _item("sql-m1", difficulty="Mid-level"),
    _item("sql-m2", difficulty="Mid-level"),
    _item("sql-s1", difficulty="Senior"),
    _item("st-m1", topic="Statistics", difficulty="Mid-level"),
    _item("ar-m1", role="Algorithm Researcher", topic="Algorithms"),
]


def test_filters_by_exact_role():
    picked = select_questions(MINI_BANK, "Algorithm Researcher", "Mid-level", None, 10)
    assert [q.id for q in picked] == ["ar-m1"]
    assert all(q.role == "Algorithm Researcher" for q in picked)


def test_filters_by_topic():
    picked = select_questions(MINI_BANK, "Data Scientist", "Mid-level", ["Statistics"], 10)
    assert [q.id for q in picked] == ["st-m1"]


def test_exact_difficulty_preferred_no_unnecessary_fallback():
    picked = select_questions(MINI_BANK, "Data Scientist", "Mid-level", ["SQL"], 2)
    assert [q.id for q in picked] == ["sql-m1", "sql-m2"]
    assert all(q.difficulty == "Mid-level" for q in picked)


def test_difficulty_fallback_when_starved():
    # Only one Senior SQL item exists; asking for 3 must widen to adjacent tiers.
    picked = select_questions(MINI_BANK, "Data Scientist", "Senior", ["SQL"], 3)
    ids = [q.id for q in picked]
    assert ids[0] == "sql-s1"  # exact difficulty first
    assert len(ids) == 3
    assert len(set(ids)) == 3
    # Mid-level is one step from Senior, so it fills before Junior.
    assert ids[1].startswith("sql-m")


def test_no_duplicates_and_exclude_ids_honored():
    exclude = ["sql-m1"]
    picked = select_questions(MINI_BANK, "Data Scientist", "Mid-level", ["SQL"], 10, exclude)
    ids = [q.id for q in picked]
    assert "sql-m1" not in ids
    assert len(ids) == len(set(ids))


def test_accumulated_exclusion_across_sections():
    """Simulates section-by-section selection within one session: no repeats."""
    exclude: list = []
    seen: list = []
    for _ in range(4):
        picked = select_questions(MINI_BANK, "Data Scientist", "Mid-level", ["SQL"], 2, exclude)
        seen.extend(q.id for q in picked)
        exclude.extend(q.id for q in picked)
    assert len(seen) == len(set(seen))


def test_n_zero_and_empty_bank():
    assert select_questions(MINI_BANK, "Data Scientist", "Junior", None, 0) == []
    assert select_questions([], "Data Scientist", "Junior", None, 5) == []


def test_generate_fallback_item_shape():
    gen = generate_fallback_item("AI Engineer", "RAG", "Senior")
    assert gen.id.startswith("gen-")
    assert gen.role == "AI Engineer"
    assert gen.topic == "RAG"
    assert gen.difficulty == "Senior"
    assert gen.source == "generated"
    assert gen.expected_points
    assert "RAG" in gen.question_text


def test_real_bank_contract_properties(bank):
    """Seed bank sanity: >=120 items, unique ids, valid enum fields."""
    assert len(bank) >= 120
    ids = [item.id for item in bank]
    assert len(ids) == len(set(ids))
    behavioral = [i for i in bank if i.is_behavioral]
    for role in ("Data Scientist", "Algorithm Researcher", "AI Engineer"):
        assert sum(1 for i in behavioral if i.role == role) >= 4
