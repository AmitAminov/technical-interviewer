"""ORM models per DESIGN.md §5 (spec §11 superset).

All primary keys are String(36) uuid4 strings. `*_enc` columns hold
Fernet-encrypted text (see app.security.crypto).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from .database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=_uuid)
    name = Column(String(200), nullable=False)
    target_roles = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    sessions = relationship(
        "InterviewSession", back_populates="user", cascade="all, delete-orphan"
    )


class InterviewSession(Base):
    __tablename__ = "interview_sessions"

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    role = Column(String(64), nullable=False)
    mode = Column(String(64), nullable=False)
    difficulty = Column(String(64), nullable=False)
    duration_minutes = Column(Integer, nullable=False)
    language = Column(String(16), nullable=False, default="en")
    hint_policy = Column(String(32), nullable=False, default="on_request")
    interviewer_style = Column(String(64), nullable=False, default="Friendly")
    use_resume = Column(Boolean, nullable=False, default=False)
    use_job_description = Column(Boolean, nullable=False, default=False)
    use_wiki = Column(Boolean, nullable=False, default=True)
    allow_internet = Column(Boolean, nullable=False, default=False)
    record_session = Column(Boolean, nullable=False, default=False)
    disable_cloud_ai = Column(Boolean, nullable=False, default=False)
    resume_text_enc = Column(Text, nullable=True)
    job_description_enc = Column(Text, nullable=True)
    plan = Column(JSON, nullable=True)
    status = Column(String(32), nullable=False, default="created")
    overall_score = Column(Float, nullable=True)
    current_section_idx = Column(Integer, nullable=False, default=0)
    current_question_idx = Column(Integer, nullable=False, default=0)
    elapsed_seconds = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="sessions")
    questions = relationship(
        "Question",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="Question.order_idx",
    )
    transcript_entries = relationship(
        "TranscriptEntry",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="TranscriptEntry.ts",
    )
    citations = relationship(
        "SourceCitation", back_populates="session", cascade="all, delete-orphan"
    )
    report = relationship(
        "Report", back_populates="session", cascade="all, delete-orphan", uselist=False
    )


class Question(Base):
    __tablename__ = "questions"

    id = Column(String(36), primary_key=True, default=_uuid)
    session_id = Column(
        String(36), ForeignKey("interview_sessions.id"), nullable=False, index=True
    )
    topic = Column(String(128), nullable=False)
    difficulty = Column(String(64), nullable=False)
    question_text = Column(Text, nullable=False)
    source = Column(String(32), nullable=False, default="seed")
    expected_points = Column(JSON, nullable=False, default=list)
    section = Column(String(128), nullable=False)
    order_idx = Column(Integer, nullable=False, default=0)
    is_behavioral = Column(Boolean, nullable=False, default=False)
    asked_at = Column(DateTime, nullable=True)

    session = relationship("InterviewSession", back_populates="questions")
    answers = relationship(
        "Answer", back_populates="question", cascade="all, delete-orphan"
    )


class Answer(Base):
    __tablename__ = "answers"

    id = Column(String(36), primary_key=True, default=_uuid)
    question_id = Column(
        String(36), ForeignKey("questions.id"), nullable=False, index=True
    )
    transcript_enc = Column(Text, nullable=True)
    duration_seconds = Column(Float, nullable=False, default=0.0)
    hints_used = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    question = relationship("Question", back_populates="answers")
    score = relationship(
        "Score", back_populates="answer", cascade="all, delete-orphan", uselist=False
    )


class Score(Base):
    __tablename__ = "scores"

    id = Column(String(36), primary_key=True, default=_uuid)
    answer_id = Column(String(36), ForeignKey("answers.id"), nullable=False, index=True)
    correctness = Column(Integer, nullable=False)
    depth = Column(Integer, nullable=False)
    clarity = Column(Integer, nullable=False)
    structure = Column(Integer, nullable=False)
    practicality = Column(Integer, nullable=False)
    mathematical_rigor = Column(Integer, nullable=False)
    tradeoff_awareness = Column(Integer, nullable=False)
    communication = Column(Integer, nullable=False)
    overall = Column(Float, nullable=False)
    feedback = Column(Text, nullable=False, default="")

    answer = relationship("Answer", back_populates="score")


class TranscriptEntry(Base):
    __tablename__ = "transcript_entries"

    id = Column(String(36), primary_key=True, default=_uuid)
    session_id = Column(
        String(36), ForeignKey("interview_sessions.id"), nullable=False, index=True
    )
    ts = Column(DateTime, nullable=False, default=datetime.utcnow)
    speaker = Column(String(16), nullable=False)  # interviewer | candidate | system
    text_enc = Column(Text, nullable=False, default="")

    session = relationship("InterviewSession", back_populates="transcript_entries")


class SourceCitation(Base):
    __tablename__ = "source_citations"

    id = Column(String(36), primary_key=True, default=_uuid)
    session_id = Column(
        String(36), ForeignKey("interview_sessions.id"), nullable=True, index=True
    )
    url = Column(Text, nullable=False)
    title = Column(Text, nullable=False, default="")
    quality = Column(String(16), nullable=False, default="medium")  # high|medium|rejected
    fetched_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    notes = Column(Text, nullable=False, default="")

    session = relationship("InterviewSession", back_populates="citations")


class Report(Base):
    __tablename__ = "reports"

    id = Column(String(36), primary_key=True, default=_uuid)
    session_id = Column(
        String(36),
        ForeignKey("interview_sessions.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    content_enc = Column(Text, nullable=True)  # Fernet-encrypted ReportOut JSON
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    generation_failed = Column(Boolean, nullable=False, default=False)

    session = relationship("InterviewSession", back_populates="report")
