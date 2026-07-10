"""GeminiAPIProvider (Vertex AI + ADC): builds only when Application Default
Credentials are available (no API key anywhere), parses a Vertex
generateContent response, and raises ProviderCallError on transport/shape
errors so the caller falls through to the existing chain."""
from __future__ import annotations

import io
import json

import google.auth
import pytest

from app.llm.provider import (
    GeminiAPIProvider,
    ProviderCallError,
    ProviderUnavailable,
)


class _FakeCreds:
    valid = True
    token = "fake-adc-token"

    def refresh(self, request):  # pragma: no cover - valid creds never refresh
        pass


def _fake_urlopen(payload: dict):
    def _open(req, timeout=None):
        return io.BytesIO(json.dumps(payload).encode("utf-8"))

    return _open


def _raise_no_adc(scopes=None):
    raise RuntimeError("could not determine credentials")


def test_requires_adc(monkeypatch):
    # No Application Default Credentials -> provider is unavailable (falls back).
    monkeypatch.setattr(google.auth, "default", _raise_no_adc)
    with pytest.raises(ProviderUnavailable):
        GeminiAPIProvider()


def test_complete_text_parses_reply(monkeypatch):
    monkeypatch.setattr(google.auth, "default",
                        lambda scopes=None: (_FakeCreds(), "proj-x"))
    payload = {"candidates": [{"content": {"parts": [{"text": "Of course — I asked about bias."}]}}]}
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen(payload))
    prov = GeminiAPIProvider()
    out = prov.complete_text("system", "prompt", max_tokens=64, timeout=5.0)
    assert out == "Of course — I asked about bias."


def test_unexpected_shape_raises(monkeypatch):
    monkeypatch.setattr(google.auth, "default",
                        lambda scopes=None: (_FakeCreds(), "proj-x"))
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen({"nope": True}))
    prov = GeminiAPIProvider()
    with pytest.raises(ProviderCallError):
        prov.complete_text("s", "p")
