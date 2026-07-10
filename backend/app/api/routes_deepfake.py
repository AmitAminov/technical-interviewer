"""Deepfake talking-head sidecar proxy (Wav2Lip via `lipsync`).

The optional deepfake sidecar (deepfake/sidecar/service.py, default
``settings.lipsync_server_url`` = http://127.0.0.1:8013) turns a character
image + text into a lip-synced talking-head MP4 (via Kokoro TTS + Wav2Lip).
This module mirrors the voice-proxy pattern:

- ``probe_lipsync_engine()``: cached sub-second liveness probe for /api/health.
- ``POST /api/lipsync``: same-origin proxy returning the generated MP4 bytes.
  Generation is slow (~4-40s depending on face-detect cache), so the timeout
  is generous and the frontend calls it off the critical path (pre-warm + queue).
"""
from __future__ import annotations

import logging
import time
from typing import Tuple

import httpx
from fastapi import APIRouter, HTTPException, Request, Response

from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

PROBE_TIMEOUT_SECONDS = 0.5
PROBE_CACHE_SECONDS = 10.0
LIPSYNC_TIMEOUT_SECONDS = 120.0

_probe_cache: Tuple[float, str] = (0.0, "unavailable")


def probe_lipsync_engine(force: bool = False) -> str:
    """Return ``"wav2lip"`` if the sidecar answers, else ``"unavailable"`` (cached ~10s)."""
    global _probe_cache
    now = time.monotonic()
    ts, cached = _probe_cache
    if not force and (now - ts) < PROBE_CACHE_SECONDS:
        return cached
    status = "unavailable"
    try:
        resp = httpx.post(
            f"{settings.lipsync_server_url}/v1/hello", timeout=PROBE_TIMEOUT_SECONDS
        )
        # "TI-Realistic" is the current sidecar; "TI-Deepfake" kept for back-compat.
        if resp.status_code == 200 and resp.text.startswith(("TI-Realistic", "TI-Deepfake")):
            status = "wav2lip"
    except Exception:  # noqa: BLE001
        pass
    _probe_cache = (now, status)
    return status


@router.post("/api/lipsync")
async def lipsync(request: Request) -> Response:
    """Same-origin proxy for the deepfake sidecar's ``POST /lipsync``.

    Body: {character, text, voice?, speed?}. Returns the generated MP4 bytes,
    or 503 when the sidecar is down (the frontend then falls back to the Photo
    avatar).
    """
    body = await request.body()
    url = f"{settings.lipsync_server_url}/lipsync"
    try:
        async with httpx.AsyncClient(timeout=LIPSYNC_TIMEOUT_SECONDS) as client:
            upstream = await client.post(
                url, content=body, headers={"Content-Type": "application/json"}
            )
    except httpx.HTTPError as exc:
        logger.warning("Deepfake sidecar unreachable at %s: %s", url, exc)
        raise HTTPException(
            status_code=503,
            detail=(
                "Deepfake sidecar is not reachable at "
                f"{settings.lipsync_server_url}. Start it with "
                "scripts/start_deepfake.ps1."
            ),
        ) from exc
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "video/mp4"),
    )
