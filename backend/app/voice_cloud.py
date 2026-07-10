"""Non-English speech via Google Cloud Text-to-Speech (project ADC, no key).

Kokoro/HeadTTS speaks only English, so non-English interviewer lines used to
fall back to the browser's built-in TTS — uncontrollable gender and often no
real audio, so the on-screen text outran the speech. This module synthesizes
gendered, real-duration audio through Cloud TTS, authenticated with the GCP
project's Application Default Credentials. It returns the same shape
HeadTTS/Kokoro does (base64 audio + word + viseme timelines) so the frontend
and the 3D talking head treat it uniformly.
"""
from __future__ import annotations

import json
import urllib.request
from typing import Any, Dict, List
from xml.sax.saxutils import escape

from .config import settings

_TTS_URL = "https://texttospeech.googleapis.com/v1beta1/text:synthesize"
_SCOPE = "https://www.googleapis.com/auth/cloud-platform"

_creds: Any = None
_auth_request: Any = None


def _token() -> str:
    global _creds, _auth_request
    if _creds is None:
        import google.auth
        from google.auth.transport.requests import Request as AuthRequest

        _creds, _ = google.auth.default(scopes=[_SCOPE])
        _auth_request = AuthRequest()
    if not _creds.valid:
        _creds.refresh(_auth_request)
    return _creds.token


def available() -> bool:
    """True when ADC is configured, so cloud TTS can be used."""
    try:
        _token()
        return True
    except Exception:
        return False


def synthesize(text: str, language_code: str, gender: str,
               speed: float = 1.0) -> Dict[str, Any]:
    """Synthesize ``text`` in ``language_code`` (e.g. ``he-IL``) with ``gender``
    (``female``|``male``). Returns HeadTTS-shaped fields with word timelines from
    SSML mark timepoints and a basic open/close viseme stream for lip motion.
    Raises on any failure so the caller can fall back to the browser voice.
    """
    words = [w for w in (text or "").split() if w]
    if not words:
        return {"audio": "", "audioEncoding": "mp3", "words": [], "wtimes": [],
                "wdurations": [], "visemes": [], "vtimes": [], "vdurations": []}

    # SSML: a mark before each word + a final mark, so timepoints give real
    # per-word start times and the total duration.
    parts = ["<speak>"]
    for i, w in enumerate(words):
        parts.append('<mark name="w%d"/>%s ' % (i, escape(w)))
    parts.append('<mark name="end"/></speak>')
    ssml = "".join(parts)

    body = {
        "input": {"ssml": ssml},
        "voice": {"languageCode": language_code,
                  "ssmlGender": "FEMALE" if gender == "female" else "MALE"},
        "audioConfig": {"audioEncoding": "MP3",
                        "speakingRate": max(0.25, min(4.0, speed))},
        "enableTimePointing": ["SSML_MARK"],
    }
    req = urllib.request.Request(
        _TTS_URL, data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": "Bearer %s" % _token(),
                 "Content-Type": "application/json",
                 "x-goog-user-project": settings.gcp_project})
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    audio_b64 = payload.get("audioContent", "")
    tmap = {tp["markName"]: float(tp["timeSeconds"])
            for tp in payload.get("timepoints", [])}
    end_ms = tmap.get("end", 0.0) * 1000.0

    wtimes: List[float] = [tmap.get("w%d" % i, 0.0) * 1000.0 for i in range(len(words))]
    wdurations: List[float] = []
    for i in range(len(words)):
        nxt = wtimes[i + 1] if i + 1 < len(words) else (end_ms or wtimes[i] + 300.0)
        wdurations.append(max(60.0, nxt - wtimes[i]))

    # Crude but synced lip motion: open at each word start, close ~60% through.
    visemes: List[str] = []
    vtimes: List[float] = []
    vdurations: List[float] = []
    for i in range(len(words)):
        visemes.append("aa"); vtimes.append(wtimes[i]); vdurations.append(wdurations[i] * 0.6)
        visemes.append("sil"); vtimes.append(wtimes[i] + wdurations[i] * 0.6); vdurations.append(wdurations[i] * 0.4)

    return {"audio": audio_b64, "audioEncoding": "mp3",
            "words": words, "wtimes": wtimes, "wdurations": wdurations,
            "visemes": visemes, "vtimes": vtimes, "vdurations": vdurations}
