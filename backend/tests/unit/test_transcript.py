"""Unit tests: transcript autosave rows + Fernet encryption at rest."""
from __future__ import annotations

from sqlalchemy import text as sql_text

from app.core import transcript as transcript_store
from app.core.orchestrator import InterviewOrchestrator
from app.models import TranscriptEntry


SECRET_LINE = "The quick brown candidate spoke about eigenvalues."


def test_add_entry_encrypts_at_rest(db, make_session):
    sess = make_session()
    entry = transcript_store.add_entry(db, sess["id"], "candidate", SECRET_LINE)
    row = db.get(TranscriptEntry, entry.id)
    # raw DB column is ciphertext, not the plaintext
    assert row.text_enc
    assert SECRET_LINE not in row.text_enc
    assert row.text_enc != SECRET_LINE
    # and the raw SQL view of the column agrees (true at-rest check)
    raw = db.execute(
        sql_text("SELECT text_enc FROM transcript_entries WHERE id = :id"),
        {"id": entry.id},
    ).scalar()
    assert SECRET_LINE not in (raw or "")
    # decrypted view round-trips
    out = transcript_store.get_transcript(db, sess["id"])
    assert [e.text for e in out.entries] == [SECRET_LINE]
    assert out.entries[0].speaker == "candidate"


def test_orchestrator_autosaves_every_line(db, make_session):
    sess = make_session()
    orch = InterviewOrchestrator(sess["id"])
    orch.handle(db, {"type": "start"})
    rows = (
        db.query(TranscriptEntry)
        .filter(TranscriptEntry.session_id == sess["id"])
        .all()
    )
    # greeting + first question autosaved as interviewer lines
    assert sum(1 for r in rows if r.speaker == "interviewer") >= 2

    orch.handle(
        db,
        {"type": "answer", "text": SECRET_LINE, "duration_seconds": 12.0,
         "input_mode": "text"},
    )
    out = transcript_store.get_transcript(db, sess["id"])
    speakers = [e.speaker for e in out.entries]
    assert "candidate" in speakers
    assert SECRET_LINE in [e.text for e in out.entries]


def test_partial_transcript_upserted_then_finalized(db, make_session):
    sess = make_session()
    orch = InterviewOrchestrator(sess["id"])
    orch.handle(db, {"type": "start"})
    orch.handle(db, {"type": "partial_transcript", "text": "The quick"})
    orch.handle(db, {"type": "partial_transcript", "text": "The quick brown"})
    orch.handle(
        db,
        {"type": "answer", "text": SECRET_LINE, "duration_seconds": 3.0,
         "input_mode": "voice"},
    )
    out = transcript_store.get_transcript(db, sess["id"])
    candidate_lines = [e.text for e in out.entries if e.speaker == "candidate"]
    # partials collapse into ONE finalized candidate line, not three
    assert candidate_lines == [SECRET_LINE]


def test_answer_transcript_encrypted_at_rest(db, make_session):
    from app.models import Answer, Question

    sess = make_session()
    orch = InterviewOrchestrator(sess["id"])
    orch.handle(db, {"type": "start"})
    orch.handle(
        db,
        {"type": "answer", "text": SECRET_LINE, "duration_seconds": 5.0,
         "input_mode": "text"},
    )
    answer = (
        db.query(Answer)
        .join(Question, Answer.question_id == Question.id)
        .filter(Question.session_id == sess["id"])
        .one()
    )
    assert answer.transcript_enc
    assert SECRET_LINE not in answer.transcript_enc


def test_transcript_endpoint_and_privacy_delete(client, db, make_session):
    sess = make_session()
    transcript_store.add_entry(db, sess["id"], "interviewer", "Welcome!")
    transcript_store.add_entry(db, sess["id"], "candidate", SECRET_LINE)

    resp = client.get("/api/sessions/{0}/transcript".format(sess["id"]))
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == sess["id"]
    assert len(body["entries"]) == 2
    assert body["entries"][1]["text"] == SECRET_LINE

    resp = client.delete("/api/sessions/{0}/transcript".format(sess["id"]))
    assert resp.status_code == 200
    assert resp.json()["entries_removed"] == 2
    resp = client.get("/api/sessions/{0}/transcript".format(sess["id"]))
    assert resp.json()["entries"] == []


def test_crypto_roundtrip_and_none_passthrough():
    from app.security.crypto import decrypt_text, encrypt_text

    assert encrypt_text(None) is None
    assert decrypt_text(None) is None
    token = encrypt_text("hello world")
    assert token != "hello world"
    assert decrypt_text(token) == "hello world"
    # corrupt ciphertext degrades to empty string, never raises
    assert decrypt_text("garbage-token") == ""
