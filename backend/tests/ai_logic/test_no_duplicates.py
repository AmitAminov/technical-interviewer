"""AI logic: a session's plan and question rows contain no duplicates."""
from __future__ import annotations

import pytest

from app.agents.planning_agent import build_plan
from app.schemas import InterviewPlan, SessionCreate


def _cfg(role, mode, duration, difficulty="Mid-level"):
    return SessionCreate(
        user_id="u", role=role, mode=mode, difficulty=difficulty,
        duration_minutes=duration, allow_internet=False, disable_cloud_ai=True,
    )


@pytest.mark.parametrize(
    "role,mode,duration",
    [
        ("Data Scientist", "Quick Practice", 15),
        ("Data Scientist", "Standard", 60),
        ("Algorithm Researcher", "Standard", 45),
        ("Algorithm Researcher", "Deep Research", 90),
        ("AI Engineer", "Deep Research", 75),
        ("AI Engineer", "Quick Practice", 10),
    ],
)
def test_plan_has_no_duplicate_question_ids(bank, offline_provider, role, mode, duration):
    plan = build_plan(_cfg(role, mode, duration), None, None, None, bank,
                      offline_provider)
    all_ids = [qid for ids in plan.section_questions.values() for qid in ids]
    assert all_ids, "plan allocates questions"
    assert len(all_ids) == len(set(all_ids)), "duplicate question id in plan"
    # sections listed once each
    assert len(plan.sections) == len(set(plan.sections))


def test_created_session_rows_and_plan_are_duplicate_free(db, make_session):
    from app.models import Question

    sess = make_session(mode="Standard", duration_minutes=60)
    plan = InterviewPlan.model_validate(sess["plan"])
    plan_ids = [qid for ids in plan.section_questions.values() for qid in ids]
    assert len(plan_ids) == len(set(plan_ids))

    rows = (
        db.query(Question)
        .filter(Question.session_id == sess["id"])
        .order_by(Question.order_idx)
        .all()
    )
    assert rows, "question rows materialized"
    texts = [r.question_text for r in rows]
    assert len(texts) == len(set(texts)), "same question asked twice in one session"
    order = [r.order_idx for r in rows]
    assert order == sorted(order) and len(order) == len(set(order))


def test_two_sessions_are_independent(make_session):
    """No-dup is per session; a second session may reuse the bank freely."""
    a = make_session()
    b = make_session()
    assert a["id"] != b["id"]
    assert a["status"] == b["status"] == "ready"
