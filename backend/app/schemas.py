"""Pinned shared schemas — single source of truth for API/WS/agent payloads.

This file is part of the architecture contract (DESIGN.md). Extend cautiously;
do not rename fields.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

Role = Literal["Data Scientist", "Algorithm Researcher", "AI Engineer"]
Mode = Literal["Quick Practice", "Standard", "Deep Research"]
Difficulty = Literal["Junior", "Mid-level", "Senior", "Research-level", "Staff/Lead-level"]
HintPolicy = Literal["none", "on_request", "adaptive"]
InterviewerStyle = Literal[
    "Friendly", "Strict", "Research professor", "Startup CTO", "Big-tech interviewer"
]
QuestionSource = Literal["local_wiki", "internet", "generated", "seed"]
SessionStatus = Literal[
    "created", "planning", "ready", "active", "paused", "completed", "cancelled"
]

ROLES: List[str] = ["Data Scientist", "Algorithm Researcher", "AI Engineer"]
MODES: List[str] = ["Quick Practice", "Standard", "Deep Research"]
DIFFICULTIES: List[str] = [
    "Junior", "Mid-level", "Senior", "Research-level", "Staff/Lead-level"
]
MODE_DURATION_RANGES: Dict[str, tuple] = {
    "Quick Practice": (10, 20),
    "Standard": (45, 60),
    "Deep Research": (60, 90),
}
TRACK_TOPICS: Dict[str, List[str]] = {
    "Data Scientist": [
        "Python", "SQL", "Statistics", "Probability", "A/B testing",
        "Experiment design", "Feature engineering", "Supervised learning",
        "Unsupervised learning", "Model evaluation", "Business case reasoning",
        "Data cleaning", "Communication of insights",
    ],
    "Algorithm Researcher": [
        "Algorithms", "Data structures", "Complexity analysis", "Probability",
        "Optimization", "Graph algorithms", "Dynamic programming",
        "Mathematical proofs", "Research paper understanding",
        "Experimental design", "Benchmarking",
    ],
    "AI Engineer": [
        "Deep learning", "Transformers", "LLMs", "RAG", "Embeddings",
        "Fine-tuning", "Evaluation", "Agents", "MLOps", "Model serving",
        "Latency optimization", "Distributed training", "GPU memory",
        "Safety and monitoring",
    ],
}


# ---------------------------------------------------------------- users
class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    target_roles: List[Role] = []


class UserOut(BaseModel):
    id: str
    name: str
    target_roles: List[str]
    created_at: datetime


# ---------------------------------------------------------------- sessions
class SessionCreate(BaseModel):
    user_id: str
    role: Role
    mode: Mode
    difficulty: Difficulty
    duration_minutes: int = Field(ge=5, le=120)
    language: str = "en"
    hint_policy: HintPolicy = "on_request"
    interviewer_style: InterviewerStyle = "Friendly"
    use_resume: bool = False
    use_job_description: bool = False
    use_wiki: bool = True
    allow_internet: bool = False
    record_session: bool = False
    disable_cloud_ai: bool = False
    resume_text: Optional[str] = None
    job_description: Optional[str] = None
    focus_topics: List[str] = []


class InterviewPlan(BaseModel):
    """Spec §6.2 output shape plus per-section question allocation."""

    role: str
    duration_minutes: int
    sections: List[str]
    difficulty: str
    # section name -> ordered list of question-bank/generated question ids
    section_questions: Dict[str, List[str]] = {}
    focus_topics: List[str] = []
    rubric_notes: Dict[str, List[str]] = {}


class SessionOut(BaseModel):
    id: str
    user_id: str
    role: str
    mode: str
    difficulty: str
    duration_minutes: int
    language: str
    hint_policy: str
    interviewer_style: str
    use_resume: bool
    use_job_description: bool
    use_wiki: bool
    allow_internet: bool
    record_session: bool
    disable_cloud_ai: bool
    status: str
    overall_score: Optional[float] = None
    plan: Optional[InterviewPlan] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


# ---------------------------------------------------------------- questions & scoring
class QuestionBankItem(BaseModel):
    id: str
    role: Role
    topic: str
    difficulty: Difficulty
    question_text: str
    expected_points: List[str] = []
    followups: List[str] = []
    is_behavioral: bool = False
    source: QuestionSource = "seed"
    # Pre-translated Hebrew fields (populated for the seed bank) so Hebrew
    # interviews run fully offline without a live translation call.
    question_text_he: str = ""
    expected_points_he: List[str] = []
    followups_he: List[str] = []


class QuestionOut(BaseModel):
    id: str
    session_id: str
    topic: str
    difficulty: str
    question_text: str
    source: str
    expected_points: List[str]
    section: str
    order_idx: int
    is_behavioral: bool = False


class MetricScores(BaseModel):
    correctness: int = Field(ge=1, le=5)
    depth: int = Field(ge=1, le=5)
    clarity: int = Field(ge=1, le=5)
    structure: int = Field(ge=1, le=5)
    practicality: int = Field(ge=1, le=5)
    mathematical_rigor: int = Field(ge=1, le=5)
    tradeoff_awareness: int = Field(ge=1, le=5)
    communication: int = Field(ge=1, le=5)


class ScoreOut(BaseModel):
    id: str
    answer_id: str
    correctness: int
    depth: int
    clarity: int
    structure: int
    practicality: int
    mathematical_rigor: int
    tradeoff_awareness: int
    communication: int
    overall: float
    feedback: str


# ---------------------------------------------------------------- transcript & rag
class TranscriptEntryOut(BaseModel):
    id: str
    session_id: str
    ts: datetime
    speaker: Literal["interviewer", "candidate", "system"]
    text: str


class TranscriptOut(BaseModel):
    session_id: str
    entries: List[TranscriptEntryOut]


class RagResult(BaseModel):
    text: str
    source: str  # wiki page name, e.g. "concepts/backpropagation.md"
    score: float


class SourceCitationOut(BaseModel):
    id: str
    session_id: Optional[str] = None
    url: str
    title: str
    quality: Literal["high", "medium", "rejected"]
    fetched_at: datetime
    notes: str = ""


# ---------------------------------------------------------------- report
class AnswerHighlight(BaseModel):
    question: str
    score: float
    why: str


class NextInterviewRec(BaseModel):
    role: str
    mode: str
    difficulty: str
    focus_topics: List[str] = []


class TimePerQuestion(BaseModel):
    question_id: str
    question_text: str
    seconds: float


class ReportOut(BaseModel):
    session_id: str
    overall_score: int = Field(ge=0, le=100)
    role_readiness: int = Field(ge=0, le=100)
    topic_scores: Dict[str, float] = {}
    best_answers: List[AnswerHighlight] = []
    weakest_answers: List[AnswerHighlight] = []
    missing_concepts: List[str] = []
    communication_feedback: str = ""
    technical_feedback: str = ""
    suggested_study_plan: List[str] = []
    recommended_next_interview: Optional[NextInterviewRec] = None
    questions_asked: List[str] = []
    transcript_summary: str = ""
    hints_used_total: int = 0
    time_per_question: List[TimePerQuestion] = []
    created_at: Optional[datetime] = None


# ---------------------------------------------------------------- progress & curriculum
class ProgressSessionOut(BaseModel):
    """One completed session in a user's cross-session history."""

    id: str
    created_at: datetime
    role: str
    mode: str
    difficulty: str
    overall_score: Optional[float] = None  # 0-100
    role_readiness: Optional[int] = None  # 0-100


