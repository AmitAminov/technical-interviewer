"""Integration: full offline interview over the real WebSocket (DESIGN.md §12).

start -> greeting + background question -> answer -> next question ->
weak answer -> schema-valid score -> follow-up generated -> follow-up
answered -> next question -> hint_request honored -> pause/resume -> end ->
closing -> report_ready -> GET report with every ReportOut field present.

Uses the real mini-wiki FAISS fixture index (use_wiki=True), no network,
no API key, Claude CLI disabled.
"""
from __future__ import annotations

import pytest

from app.schemas import MetricScores, ReportOut

# Deliberately weak (but >=5 words, so not the short-answer path): near-zero
# expected-point coverage -> correctness <= 3 -> the offline decide_followup
# deterministically serves the question's bank follow-up (spec §13.4).
WEAK_ANSWER = (
    "Honestly I am not sure about this one, I would probably just guess and "
    "hope for the best."
)

SUBSTANTIVE_ANSWER = (
    "First, I would restate the problem and state my assumptions explicitly. "
    "The core approach is to start from the definition, walk through how the "
    "method works step by step, and quantify the behavior with a concrete "
    "metric. For example, in practice I would run an experiment, monitor the "
    "distribution of outcomes, and compare against a baseline with a clear "
    "hypothesis and a p-value threshold. However, there is a trade-off "
    "between speed and rigor that depends on the cost of errors, so I would "
    "also discuss the limitations and alternatives before recommending a "
    "final decision to stakeholders."
)

BACKGROUND_ANSWER = (
    "I have five years of relevant experience as a data scientist working on "
    "forecasting and experimentation platforms; my motivation for the role "
    "is to own modeling problems end to end, and the project I am most proud "
    "of cut forecast error by thirty percent for a clear business narrative."
)


def _recv_until(ws, msg_type, limit=25):
    """Receive messages until one of ``msg_type`` arrives; returns all seen."""
    seen = []
    for _ in range(limit):
        msg = ws.receive_json()
        seen.append(msg)
        if msg["type"] == msg_type:
            return seen
    raise AssertionError(
        "never received {0!r}; got {1}".format(msg_type, [m["type"] for m in seen])
    )


def _questions(msgs):
    return [m for m in msgs if m["type"] == "interviewer" and m["kind"] == "question"]


