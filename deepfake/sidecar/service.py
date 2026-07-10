"""Realistic talking-head sidecar (2-tier: idle loop + Wav2Lip via `lipsync`).

POST /lipsync {character, text, voice?, speed?} ->
  text -> Kokoro TTS (HeadTTS :8012) -> wav
  -> Wav2Lip(idle-loop-video, wav) -> mp4 bytes.

Tier 1 (`idle_loop.py`): a seamless idle-motion loop is pre-rendered once per
character (subtle whole-head sway + breathing; CPU-only; cached to cache/idle/).
Tier 2 (here): the existing Wav2Lip mouth-sync runs *on top of* that looping
video instead of the still portrait, so the whole face stays alive (eyes/nose/
head drift) while the mouth is driven by the audio — at Wav2Lip's latency, since
Wav2Lip just cycles the idle frames (`i % len(frames)`) over the line.

If the idle loop can't be produced or a frame ever fails face-detection, we fall
back to the still image, so the pipeline can never regress below the old
frozen-portrait behaviour. GPU-serialized (one clip at a time); model loads once.
"""
import base64
import json
import logging
import os
import tempfile
import threading
import time
import urllib.request

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response, PlainTextResponse
from pydantic import BaseModel

import idle_loop

logger = logging.getLogger("ti-realistic")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["PATH"] = os.path.join(HERE, "..", "bin") + os.pathsep + os.environ.get("PATH", "")
CHARS_DIR = os.environ.get(
    "TI_CHARS_DIR",
    os.path.join(HERE, "..", "..", "frontend", "public", "interviewers"),
)
VOICE_URL = os.environ.get("TI_VOICE_URL", "http://127.0.0.1:8012")
CKPT = os.path.join(HERE, "weights", "wav2lip_gan_ls.pth")
CACHE_DIR = os.path.join(HERE, "cache")
IDLE_DIR = os.path.join(CACHE_DIR, "idle")
# Set TI_IDLE=0 to disable tier-1 and lip-sync the frozen portrait (old behaviour).
IDLE_ENABLED = os.environ.get("TI_IDLE", "1") != "0"

app = FastAPI(title="TI-Realistic")
_lock = threading.Lock()
_lip = None


def _get_lip():
    global _lip
    if _lip is None:
        import torch
        from lipsync import LipSync
        _lip = LipSync(
            model="wav2lip", checkpoint_path=CKPT, nosmooth=True,
            device="cuda" if torch.cuda.is_available() else "cpu",
            cache_dir=CACHE_DIR, img_size=96, save_cache=True,
        )
    return _lip


def _synth_wav(text, out_wav, voice, speed):
    body = json.dumps({"input": text, "voice": voice, "language": "en-us",
                       "speed": speed, "audioEncoding": "wav"}).encode()
    req = urllib.request.Request(f"{VOICE_URL}/v1/synthesize", data=body,
                                 headers={"Content-Type": "application/json"})
    d = json.load(urllib.request.urlopen(req, timeout=180))
    open(out_wav, "wb").write(base64.b64decode(d["audio"]))


def _resolve_face(img: str, character: str) -> str:
    """Pick the Wav2Lip face input: the cached idle loop when available, else
    the still image. Idle generation is CPU-only and cached, so this is cheap
    after the first call per character."""
    if not IDLE_ENABLED:
        return img
    idle = idle_loop.ensure_idle_loop(img, IDLE_DIR, character)
    return idle or img


def _warm_face_cache(face: str) -> None:
    """Populate Wav2Lip's per-frame face-detection cache for `face` so the first
    spoken line for a character isn't slowed by detecting the whole idle loop.
    Best-effort; runs under the GPU lock."""
    from lipsync.helpers import read_frames
    lip = _get_lip()
    lip._filepath = face
    if lip.get_from_cache():
        return
    frames, _ = read_frames(face)
    lip.static = False
    lip.face_detect(frames)


class Req(BaseModel):
    character: str            # manifest file name, e.g. "data-scientist-0.jpg"
    text: str
    voice: str = "af_bella"
    speed: float = 1.0


@app.post("/v1/hello", response_class=PlainTextResponse)
@app.get("/v1/hello", response_class=PlainTextResponse)
def hello():
    return "TI-Realistic v2"


@app.post("/lipsync")
def lipsync(req: Req):
    img = os.path.abspath(os.path.join(CHARS_DIR, os.path.basename(req.character)))
    if not os.path.exists(img):
        raise HTTPException(404, f"character image not found: {req.character}")
    if not req.text.strip():
        raise HTTPException(400, "empty text")
    face = _resolve_face(img, req.character)
    with tempfile.TemporaryDirectory() as td:
        wav = os.path.join(td, "line.wav")
        mp4 = os.path.join(td, "out.mp4")
        t0 = time.perf_counter()
        try:
            _synth_wav(req.text, wav, req.voice, req.speed)
        except Exception as e:
            raise HTTPException(502, f"TTS failed: {type(e).__name__}: {e}")
        with _lock:  # serialize GPU
            try:
                _get_lip().sync(face, wav, mp4)
            except Exception as e:
                # Idle loop failed a face-detection (or anything else): drop back
                # to the frozen portrait so the line still speaks.
                if face != img:
                    logger.warning("idle sync failed (%s: %s) — falling back to "
                                   "still image for %s", type(e).__name__, e,
                                   req.character)
                    try:
                        _get_lip().sync(img, wav, mp4)
                    except Exception as e2:
                        raise HTTPException(500, f"lipsync failed: {type(e2).__name__}: {e2}")
                else:
                    raise HTTPException(500, f"lipsync failed: {type(e).__name__}: {e}")
        data = open(mp4, "rb").read()
        dt = time.perf_counter() - t0
        return Response(content=data, media_type="video/mp4",
                        headers={"X-Gen-Seconds": f"{dt:.2f}",
                                 "X-Face-Mode": "idle" if face != img else "still"})


def _prewarm() -> None:
    """Background: pre-render every character's idle loop and warm its
    face-detection cache, so steady-state lines are fast regardless of which
    interviewer the session picks. Best-effort; never crashes the sidecar."""
    if not IDLE_ENABLED:
        return
    manifest = os.path.join(CHARS_DIR, "manifest.json")
    try:
        chars = json.load(open(manifest, encoding="utf-8")).get("characters", [])
    except Exception as e:  # noqa: BLE001
        logger.info("prewarm: no manifest (%s) — skipping", e)
        return
    for c in chars:
        fname = c.get("file") or c.get("id", "")
        img = os.path.abspath(os.path.join(CHARS_DIR, os.path.basename(fname)))
        if not os.path.exists(img):
            continue
        face = _resolve_face(img, fname)
        if face == img:
            continue  # idle gen failed; still image needs no pre-warm
        try:
            with _lock:
                _warm_face_cache(face)
            logger.info("prewarm: idle ready for %s", fname)
        except Exception as e:  # noqa: BLE001
            logger.warning("prewarm: %s failed (%s) — will use still image", fname, e)


@app.on_event("startup")
def _startup() -> None:
    os.makedirs(IDLE_DIR, exist_ok=True)
    if IDLE_ENABLED:
        threading.Thread(target=_prewarm, name="idle-prewarm", daemon=True).start()
