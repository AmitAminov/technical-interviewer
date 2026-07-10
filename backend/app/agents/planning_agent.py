"""Planning agent: builds the interview plan (spec §6.2, DESIGN.md §7).

``build_plan`` is fully deterministic offline: sections and question
allocation depend only on the session config, resume/JD topic matches, the
question bank order, and (when available) wiki coverage scores from the
retriever. The provider is consulted only as an optional refinement whose
output is validated before use.
"""
from __future__ import annotations

import re
from typing import Any, List, Optional, Sequence, Set, Tuple

from pydantic import BaseModel

from ..schemas import (
    DIFFICULTIES,
    TRACK_TOPICS,
    InterviewPlan,
    QuestionBankItem,
    SessionCreate,
)

BACKGROUND_SECTION = "background"
BEHAVIORAL_SECTION = "behavioral"
CANDIDATE_QUESTIONS_SECTION = "candidate questions"

_MINUTES_PER_TECH_QUESTION = 7.0  # one technical question per 6-8 minutes
_OVERHEAD_MINUTES = {
    "Quick Practice": 4.0,     # greeting + background + wrap-up
    "Standard": 10.0,          # + behavioral
    "Deep Research": 12.0,
}
_BEHAVIORAL_COUNT = {"Quick Practice": 0, "Standard": 2, "Deep Research": 3}

_STOPWORDS = frozenset(
    "the a an and or of to in for with on at by from as is are was were".split()
)


# ------------------------------------------------------------- topic matching
def _topic_tokens(topic: str) -> List[str]:
    return [t for t in re.findall(r"[a-z0-9/]+", topic.casefold())
            if len(t) >= 3 and t not in _STOPWORDS]


def _topic_in_text(topic: str, text_cf: str) -> bool:
    if topic.casefold() in text_cf:
        return True
    tokens = _topic_tokens(topic)
    return bool(tokens) and all(t in text_cf for t in tokens)


def _match_topics(text: Optional[str], role_topics: Sequence[str]) -> List[str]:
    """Role topics mentioned in free text (resume / job description)."""
    if not text:
        return []
    cf = text.casefold()
    return [t for t in role_topics if _topic_in_text(t, cf)]


def _canonical_focus(focus_topics: Sequence[str],
                     role_topics: Sequence[str]) -> List[str]:
    """Map free-form focus topics onto the role's canonical topic list."""
    out: List[str] = []
    for raw in focus_topics:
        raw_cf = (raw or "").casefold().strip()
        if not raw_cf:
            continue
        for topic in role_topics:
            if topic in out:
                continue
            if topic.casefold() == raw_cf or _topic_in_text(topic, raw_cf) \
                    or _topic_in_text(raw, topic.casefold()):
                out.append(topic)
                break
    return out


def _wiki_coverage_order(topics: List[str], retriever: Any) -> List[str]:
    """Stable-sort topics by wiki coverage (top-1 similarity), best first."""
    if retriever is None or not getattr(retriever, "loaded", False):
        return topics
    scored: List[Tuple[float, int, str]] = []
    for i, topic in enumerate(topics):
        score = 0.0
        try:
            hits = retriever.search(topic, k=1)
            if hits:
                score = float(hits[0].score)
        except Exception:
            score = 0.0
        scored.append((-score, i, topic))
    scored.sort()
    return [t for _, _, t in scored]


# ---------------------------------------------------------- question picking
def _difficulty_ladder(difficulty: str) -> List[str]:
    """Requested difficulty first, then adjacent levels by distance."""
    if difficulty not in DIFFICULTIES:
        return list(DIFFICULTIES)
    idx = DIFFICULTIES.index(difficulty)
    ladder = [difficulty]
    for dist in range(1, len(DIFFICULTIES)):
        for j in (idx - dist, idx + dist):
            if 0 <= j < len(DIFFICULTIES):
                ladder.append(DIFFICULTIES[j])
    return ladder


def _pick_technical(bank: Sequence[QuestionBankItem], role: str, topic: str,
                    difficulty: str, n: int,
                    used: Set[str]) -> List[QuestionBankItem]:
    picked: List[QuestionBankItem] = []
    for diff in _difficulty_ladder(difficulty):
        for item in bank:
            if len(picked) >= n:
                return picked
            if item.id in used or item.is_behavioral:
                continue
            if item.role == role and item.topic == topic and item.difficulty == diff:
                picked.append(item)
                used.add(item.id)
    return picked


def _pick_behavioral(bank: Sequence[QuestionBankItem], role: str,
                     difficulty: str, n: int,
                     used: Set[str]) -> List[QuestionBankItem]:
    picked: List[QuestionBankItem] = []
    for diff in _difficulty_ladder(difficulty):
        for item in bank:
            if len(picked) >= n:
                return picked
            if item.id in used or not item.is_behavioral:
                continue
            if item.role == role and item.difficulty == diff:
                picked.append(item)
                used.add(item.id)
    return picked


# ------------------------------------------------------- provider refinement
class _SectionOrder(BaseModel):
    sections: List[str] = []


