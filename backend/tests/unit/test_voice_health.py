"""Unit tests: voice sidecar health flag + TTS proxy (routes_voice)."""
from __future__ import annotations

import pytest

from app.api import routes_voice
from app.config import settings

BOGUS_URL = "http://127.0.0.1:1"  # nothing listens here; refused instantly


@pytest.fixture()
def sidecar_down(monkeypatch):
    """Point the voice sidecar URL at a dead port and clear the probe cache."""
    monkeypatch.setattr(settings, "voice_server_url", BOGUS_URL)
    monkeypatch.setattr(routes_voice, "_probe_cache", (0.0, "unavailable"))
    yield
    routes_voice._probe_cache = (0.0, "unavailable")


def test_health_includes_voice_engine_key(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "voice_engine" in data
    assert data["voice_engine"] in ("headtts", "unavailable")


def test_health_voice_engine_unavailable_when_sidecar_down(client, sidecar_down):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["voice_engine"] == "unavailable"


def test_probe_result_is_cached(sidecar_down, monkeypatch):
    assert routes_voice.probe_voice_engine() == "unavailable"
    # Even if the URL becomes "valid", the cached value is returned
    # until the cache window expires.
    monkeypatch.setattr(settings, "voice_server_url", "http://127.0.0.1:2")
    calls = []
    monkeypatch.setattr(
        routes_voice.httpx, "post", lambda *a, **k: calls.append(a) or None
    )
    assert routes_voice.probe_voice_engine() == "unavailable"
    assert calls == []  # cache hit: no new HTTP probe was issued


def test_voice_tts_proxy_returns_503_when_sidecar_down(client, sidecar_down):
    resp = client.post(
        "/api/voice/tts",
        json={"input": "Hello there.", "voice": "af_bella", "audioEncoding": "wav"},
    )
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert "HeadTTS" in detail
    assert BOGUS_URL in detail
