"""Unit tests: report generation — all §8 fields present, recoverable."""
from __future__ import annotations

import pytest

from app.core import report_generator
from app.schemas import ReportOut


def test_report_has_every_field(db, completed_session):
    sid = completed_session()
    report = report_generator.generate_report(db, sid)
    assert isinstance(report, ReportOut)
    assert report.session_id == sid
    assert 0 <= report.overall_score <= 100
    assert 0 <= report.role_readiness <= 100
    assert report.topic_scores, "per-topic scores populated"
    assert report.best_answers and report.weakest_answers
    for hl in report.best_answers + report.weakest_answers:
        assert hl.question and hl.why
        assert 1.0 <= hl.score <= 5.0
    assert report.communication_feedback.strip()
    assert report.technical_feedback.strip()
    assert len(report.suggested_study_plan) >= 3
    assert report.recommended_next_interview is not None
    assert report.recommended_next_interview.role == "Data Scientist"
    assert report.questions_asked, "questions_asked non-empty"
    assert report.transcript_summary.strip()
    assert report.hints_used_total >= 0
    assert report.time_per_question, "time_per_question populated"
    for tpq in report.time_per_question:
        assert tpq.question_id and tpq.question_text
        assert tpq.seconds >= 0.0
    assert report.created_at is not None


def test_report_persisted_encrypted_and_loadable(db, completed_session):
    from app.models import Report
    from app.security.crypto import decrypt_text

    sid = completed_session()
    report = report_generator.generate_report(db, sid)
    row = db.query(Report).filter(Report.session_id == sid).one()
    assert row.generation_failed is False
    assert row.content_enc
    # encrypted at rest: ciphertext does not contain the plaintext summary
    assert report.transcript_summary[:30] not in row.content_enc
    assert decrypt_text(row.content_enc)
    loaded = report_generator.load_report(db, sid)
    assert loaded is not None
    assert loaded.overall_score == report.overall_score


def test_report_endpoint_404_before_generation(client, make_session):
    sess = make_session()
    resp = client.get("/api/sessions/{0}/report".format(sess["id"]))
    assert resp.status_code == 404
    assert "not ready" in resp.json()["detail"]


def test_report_endpoint_after_generation(client, db, completed_session):
    sid = completed_session()
    report_generator.generate_report(db, sid)
    resp = client.get("/api/sessions/{0}/report".format(sid))
    assert resp.status_code == 200
    ReportOut.model_validate(resp.json())


def test_regenerate_recovers_failed_generation(client, db, completed_session, monkeypatch):
    sid = completed_session()

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated narrative failure")

    monkeypatch.setattr(report_generator, "build_report", _boom)
    with pytest.raises(RuntimeError):
        report_generator.generate_report(db, sid)
    assert report_generator.report_status(db, sid) == "failed"
    # GET reports the failure (500 with recovery instructions), not "not ready".
    resp = client.get("/api/sessions/{0}/report".format(sid))
    assert resp.status_code == 500
    monkeypatch.undo()

    resp = client.post("/api/sessions/{0}/report/regenerate".format(sid))
    assert resp.status_code == 200
    report = ReportOut.model_validate(resp.json())
    assert report.session_id == sid
    assert report_generator.report_status(db, sid) == "ready"


def test_regenerate_unknown_session_404(client):
    resp = client.post("/api/sessions/nope/report/regenerate")
    assert resp.status_code == 404


def test_overall_score_is_mean_overall_times_20(db, completed_session):
    from app.models import Answer, Question, Score

    sid = completed_session()
    report = report_generator.generate_report(db, sid)
    overalls = [
        float(s.overall)
        for s in db.query(Score)
        .join(Answer, Score.answer_id == Answer.id)
        .join(Question, Answer.question_id == Question.id)
        .filter(Question.session_id == sid)
        .all()
    ]
    assert overalls
    expected = int(round(sum(overalls) / len(overalls) * 20))
    assert report.overall_score == max(0, min(100, expected))


def test_role_readiness_difficulty_modifier(db, completed_session):
    sid = completed_session(difficulty="Staff/Lead-level")
    report = report_generator.generate_report(db, sid)
    assert report.role_readiness == int(round(report.overall_score * 0.9))