def _refine_order_with_provider(tech_topics: List[str], cfg: SessionCreate,
                                provider: Any) -> List[str]:
    """Optionally let the LLM reorder technical sections; validated strictly."""
    if provider is None or getattr(provider, "name", "offline") == "offline":
        return tech_topics
    if len(tech_topics) < 3:
        return tech_topics
    try:
        result = provider.complete_json(
            "You are an interview planning agent.",
            "Order these technical interview sections for a %s %s interview "
            "at %s difficulty so the interview flows from fundamentals to "
            "advanced/system topics. Return the same section names, no "
            "additions or removals.\nSections: %s"
            % (cfg.role, cfg.mode, cfg.difficulty, ", ".join(tech_topics)),
            _SectionOrder,
            timeout=15.0,
        )
        if sorted(result.sections) == sorted(tech_topics):
            return list(result.sections)
    except Exception:
        pass
    return tech_topics


# -------------------------------------------------------------------- pinned
def build_plan(cfg: SessionCreate, resume_text: Optional[str],
               jd_text: Optional[str], retriever,
               bank: List[QuestionBankItem], provider) -> InterviewPlan:
    """Build the interview plan (pinned interface, DESIGN.md §7).

    Always starts with "background" and ends with "candidate questions".
    Standard/Deep Research include a "behavioral" section. Technical section
    count and question count scale with mode and duration; Deep Research
    prioritizes resume/JD-derived topics.
    """
    role = cfg.role
    role_topics = list(TRACK_TOPICS.get(role, []))
    duration = float(cfg.duration_minutes)

    focus = _canonical_focus(cfg.focus_topics or [], role_topics)
    # Resume/JD text is only used when the corresponding toggle is on.
    resume_topics = _match_topics(resume_text if cfg.use_resume else None,
                                  role_topics)
    jd_topics = _match_topics(jd_text if cfg.use_job_description else None,
                              role_topics)

    # Priority: explicit focus > resume/JD signals > remaining role topics
    # (remaining topics ranked by wiki coverage when the retriever is loaded).
    prioritized: List[str] = []
    for t in focus + jd_topics + resume_topics:
        if t not in prioritized:
            prioritized.append(t)
    remaining = [t for t in role_topics if t not in prioritized]
    remaining = _wiki_coverage_order(remaining, retriever)
    candidates = prioritized + remaining

    # Section counts by mode (spec §6.2 / DESIGN §7).
    if cfg.mode == "Quick Practice":
        n_tech = 2 if duration >= 15 else 1
    elif cfg.mode == "Standard":
        n_tech = 4 if duration >= 55 else 3
    else:  # Deep Research
        if duration >= 80:
            n_tech = 6
        elif duration >= 70:
            n_tech = 5
        else:
            n_tech = 4
    tech_topics = candidates[:n_tech]
    tech_topics = _refine_order_with_provider(tech_topics, cfg, provider)

    include_behavioral = cfg.mode in ("Standard", "Deep Research")
    sections: List[str] = [BACKGROUND_SECTION]
    if include_behavioral:
        sections.append(BEHAVIORAL_SECTION)
    sections.extend(tech_topics)
    sections.append(CANDIDATE_QUESTIONS_SECTION)

    # Question budget: ~one technical question per 6-8 minutes of remaining
    # time after fixed overhead; at least one per technical section.
    overhead = _OVERHEAD_MINUTES.get(cfg.mode, 10.0)
    total_tech = int(round(max(0.0, duration - overhead) / _MINUTES_PER_TECH_QUESTION))
    total_tech = max(len(tech_topics), total_tech)
    total_tech = min(total_tech, 4 * max(1, len(tech_topics)))

    section_questions = {BACKGROUND_SECTION: [],
                         CANDIDATE_QUESTIONS_SECTION: []}
    rubric_notes = {
        BACKGROUND_SECTION: [
            "Clear narrative of experience relevant to %s work" % role,
            "Concrete project with the candidate's own contribution and impact",
        ],
        CANDIDATE_QUESTIONS_SECTION: [
            "Asks informed questions about the team, stack, or expectations",
        ],
    }

    used: Set[str] = set()
    if include_behavioral:
        behavioral_items = _pick_behavioral(
            bank, role, cfg.difficulty, _BEHAVIORAL_COUNT.get(cfg.mode, 2), used)
        section_questions[BEHAVIORAL_SECTION] = [q.id for q in behavioral_items]
        notes: List[str] = []
        for q in behavioral_items:
            notes.extend(q.expected_points)
        rubric_notes[BEHAVIORAL_SECTION] = notes[:10] or [
            "Specific situation, actions taken, measurable outcome (STAR)",
        ]

    # Distribute the technical budget across sections (front-loaded remainder).
    n_sections = max(1, len(tech_topics))
    base, extra = divmod(total_tech, n_sections)
    for i, topic in enumerate(tech_topics):
        want = base + (1 if i < extra else 0)
        items = _pick_technical(bank, role, topic, cfg.difficulty,
                                max(1, want), used)
        section_questions[topic] = [q.id for q in items]
        notes = []
        for q in items:
            notes.extend(q.expected_points)
        rubric_notes[topic] = notes[:10]

    return InterviewPlan(
        role=role,
        duration_minutes=cfg.duration_minutes,
        sections=sections,
        difficulty=cfg.difficulty,
        section_questions=section_questions,
        focus_topics=tech_topics,
        rubric_notes=rubric_notes,
    )
