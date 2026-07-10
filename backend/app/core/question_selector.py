"""Question-bank filtering & no-duplicate selection (DESIGN.md §7).

Deterministic: selection preserves bank order so plans and tests are stable
offline. Falls back to adjacent difficulties when the exact difficulty is
starved, widening one step at a time.
"""
from __future__ import annotations

import uuid
from typing import Iterable, List, Optional, Set

from ..schemas import DIFFICULTIES, QuestionBankItem


def _difficulty_ring(difficulty: str) -> List[List[str]]:
    """Difficulty preference tiers: exact first, then ±1 step, ±2 steps, ...

    Unknown difficulty strings get a single tier containing every difficulty.
    """
    if difficulty not in DIFFICULTIES:
        return [[difficulty], list(DIFFICULTIES)]
    idx = DIFFICULTIES.index(difficulty)
    tiers: List[List[str]] = [[difficulty]]
    for step in range(1, len(DIFFICULTIES)):
        tier = []
        if idx - step >= 0:
            tier.append(DIFFICULTIES[idx - step])
        if idx + step < len(DIFFICULTIES):
            tier.append(DIFFICULTIES[idx + step])
        if tier:
            tiers.append(tier)
    return tiers


def select_questions(
    bank: List[QuestionBankItem],
    role: str,
    difficulty: str,
    topics: Optional[Iterable[str]],
    n: int,
    exclude_ids: Optional[Iterable[str]] = None,
) -> List[QuestionBankItem]:
    """Select up to ``n`` questions for ``role`` at ``difficulty``.

    - Exact role match always required.
    - ``topics``: restrict to these topics when provided (empty/None = any).
    - Never returns an id in ``exclude_ids`` and never duplicates within the
      returned list (no repeats within a session — callers accumulate
      exclude_ids across sections).
    - Falls back to adjacent difficulty tiers when starved.
    """
    if n <= 0:
        return []
    excluded: Set[str] = set(exclude_ids or [])
    topic_set = set(topics) if topics else None

    def matches(item: QuestionBankItem) -> bool:
        if item.role != role or item.id in excluded:
            return False
        if topic_set is not None and item.topic not in topic_set:
            return False
        return True

    selected: List[QuestionBankItem] = []
    for tier in _difficulty_ring(difficulty):
        if len(selected) >= n:
            break
        for item in bank:
            if len(selected) >= n:
                break
            if item.difficulty in tier and matches(item):
                selected.append(item)
                excluded.add(item.id)
    return selected


def generate_fallback_item(
    role: str, topic: str, difficulty: str, language: str = "en"
) -> QuestionBankItem:
    """Deterministic generated question used when the bank is starved.

    Guarantees the app still runs end-to-end offline with an empty/missing
    question bank. Emits Hebrew text for Hebrew sessions.
    """
    is_he = (language or "en").lower().startswith("he")
    if is_he:
        return QuestionBankItem(
            id="gen-" + uuid.uuid4().hex[:12],
            role=role,  # type: ignore[arg-type]
            topic=topic,
            difficulty=difficulty,  # type: ignore[arg-type]
            question_text=(
                "הסבר את הרעיונות המרכזיים של {t} כפי שהם רלוונטיים לתפקיד {r}: "
                "אילו בעיות זה פותר, איך זה עובד, ואילו שיקולים או מלכודות כדאי "
                "למתרגל לשים לב אליהם?".format(t=topic, r=role)
            ),
            expected_points=[
                "הגדרה מרכזית של {0}".format(topic),
                "איך זה עובד / הטכניקות המרכזיות",
                "שיקולי יתרונות/חסרונות ומלכודות בפועל",
                "דוגמה קונקרטית",
            ],
            followups=["תוכל לתת דוגמה קונקרטית מהניסיון שלך?"],
            is_behavioral=False,
            source="generated",
        )
    return QuestionBankItem(
        id="gen-" + uuid.uuid4().hex[:12],
        role=role,  # type: ignore[arg-type]
        topic=topic,
        difficulty=difficulty,  # type: ignore[arg-type]
        question_text=(
            "Explain the key ideas of {t} as they apply to the {r} role: what "
            "problems does it solve, how does it work, and what trade-offs or "
            "pitfalls should a practitioner watch out for?".format(t=topic, r=role)
        ),
        expected_points=[
            "core definition of {0}".format(topic),
            "how it works / main techniques",
            "practical trade-offs and pitfalls",
            "a concrete example",
        ],
        followups=["Can you give a concrete example from your own experience?"],
        is_behavioral=False,
        source="generated",
    )
