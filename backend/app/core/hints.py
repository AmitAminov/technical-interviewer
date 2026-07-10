"""Hint policy + 5 escalating levels (DESIGN.md §8, spec §7.4).

Levels: 1 small nudge, 2 conceptual direction, 3 structured outline,
4 partial answer, 5 full explanation. Levels 1-4 are served pre-answer on
request; level 5 is the full explanation and is only served AFTER the answer
is scored (spec §7.4), via :func:`full_explanation`. Hint text is generated
via the LLM provider when available, with a deterministic offline fallback
composed from the question's ``expected_points``. Each delivered hint
increments ``Answer.hints_used`` (persisted by the orchestrator), which feeds
the scoring penalty in :mod:`app.core.scoring`.
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

MAX_HINT_LEVEL = 5
#: Levels available before the answer is scored; level 5 (full explanation)
#: is held back until after scoring (spec §7.4).
MAX_PRE_ANSWER_HINT_LEVEL = 4

LEVEL_DESCRIPTIONS = {
    1: "a small nudge (one guiding question, no content given away)",
    2: "a conceptual direction (name the concept area to think about)",
    3: "a structured outline of the expected answer",
    4: "a partial answer covering roughly half of the expected points",
    5: "a full explanation of the expected answer",
}


def _points(question: Any) -> List[str]:
    pts = getattr(question, "expected_points", None) or []
    return [str(p) for p in pts]


def _topic(question: Any) -> str:
    return str(getattr(question, "topic", "") or "the topic")


def _is_he(language: str) -> bool:
    return (language or "en").lower().startswith("he")


def offline_hint(question: Any, level: int, language: str = "en") -> str:
    """Deterministic hint composed from expected_points (no LLM needed)."""
    pts = _points(question)
    topic = _topic(question)
    if _is_he(language):
        return _offline_hint_he(pts, topic, level)
    if not pts:
        fallbacks = {
            1: "Take a breath and restate the question in your own words — "
               "what is it really asking about {0}?".format(topic),
            2: "Think about the fundamentals of {0}: definitions first, then "
               "how the pieces interact.".format(topic),
            3: "Structure your answer as: (1) define the core concept, "
               "(2) explain how it works, (3) discuss trade-offs, "
               "(4) give an example.",
            4: "Start from the core definition in {0} and walk through how it "
               "works step by step; then contrast at least two alternatives "
               "and when you'd pick each.".format(topic),
            5: "A complete answer would define the concept precisely, explain "
               "the mechanism behind it, compare the main alternatives with "
               "their trade-offs, and close with a concrete example of using "
               "it in practice.",
        }
        return fallbacks[level]
    if level == 1:
        return "Here's a nudge: have you considered {0}?".format(pts[0].rstrip("."))
    if level == 2:
        themes = ", ".join(p.rstrip(".") for p in pts[:2])
        return (
            "Conceptually, this question is about {0}. Focus your thinking "
            "around: {1}.".format(topic, themes)
        )
    if level == 3:
        outline = "\n".join("- {0}".format(p) for p in pts)
        return "A strong answer would touch on these points:\n{0}".format(outline)
    if level == 4:
        half = max(1, (len(pts) + 1) // 2)
        expanded = "\n".join(
            "- {0} — explain this in your own words and why it matters.".format(
                p.rstrip(".")
            )
            for p in pts[:half]
        )
        return "Let me give you part of the answer:\n{0}\nNow try to complete the rest.".format(
            expanded
        )
    # level 5: full explanation
    full = "\n".join("- {0}".format(p) for p in pts)
    return (
        "Here is the full picture. A complete answer covers:\n{0}\n"
        "Walking through each of these, in order, forms the model answer for "
        "this {1} question.".format(full, topic)
    )


def _offline_hint_he(pts, topic: str, level: int) -> str:
    """Hebrew deterministic hint (expected_points are already Hebrew)."""
    if not pts:
        fallbacks = {
            1: "קח נשימה ונסח מחדש את השאלה במילים שלך — על מה היא באמת שואלת "
               "בנוגע ל{0}?".format(topic),
            2: "חשוב על היסודות של {0}: קודם הגדרות, ואז איך החלקים "
               "מתחברים.".format(topic),
            3: "בנה את התשובה כך: (1) הגדר את המושג המרכזי, (2) הסבר איך זה "
               "עובד, (3) דון ביתרונות וחסרונות, (4) תן דוגמה.",
            4: "התחל מההגדרה המרכזית של {0} ועבור שלב-שלב על אופן הפעולה; אז "
               "השווה לפחות שתי חלופות ומתי תבחר בכל אחת.".format(topic),
            5: "תשובה מלאה תגדיר את המושג במדויק, תסביר את המנגנון שמאחוריו, "
               "תשווה את החלופות המרכזיות עם היתרונות והחסרונות, ותסגור עם "
               "דוגמה קונקרטית לשימוש בפועל.",
        }
        return fallbacks[level]
    if level == 1:
        return "רמז קטן: האם חשבת על {0}?".format(pts[0].rstrip("."))
    if level == 2:
        themes = ", ".join(p.rstrip(".") for p in pts[:2])
        return "מבחינה מושגית, השאלה עוסקת ב{0}. מקד את החשיבה סביב: {1}.".format(topic, themes)
    if level == 3:
        outline = "\n".join("- {0}".format(p) for p in pts)
        return "תשובה טובה תיגע בנקודות הבאות:\n{0}".format(outline)
    if level == 4:
        half = max(1, (len(pts) + 1) // 2)
        expanded = "\n".join(
            "- {0} — הסבר זאת במילים שלך ולמה זה חשוב.".format(p.rstrip("."))
            for p in pts[:half]
        )
        return "הנה חלק מהתשובה:\n{0}\nעכשיו נסה להשלים את השאר.".format(expanded)
    full = "\n".join("- {0}".format(p) for p in pts)
    return (
        "הנה התמונה המלאה. תשובה שלמה כוללת:\n{0}\n"
        "מעבר על כל אחת מהנקודות האלה, לפי הסדר, מרכיב את התשובה המלאה "
        "לשאלה בנושא {1}.".format(full, topic)
    )


def next_hint(question: Any, hints_used: int, provider: Optional[Any] = None,
              language: str = "en") -> Tuple[int, str]:
    """Return ``(level, text)`` for the next hint on ``question``.

    ``hints_used`` is the number of hints already given for this question;
    the next hint level is ``hints_used + 1`` capped at 5. Uses the LLM
    provider when available; always has the deterministic offline fallback.
    """
    level = min(int(hints_used) + 1, MAX_HINT_LEVEL)
    return level, _hint_text(question, level, provider, language)


def full_explanation(question: Any, provider: Optional[Any] = None,
                     language: str = "en") -> str:
    """Level-5 hint text: the full explanation of the expected answer.

    Served by the orchestrator only after the answer has been scored
    (spec §7.4). Provider-optional like the other levels, with the same
    deterministic ``expected_points``-based offline fallback.
    """
    return _hint_text(question, MAX_HINT_LEVEL, provider, language)


def _hint_text(question: Any, level: int, provider: Optional[Any] = None,
               language: str = "en") -> str:
    """Hint text for ``level``, via the provider with an offline fallback."""
    fallback = offline_hint(question, level, language)
    # When only the deterministic offline provider is available, our
    # expected_points-derived hint is strictly more specific than a canned
    # template — use it directly.
    if provider is None or getattr(provider, "name", "offline") == "offline":
        return fallback
    try:
        q_text = str(getattr(question, "question_text", ""))
        pts = _points(question)
        prompt = (
            "Interview question: {q}\n"
            "Expected answer points: {pts}\n"
            "Give the candidate hint level {lvl} of 5: {desc}. "
            "Reply with the hint text only, 1-4 sentences, supportive tone. "
            "Do not reveal more than the level allows.{he}".format(
                q=q_text,
                pts="; ".join(pts) if pts else "(none listed)",
                lvl=level,
                desc=LEVEL_DESCRIPTIONS[level],
                he=" Write the hint in fluent modern Hebrew (עברית)." if _is_he(language) else "",
            )
        )
        text = provider.complete_text(
            system="You are a technical interviewer giving calibrated hints.",
            prompt=prompt,
            max_tokens=300,
        )
        text = (text or "").strip()
        if text:
            return text
    except Exception:
        logger.exception("LLM hint generation failed; using offline fallback")
    return fallback
