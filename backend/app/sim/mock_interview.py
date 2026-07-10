"""Both-AI mock-interview harness (interviewer TTS -> candidate STT -> Gemini+CV).

Drives the REAL interviewer (REST + WebSocket) against the simulated candidate
in ``ai_interviewee.py``. The "no backdoor" guarantee is preserved end to end:
the interviewer's message text ``T`` is NEVER handed to the candidate. We only
synthesize ``T`` to audio (POST /api/voice/tts) and feed the *audio bytes* to
``candidate.listen()`` (speech-to-text); the candidate then ``respond()``s from
what it heard, with no text argument.

Run (from the backend/ directory, ADC configured, PYTHONIOENCODING=utf-8):

    python -m app.sim.mock_interview            # runs both en and he
    python -m app.sim.mock_interview en         # just english
    python -m app.sim.mock_interview he         # just hebrew

Outputs per language to ``app/sim/out/<lang>/``:
    interviewer_<n>.(wav|mp3), candidate_<n>.(wav|mp3), transcript.json
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
from typing import Any, Dict, List, Optional

import requests
import websockets

from app.sim.ai_interviewee import AIInterviewee, load_cv

API = "http://127.0.0.1:8011"
WS = "ws://127.0.0.1:8011"
CV_PATH = r"C:\Users\ADMIN\Agentic_Projects\Job_Search\cv\amit-aminov-cv.pdf"
HERE = os.path.dirname(os.path.abspath(__file__))

# How many real questions the candidate answers before we end.
MAX_ANSWERS = 3

# Kinds that are a genuine question the candidate must answer.
ANSWERABLE = {"question", "followup"}


def _tts(text: str, voice: str, language: str) -> bytes:
    """Synthesize ``text`` and return decoded audio bytes plus the encoding."""
    resp = requests.post(
        f"{API}/api/voice/tts",
        json={"input": text, "voice": voice, "language": language, "speed": 1.0},
        timeout=90,
    )
    resp.raise_for_status()
    data = resp.json()
    audio = base64.b64decode(data["audio"])
    enc = str(data.get("audioEncoding") or "wav").lower()
    ext = "mp3" if enc == "mp3" else "wav"
    return audio, ext


def _create_session(language: str, interviewer_style: str) -> str:
    user = requests.post(
        f"{API}/api/users",
        json={"name": "Amit", "target_roles": ["Data Scientist"]},
        timeout=30,
    )
    user.raise_for_status()
    user_id = user.json()["id"]

    sess = requests.post(
        f"{API}/api/sessions",
        json={
            "user_id": user_id,
            "role": "Data Scientist",
            "mode": "Quick Practice",
            "difficulty": "Mid-level",
            "duration_minutes": 10,
            "language": language,
            "hint_policy": "on_request",
            "interviewer_style": interviewer_style,
            "use_resume": False,
            "use_job_description": False,
            "use_wiki": False,
            "allow_internet": False,
            "record_session": False,
            "disable_cloud_ai": False,
            "resume_text": None,
            "job_description": None,
            "focus_topics": [],
        },
        timeout=60,
    )
    sess.raise_for_status()
    return sess.json()["id"]


async def run_mock(language: str, interviewer_style: str = "Friendly") -> Dict[str, Any]:
    lang = "he" if language.lower().startswith("he") else "en"
    tts_lang = "he-IL" if lang == "he" else "en-us"
    out_dir = os.path.join(HERE, "out", lang)
    os.makedirs(out_dir, exist_ok=True)

    session_id = _create_session(lang, interviewer_style)

    cv = load_cv(CV_PATH)
    candidate = AIInterviewee(cv, voice="am_fenrir", gender="male", name="Amit")

    transcript: List[Dict[str, Any]] = []
    turn_no = 0
    answered = 0
    ended = False

    uri = f"{WS}/ws/interview/{session_id}"
    async with websockets.connect(uri, max_size=None) as ws:
        await ws.send(json.dumps({"type": "start"}))

        while not ended:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=120)
            except asyncio.TimeoutError:
                print(f"[{lang}] timed out waiting for a server message", flush=True)
                break
            msg = json.loads(raw)
            mtype = msg.get("type")

            if mtype != "interviewer":
                # score / hint / state / error / report_ready — nothing to hear.
                if mtype == "error":
                    print(f"[{lang}] server error: {msg.get('message')}", flush=True)
                continue

            kind = msg.get("kind")
            text = str(msg.get("text") or "")
            if not text.strip():
                continue

            turn_no += 1
            iv_voice = "af_bella"  # Friendly interviewer -> female voice.
            iv_audio, iv_ext = _tts(text, iv_voice, tts_lang)
            iv_path = os.path.join(out_dir, f"interviewer_{turn_no}.{iv_ext}")
            with open(iv_path, "wb") as fh:
                fh.write(iv_audio)

            # NO BACKDOOR: the candidate only hears the audio, never `text`.
            heard = candidate.listen(iv_audio, lang)
            print(f"[{lang}] #{turn_no} ({kind}) HEARD: {heard[:80]}", flush=True)

            turn: Dict[str, Any] = {
                "turn": turn_no,
                "kind": kind,
                "interviewer_text": text,
                "interviewer_audio": os.path.abspath(iv_path),
                "heard": heard,
                "candidate_text": None,
                "candidate_audio": None,
            }

            if kind in ANSWERABLE:
                answer = candidate.respond(lang)
                cand_audio, cand_ext = _tts(answer, "am_fenrir", tts_lang)
                cand_path = os.path.join(out_dir, f"candidate_{turn_no}.{cand_ext}")
                with open(cand_path, "wb") as fh:
                    fh.write(cand_audio)
                turn["candidate_text"] = answer
                turn["candidate_audio"] = os.path.abspath(cand_path)
                print(f"[{lang}] #{turn_no} ANSWER: {answer[:80]}", flush=True)

                await ws.send(json.dumps({
                    "type": "answer",
                    "text": answer,
                    "duration_seconds": 8.0,
                    "input_mode": "voice",
                }))
                answered += 1

            transcript.append(turn)

            if answered >= MAX_ANSWERS:
                await ws.send(json.dumps({"type": "end"}))
                ended = True

    tpath = os.path.join(out_dir, "transcript.json")
    with open(tpath, "w", encoding="utf-8") as fh:
        json.dump(transcript, fh, ensure_ascii=False, indent=2)

    return {
        "language": lang,
        "session_id": session_id,
        "out_dir": os.path.abspath(out_dir),
        "answered": answered,
        "transcript_path": os.path.abspath(tpath),
        "transcript": transcript,
    }


def main(argv: Optional[List[str]] = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    langs = argv if argv else ["en", "he"]
    for lang in langs:
        result = asyncio.run(run_mock(lang))
        print(json.dumps({k: v for k, v in result.items() if k != "transcript"},
                         ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
