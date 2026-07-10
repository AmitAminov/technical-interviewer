"""Voice sidecar integration (HeadTTS, DESIGN.md extension).

The natural-voice sidecar is a local HeadTTS Node.js server (Kokoro-82M,
timestamped) listening on ``settings.voice_server_url``
(default ``http://127.0.0.1:8012``). This module provides:

- ``probe_voice_engine()``: a cached, sub-second liveness probe used by
  ``GET /api/health`` (never blocks health for more than ~0.5 s).
- ``POST /api/voice/tts``: a same-origin proxy that mirrors HeadTTS's
  REST contract (``POST /v1/synthesize``) 1:1 so the frontend avoids
  CORS/port juggling. Request and response bodies pass through unchanged.

HeadTTS REST contract (see voice/headtts/README.md, Appendix A):
  request : {input, voice?, language?, speed?, audioEncoding?}
  response: {audio (base64 wav | pcm s16le), audioEncoding,
             words, wtimes, wdurations,
             visemes, vtimes, vdurations, phonemes}
"""
from __future__ import annotations

import json
import logging
import time
from typing import Tuple

import httpx
from fastapi import APIRouter, HTTPException, Request, Response

from ..config import settings
from .. import voice_cloud

logger = logging.getLogger(__name__)

router = APIRouter()

PROBE_TIMEOUT_SECONDS = 0.5
PROBE_CACHE_SECONDS = 10.0
TTS_TIMEOUT_SECONDS = 30.0

# (monotonic timestamp, "headtts" | "unavailable")
_probe_cache: Tuple[float, str] = (0.0, "unavailable")


def probe_voice_engine(force: bool = False) -> str:
    """Return ``"headtts"`` if the sidecar answers its hello endpoint,
    else ``"unavailable"``. The result is cached for ~10 s so repeated
    health checks stay cheap; each miss costs at most ~0.5 s.
    """
    global _probe_cache
    now = time.monotonic()
    ts, cached = _probe_cache
    if not force and (now - ts) < PROBE_CACHE_SECONDS:
        return cached
    status = "unavailable"
    try:
        resp = httpx.post(
            f"{settings.voice_server_url}/v1/hello",
            timeout=PROBE_TIMEOUT_SECONDS,
        )
        if resp.status_code == 200 and resp.text.startswith("HeadTTS"):
            status = "headtts"
    except Exception:  # noqa: BLE001 - any failure means unavailable
        pass
    _probe_cache = (now, status)
    return status


@router.post("/api/voice/tts")
async def voice_tts(request: Request) -> Response:
    """Same-origin proxy for HeadTTS ``POST /v1/synthesize``.

    Forwards the JSON body verbatim and returns the sidecar's response
    (status code, body and content type) unchanged. Returns 503 with a
    clear detail message when the sidecar is down.
    """
    body = await request.body()

    # Non-English (Hebrew) can't use the English-only Kokoro sidecar: route it to
    # Google Cloud TTS (gendered, real audio) so voice gender matches the
    # character and the audio has real duration. English falls through to Kokoro.
    try:
        parsed = json.loads(body or b"{}")
    except Exception:
        parsed = None
    if isinstance(parsed, dict):
        lang = str(parsed.get("language") or "")
        if lang.lower().startswith("he"):
            voice = str(parsed.get("voice") or "")
            gender = str(parsed.get("gender") or "") or (
                "female" if voice.lower().startswith("af") else "male")
            try:
                result = voice_cloud.synthesize(
                    str(parsed.get("input") or ""), "he-IL", gender,
                    float(parsed.get("speed") or 1.0))
                return Response(content=json.dumps(result), media_type="application/json")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Cloud TTS (he) failed: %s", exc)
                raise HTTPException(
                    status_code=503, detail="Hebrew cloud TTS failed") from exc

    url = f"{settings.voice_server_url}/v1/synthesize"
    try:
        async with httpx.AsyncClient(timeout=TTS_TIMEOUT_SECONDS) as client:
            upstream = await client.post(
                url, content=body, headers={"Content-Type": "application/json"}
            )
    except httpx.HTTPError as exc:
        logger.warning("Voice sidecar unreachable at %s: %s", url, exc)
        raise HTTPException(
            status_code=503,
            detail=(
                "Voice sidecar (HeadTTS) is not reachable at "
                f"{settings.voice_server_url}. Start it with scripts/start.ps1 "
                "or scripts/setup_voice.ps1."
            ),
        ) from exc
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "application/json"),
    )
