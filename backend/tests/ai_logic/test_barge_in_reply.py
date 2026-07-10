"""barge_in_reply: replies to a clarifying interjection, stays silent when the
candidate is just answering, and never hangs (offline fallback)."""
from __future__ import annotations

from app.llm.interviewer import barge_in_reply

QUESTION = "How would you handle class imbalance in a classifier?"


class FakeProvider:
    def __init__(self, out: str):
        self.name = "fake"
        self._out = out

    def complete_text(self, system, prompt, max_tokens=800, timeout=20.0):
        return self._out


def test_returns_reply_when_provider_replies(monkeypatch):
    monkeypatch.setattr("app.llm.provider.get_gemini_provider", lambda: None)
    out = barge_in_reply(QUESTION, "wait, can you repeat that?", "technical",
                         "Friendly", FakeProvider("Of course — I asked about class imbalance."))
    assert out == "Of course — I asked about class imbalance."


def test_empty_provider_reply_means_no_interjection(monkeypatch):
    monkeypatch.setattr("app.llm.provider.get_gemini_provider", lambda: None)
    out = barge_in_reply(QUESTION, "well I would first oversample the minority",
                         "technical", "Friendly", FakeProvider(""))
    assert out == ""


def test_offline_replies_only_on_a_clear_cue(offline_provider, monkeypatch):
    monkeypatch.setattr("app.llm.provider.get_gemini_provider", lambda: None)
    # Offline provider (name == "offline") is skipped by _use_llm; fallback logic runs.
    cue = barge_in_reply(QUESTION, "sorry, can you repeat?", "technical",
                         "Strict", offline_provider)
    assert QUESTION in cue
    silent = barge_in_reply(QUESTION, "I would use SMOTE and class weights",
                            "technical", "Strict", offline_provider)
    assert silent == ""