@pytest.mark.slow
def test_full_interview_flow(client, make_user, make_session, mini_wiki_index,
                             monkeypatch):
    monkeypatch.setenv("TI_WIKI_INDEX_DIR", mini_wiki_index)

    user = make_user(name="Flow Tester")
    sess = make_session(
        user_id=user["id"],
        role="Data Scientist",
        mode="Quick Practice",
        difficulty="Mid-level",
        duration_minutes=15,
        hint_policy="on_request",
        use_wiki=True,
        allow_internet=False,
        disable_cloud_ai=True,
    )
    sid = sess["id"]
    assert sess["status"] == "ready"
    assert sess["plan"]["sections"][0] == "background"

    with client.websocket_connect("/ws/interview/{0}".format(sid)) as ws:
        # ---- start: greeting then the background question, then state
        ws.send_json({"type": "start"})
        msgs = _recv_until(ws, "state")
        interviewer = [m for m in msgs if m["type"] == "interviewer"]
        assert interviewer[0]["kind"] == "greeting"
        assert interviewer[0]["text"].strip()
        background = _questions(msgs)[0]
        assert background["section"] == "background"
        assert background["question_id"]
        assert background["total_questions"] >= 2
        state = msgs[-1]
        assert state["status"] == "active"
        assert state["remaining_seconds"] > 0

        # ---- answer the background question -> score + next question
        ws.send_json({
            "type": "answer", "text": BACKGROUND_ANSWER,
            "duration_seconds": 42.5, "input_mode": "voice",
        })
        msgs = _recv_until(ws, "state")
        scores = [m for m in msgs if m["type"] == "score"]
        assert len(scores) == 1
        assert scores[0]["question_id"] == background["question_id"]
        MetricScores.model_validate(scores[0]["scores"])
        # moving into the first technical section announces the change
        assert any(m["type"] == "section_change" for m in msgs)
        q1 = _questions(msgs)[0]
        assert q1["question_id"] != background["question_id"]
        assert q1["section"] != "background"

        # ---- weak technical answer -> score, then a bank follow-up arrives
        #      BEFORE any next question (spec §13.4 "Generate follow-up")
        ws.send_json({
            "type": "answer", "text": WEAK_ANSWER,
            "duration_seconds": 12.0, "input_mode": "text",
        })
        msgs = _recv_until(ws, "state")
        score = next(m for m in msgs if m["type"] == "score")
        assert score["question_id"] == q1["question_id"]
        MetricScores.model_validate(score["scores"])
        followup = next(
            m for m in msgs
            if m["type"] == "interviewer" and m["kind"] == "followup"
        )
        assert followup["question_id"] == q1["question_id"]
        assert followup["text"].strip()
        assert not _questions(msgs), "follow-up must come before the next question"

        # ---- answer the follow-up -> schema-valid score, then next question
        ws.send_json({
            "type": "answer", "text": SUBSTANTIVE_ANSWER,
            "duration_seconds": 95.0, "input_mode": "text",
        })
        msgs = _recv_until(ws, "state")
        score = next(m for m in msgs if m["type"] == "score")
        assert score["question_id"] == q1["question_id"]
        metrics = MetricScores.model_validate(score["scores"])
        assert 1.0 <= score["overall"] <= 5.0
        assert score["overall"] > 1.0, "substantive answer beats the floor"
        assert metrics.communication >= 3
        assert isinstance(score["feedback"], str) and score["feedback"].strip()
        q2 = _questions(msgs)[0]
        assert q2["question_id"] not in (background["question_id"], q1["question_id"])

        # ---- hint_request honored (on_request policy)
        ws.send_json({"type": "hint_request"})
        hint = ws.receive_json()
        assert hint["type"] == "hint"
        assert hint["level"] == 1
        assert hint["hints_used"] == 1
        assert hint["question_id"] == q2["question_id"]
        assert hint["text"].strip()

        # ---- pause stops the clock, resume re-asks the open question
        ws.send_json({"type": "pause"})
        paused = ws.receive_json()
        assert paused["type"] == "state"
        assert paused["status"] == "paused"

        ws.send_json({"type": "resume"})
        msgs = _recv_until(ws, "interviewer")
        assert msgs[0]["type"] == "state"
        assert msgs[0]["status"] == "active"
        reasked = msgs[-1]
        assert reasked["kind"] == "question"
        assert reasked["question_id"] == q2["question_id"]

        # ---- end: closing + completed state, then background report_ready
        ws.send_json({"type": "end"})
        msgs = _recv_until(ws, "state")
        closing = next(m for m in msgs if m["type"] == "interviewer")
        assert closing["kind"] == "closing"
        assert closing["text"].strip()
        assert msgs[-1]["status"] == "completed"

        ready = _recv_until(ws, "report_ready", limit=5)[-1]
        assert ready["session_id"] == sid

    # ---- session status persisted
    resp = client.get("/api/sessions/{0}".format(sid))
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"
    assert resp.json()["overall_score"] is not None

    # ---- report: every ReportOut field present and valid
    resp = client.get("/api/sessions/{0}/report".format(sid))
    assert resp.status_code == 200
    data = resp.json()
    for field in ReportOut.model_fields:
        assert field in data, "report missing field {0}".format(field)
    report = ReportOut.model_validate(data)
    assert report.session_id == sid
    assert 0 <= report.overall_score <= 100
    assert report.questions_asked, "questions_asked non-empty"
    assert report.time_per_question, "time_per_question populated"
    answered_ids = {background["question_id"], q1["question_id"]}
    tpq_by_id = {t.question_id: t.seconds for t in report.time_per_question}
    assert answered_ids <= set(tpq_by_id)
    assert tpq_by_id[background["question_id"]] == pytest.approx(42.5)
    # q1 time = weak answer + follow-up answer durations
    assert tpq_by_id[q1["question_id"]] == pytest.approx(12.0 + 95.0)
    assert report.hints_used_total == 0, "hint was requested but never consumed by an answer"
    assert len(report.suggested_study_plan) >= 3
    assert report.recommended_next_interview is not None

    # ---- transcript autosaved throughout the interview
    resp = client.get("/api/sessions/{0}/transcript".format(sid))
    assert resp.status_code == 200
    entries = resp.json()["entries"]
    speakers = {e["speaker"] for e in entries}
    assert {"interviewer", "candidate"} <= speakers
    assert any(BACKGROUND_ANSWER[:40] in e["text"] for e in entries)


@pytest.mark.slow
def test_ws_reconnect_resumes_from_persisted_state(client, make_session,
                                                   mini_wiki_index, monkeypatch):
    monkeypatch.setenv("TI_WIKI_INDEX_DIR", mini_wiki_index)
    sess = make_session(duration_minutes=15, use_wiki=True)
    sid = sess["id"]

    with client.websocket_connect("/ws/interview/{0}".format(sid)) as ws:
        ws.send_json({"type": "start"})
        msgs = _recv_until(ws, "state")
        first_q = _questions(msgs)[0]
        ws.send_json({
            "type": "answer", "text": BACKGROUND_ANSWER,
            "duration_seconds": 20.0, "input_mode": "text",
        })
        msgs = _recv_until(ws, "state")
        open_q = _questions(msgs)[0]

    # drop the socket, reconnect: the open question is re-asked, not restarted
    with client.websocket_connect("/ws/interview/{0}".format(sid)) as ws:
        ws.send_json({"type": "start"})
        msgs = _recv_until(ws, "interviewer")
        reasked = msgs[-1]
        assert reasked["kind"] == "question"
        assert reasked["question_id"] == open_q["question_id"]
        assert reasked["question_id"] != first_q["question_id"]


def test_ws_unknown_session_rejected(client):
    with client.websocket_connect("/ws/interview/not-a-session") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "not found" in msg["message"]


def test_ws_invalid_json_reports_error(client, make_session):
    sess = make_session()
    with client.websocket_connect("/ws/interview/{0}".format(sess["id"])) as ws:
        ws.send_text("this is not json{")
        msg = ws.receive_json()
        assert msg["type"] == "error"
        ws.send_json({"type": "totally-unknown"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
