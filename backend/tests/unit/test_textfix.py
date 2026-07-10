"""Mojibake repair for UTF-8-as-cp1252 double-encoded model/CLI text."""
from __future__ import annotations

from app.core.textfix import fix_mojibake


def _garble(s: str) -> str:
    """Reproduce the Windows cp1252 mis-decode of UTF-8 bytes."""
    return s.encode("utf-8").decode("cp1252")


def test_repairs_em_dash():
    garbled = "explain CNNs concretely " + _garble("—") + " convolutions"
    assert fix_mojibake(garbled) == "explain CNNs concretely — convolutions"


def test_repairs_curly_punctuation():
    # Uses characters whose UTF-8 tail byte is defined in cp1252 (so they are
    # actually producible as mojibake): apostrophe, left quote, ellipsis, en-dash.
    assert fix_mojibake("it" + _garble("’") + "s") == "it’s"
    assert fix_mojibake(_garble("“") + "hi") == "“hi"
    assert fix_mojibake("a" + _garble("…")) == "a…"
    assert fix_mojibake("10" + _garble("–") + "20") == "10–20"


def test_clean_text_unchanged():
    for s in ("A clean, normal sentence.", "", "score 1.0/5", "no markers here"):
        assert fix_mojibake(s) == s


def test_hebrew_passes_through():
    # Hebrew is not cp1252-encodable, so the guard returns it unchanged.
    he = "המשוב הטכני שלך: חסרו יסודות."
    assert fix_mojibake(he) == he


def test_already_correct_em_dash_unchanged():
    # A real em-dash is not cp1252-encodable → left as-is, never double-fixed.
    s = "ground your claims — in real projects"
    assert fix_mojibake(s) == s
