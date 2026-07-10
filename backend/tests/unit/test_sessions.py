"""Unit tests: session creation returns ready status + a valid plan."""
from __future__ import annotations

from app.schemas import InterviewPlan


def test_create_session_returns_ready_and_plan(make_session):
    sess = make_session()
    assert sess["status"] == "ready"
    assert sess["plan"] is not None
    plan = InterviewPlan.model_validate(sess["plan"])
    assert plan.sections[0] == "background"
    assert plan.sections[-1] == "candidate questions"
    assert plan.role == "Data Scientist"
    assert plan.duration_minutes == 10


def test_plan_sections_have_questions(make_session, bank):
    sess = make_session(mode="Quick Practice", duration_minutes=15)
    plan = InterviewPlan.model_validate(sess["plan"])
    bank_ids = {item.id for item in bank}
    technical = [
        s for s in plan.sections if s not in ("background", "candidate questions", "behavioral")
    ]
    assert technical, "plan must contain technical sections"
    all_ids = [qid for s in technical for qid in plan.section_questions.get(s, [])]
    assert all_ids, "technical sections must be allocated question ids"
    for qid in all_ids:
        assert qid in bank_ids or qid.startswith(("gen-", "net-"))


def test_standard_mode_includes_behavioral_section(make_session):
    sess = make_session(mode="Standard", duration_minutes=50)
    plan = InterviewPlan.model_validate(sess["plan"])
    assert "behavioral" in plan.sections
    assert plan.section_questions.get("behavioral"), "behavioral questions allocated"


def test_create_session_unknown_user_404(client):
    payload = {
        "user_id": "missing-user",
        "role": "Data Scientist",
        "mode": "Quick Practice",
        "difficulty": "Junior",
        "duration_minutes": 10,
    }
    resp = client.post("/api/sessions", json=payload)
    assert resp.status_code == 404


def test_create_session_validates_enums(client, make_user):
    user = make_user()
    payload = {
        "user_id": user["id"],
        "role": "Wizard",
        "mode": "Quick Practice",
        "difficulty": "Junior",
        "duration_minutes": 10,
    }
    resp = client.post("/api/sessions", json=payload)
    assert resp.status_code == 422


def test_get_session_roundtrip_includes_plan(client, make_session):
    sess = make_session()
    resp = client.get("/api/sessions/{0}".format(sess["id"]))
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == sess["id"]
    assert data["status"] == "ready"
    assert data["plan"]["sections"] == sess["plan"]["sections"]
    # privacy toggles echoed back
    assert data["allow_internet"] is False
    assert data["disable_cloud_ai"] is True


def test_get_unknown_session_404(client):
    resp = client.get("/api/sessions/not-a-session")
    assert resp.status_code == 404


def test_focus_topics_prioritized_in_plan(make_session):
    sess = make_session(
        mode="Standard",
        duration_minutes=50,
        focus_topics=["SQL", "Statistics"],
    )
    plan = InterviewPlan.model_validate(sess["plan"])
    assert "SQL" in plan.sections
    assert "Statistics" in plan.sections


def test_session_delete_full(client, make_session):
    sess = make_session()
    resp = client.delete("/api/sessions/{0}".format(sess["id"]))
    assert resp.status_code == 200
    assert client.get("/api/sessions/{0}".format(sess["id"])).status_code == 404
