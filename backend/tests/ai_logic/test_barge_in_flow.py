"""_on_barge_in: emits an adaptive reply when barge_in_reply returns text,
and only a state ack when it returns empty; persists the interjection."""
from __future__ import annotations


def test_barge_in_emits_reply(db, make_session, monkeypatch):
    from app.core.orchestrator import InterviewOrchestrator
    import app.llm.interviewer as interviewer

    monkeypatch.setattr(interviewer, "barge_in_reply",
                        lambda **kw: "Of course — let me restate that.")
    sess = make_session()
    orch = InterviewOrchestrator(sess["id"])
    orch.handle(db, {"type": "start"})
    msgs = orch.handle(db, {"type": "barge_in", "text": "wait can you repeat that"})
    replies = [m for m in msgs if m["type"] == "interviewer" and m["kind"] == "reply"]
    assert len(replies) == 1
    assert replies[0]["text"] == "Of course — let me restate that."
    assert any(m["type"] == "state" for m in msgs)


def test_barge_in_empty_reply_is_state_only(db, make_session, monkeypatch):
    from app.core.orchestrator import InterviewOrchestrator
    import app.llm.interviewer as interviewer

    monkeypatch.setattr(interviewer, "barge_in_reply", lambda **kw: "")
    sess = make_session()
    orch = InterviewOrchestrator(sess["id"])
    orch.handle(db, {"type": "start"})
    msgs = orch.handle(db, {"type": "barge_in", "text": "so I would start by"})
    assert not any(m["type"] == "interviewer" for m in msgs)
    assert any(m["type"] == "state" for m in msgs)
