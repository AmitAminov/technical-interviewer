"""Hebrew interview language (DESIGN.md §2): interviewer + scorer text.

The LLM path is instructed to reply in Hebrew via a directive; fully offline,
the persona lines fall back to Hebrew templates. English stays the default.
"""
from __future__ import annotations

from app.llm.interviewer import (
    background_question,
    checkin_after_silence,
    closing,
    greeting,
)


def _has_hebrew(text: str) -> bool:
    return any("֐" <= ch <= "׿" for ch in text)


def _has_english_words(text: str) -> bool:
    import re
    # a run of >=4 latin letters that is not an allowed tech term
    allowed = {"python", "sql", "rag", "llm", "gpu", "data", "scientist"}
    for w in re.findall(r"[A-Za-z]{4,}", text):
        if w.lower() not in allowed:
            return True
    return False


def test_greeting_hebrew_offline_fallback(offline_provider):
    out = greeting("Friendly", "Data Scientist", "Amit", offline_provider, "he")
    assert _has_hebrew(out), out


def test_hints_hebrew_offline():
    from types import SimpleNamespace

    from app.core.hints import full_explanation, next_hint

    q = SimpleNamespace(
        question_text="הסבר p-value", topic="Statistics",
        expected_points=["הסתברות לנתונים תחת השערת האפס", "לא ההסתברות שהאפס נכון"],
    )
    _, h1 = next_hint(q, 0, None, "he")
    assert _has_hebrew(h1)
    assert _has_hebrew(full_explanation(q, None, "he"))
    # English default unaffected
    _, en = next_hint(q, 0, None)
    assert "nudge" in en.lower() or "point" in en.lower()


def test_generated_fallback_question_hebrew():
    from app.core.question_selector import generate_fallback_item

    he = generate_fallback_item("AI Engineer", "Transformers", "Senior", "he")
    assert _has_hebrew(he.question_text)
    assert all(_has_hebrew(p) for p in he.expected_points)
    en = generate_fallback_item("AI Engineer", "Transformers", "Senior")
    assert not _has_hebrew(en.question_text)


def test_greeting_defaults_to_english(offline_provider):
    out = greeting("Friendly", "Data Scientist", "Amit", offline_provider)
    assert not _has_hebrew(out)
    assert "Amit" in out


def test_background_checkin_closing_hebrew_offline(offline_provider):
    assert _has_hebrew(background_question("AI Engineer", offline_provider, "he"))
    assert _has_hebrew(checkin_after_silence("Strict", offline_provider, "he"))
    assert _has_hebrew(closing("Startup CTO", offline_provider, "he"))


def test_english_paths_have_no_hebrew(offline_provider):
    assert not _has_hebrew(background_question("AI Engineer", offline_provider))
    assert not _has_hebrew(checkin_after_silence("Strict", offline_provider))
    assert not _has_hebrew(closing("Startup CTO", offline_provider))