class TrendPoint(BaseModel):
    """One point on a per-session trend line.

    ``score`` is an int 0-100 on the readiness trend and a float 0-5
    (mean per-answer overall) on topic trends; the union keeps readiness
    points serializing as integers.
    """

    session_id: str
    created_at: datetime
    score: Union[int, float]


class CurriculumItem(BaseModel):
    """One personalized study recommendation (spec §16)."""

    title: str
    reason: str
    wiki_refs: List[str] = []
    priority: int = Field(ge=1, le=3)  # 1=now, 2=next, 3=later
    source_sessions: List[str] = []


class ProgressOut(BaseModel):
    """Cross-session progress + personalized study curriculum (spec §16)."""

    user_id: str
    sessions: List[ProgressSessionOut] = []
    readiness_trend: List[TrendPoint] = []
    topic_trends: Dict[str, List[TrendPoint]] = {}
    current_weak_topics: List[str] = []
    current_strong_topics: List[str] = []
    curriculum: List[CurriculumItem] = []


# ---------------------------------------------------------------- qa agent
class QAReport(BaseModel):
    status: Literal["PASS", "FAIL"]
    critical_issues: List[str] = []
    missing_tests: List[str] = []
    latency_problems: List[str] = []
    security_concerns: List[str] = []
    recommended_fixes: List[str] = []
    details: str = ""
