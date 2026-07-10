"""Unit tests: cross-session progress tracking + study curriculum (spec §16)."""
from __future__ import annotations

import pytest

from app.core import report_generator
from app.core.progress import classify_topics
from app.schemas import ProgressOut


def _progress(client, user_id):
    resp = client.get("/api/users/{0}/progress".format(user_id))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    ProgressOut.model_validate(body)  # schema contract holds
    return body


def _degrade_first_topic(db, session_id, value=2.0):
    """Set every per-answer overall for the session's first topic to `value`."""
    from app.models import Answer, Question, Score

    rows = (
        db.query(Score, Question.topic)
        .join(Answer, Score.answer_id == Answer.id)
        .join(Question, Answer.question_id == Question.id)
        .filter(Question.session_id == session_id)
        .order_by(Question.order_idx)
        .all()
    )
    assert rows, "completed session must have scored answers"
    target = rows[0][1]
    for score, topic in rows:
        if topic == target:
            score.overall = value
    db.commit()
    return target


def test_unknown_user_404(client):
    resp = client.get("/api/users/no-such-user/progress")
    assert resp.status_code == 404


def test_empty_history_returns_empty_progress(client, make_user):
    user = make_user(name="Fresh Candidate")
    body = _progress(client, user["id"])
    assert body["user_id"] == user["id"]
    assert body["sessions"] == []
    assert body["readiness_trend"] == []
    assert body["topic_trends"] == {}
    assert body["current_weak_topics"] == []
    assert body["current_strong_topics"] == []
    assert body["curriculum"] == []


def test_incomplete_sessions_are_excluded(client, make_user, make_session):
    user = make_user(name="Started But Never Finished")
    make_session(user_id=user["id"])  # status=created, never completed
    body = _progress(client, user["id"])
    assert body["sessions"] == []
    assert body["readiness_trend"] == []


def test_single_completed_session_progress(client, db, completed_session):
    from app.models import InterviewSession

    sid = completed_session()
    weak_topic = _degrade_first_topic(db, sid, value=2.0)
    report = report_generator.generate_report(db, sid)
    user_id = db.get(InterviewSession, sid).user_id

    body = _progress(client, user_id)

    # ---- sessions: exactly this completed session, report-backed scores
    assert [s["id"] for s in body["sessions"]] == [sid]
    sess = body["sessions"][0]
    assert sess["role"] == "Data Scientist"
    assert sess["mode"] == "Quick Practice"
    assert sess["difficulty"] == "Mid-level"
    assert sess["overall_score"] == float(report.overall_score)
    assert sess["role_readiness"] == report.role_readiness
    assert sess["created_at"]

    # ---- readiness trend mirrors the stored report
    assert len(body["readiness_trend"]) == 1
    point = body["readiness_trend"][0]
    assert point["session_id"] == sid
    assert point["score"] == report.role_readiness
    assert 0 <= point["score"] <= 100

    # ---- topic trends: one 0-5 point per topic, matching the report
    assert set(body["topic_trends"].keys()) == set(report.topic_scores.keys())
    for topic, points in body["topic_trends"].items():
        assert [p["session_id"] for p in points] == [sid]
        assert 0.0 <= points[0]["score"] <= 5.0
        assert points[0]["score"] == report.topic_scores[topic]
    assert body["topic_trends"][weak_topic][0]["score"] == 2.0

    # ---- weak/strong classification against the trend data
    assert weak_topic in body["current_weak_topics"]
    for t in body["current_weak_topics"]:
        assert body["topic_trends"][t][-1]["score"] < 3.0
    for t in body["current_strong_topics"]:
        assert body["topic_trends"][t][-1]["score"] >= 4.0

    # ---- curriculum: non-empty, valid priorities, deterministic reasons
    assert body["curriculum"], "weak topic must produce curriculum items"
    for item in body["curriculum"]:
        assert item["title"].strip()
        assert item["reason"].strip()
        assert item["priority"] in (1, 2, 3)
        assert isinstance(item["wiki_refs"], list)
        assert sid in item["source_sessions"]
    titles = {i["title"].lower() for i in body["curriculum"]}
    assert weak_topic.lower() in titles
    weak_item = next(
        i for i in body["curriculum"] if i["title"].lower() == weak_topic.lower()
    )
    assert "2.0/5" in weak_item["reason"]
    assert weak_topic in weak_item["reason"]
    # single-session history: the top (weighted) items are priority 1
    assert body["curriculum"][0]["priority"] == 1


def test_progress_without_report_falls_back_to_session_score(
    client, db, completed_session
):
    """No stored report: readiness falls back to InterviewSession.overall_score."""
    from app.models import InterviewSession

    sid = completed_session()
    row = db.get(InterviewSession, sid)
    row.overall_score = 62.0
    db.commit()

    body = _progress(client, row.user_id)
    sess = next(s for s in body["sessions"] if s["id"] == sid)
    assert sess["overall_score"] == 62.0
    assert sess["role_readiness"] == 62
    assert any(
        p["session_id"] == sid and p["score"] == 62 for p in body["readiness_trend"]
    )
    # topic trends come straight from Score rows, so they exist regardless
    assert body["topic_trends"]


@pytest.mark.slow
def test_progress_curriculum_wiki_refs_use_loaded_index(
    client, db, completed_session, mini_wiki_index, monkeypatch
):
    """Regression: with a loaded wiki index, curriculum wiki_refs are real.

    A silent retriever-load failure used to leave every curriculum item's
    ``wiki_refs`` empty on the running server while /api/health still looked
    fine. This drives the full endpoint path against a real fixture index.
    """
    from app.models import InterviewSession

    monkeypatch.setenv("TI_WIKI_INDEX_DIR", mini_wiki_index)
    sid = completed_session()
    _degrade_first_topic(db, sid, value=2.0)
    report_generator.generate_report(db, sid)
    user_id = db.get(InterviewSession, sid).user_id

    body = _progress(client, user_id)

    assert body["curriculum"], "weak topic must produce curriculum items"
    all_refs = [ref for item in body["curriculum"] for ref in item["wiki_refs"]]
    assert all_refs, "wiki_refs must be non-empty when the index is loaded"
    for ref in all_refs:
        assert ref.endswith(".md")


def test_classify_topics_thresholds():
    weak, strong = classify_topics(
        {"Stats": 2.9, "SQL": 3.0, "Python": 4.0, "RAG": 4.5, "Probability": 1.0}
    )
    # weak strictly below 3.0, weakest first
    assert weak == ["Probability", "Stats"]
    # strong at/above 4.0, strongest first
    assert strong == ["RAG", "Python"]
    # 3.0 <= score < 4.0 is neither weak nor strong
    assert "SQL" not in weak and "SQL" not in strong
