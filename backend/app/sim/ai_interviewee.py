"""AI interviewee — a simulated candidate for both-AI mock interviews.

It **listens** to the interviewer through speech-to-text (faster-whisper) and
answers with **Gemini conditioned on a CV**. The "no backdoor" guarantee is
structural: the candidate only ever receives the interviewer's *audio* via
``listen()``, which transcribes it; ``respond()`` takes **no text argument** and
can only answer what was actually heard (stored in ``self.history``). There is
no code path by which the interviewer's source text reaches the candidate.

Auth for Gemini is the project's Application Default Credentials (Vertex AI),
the same as the live barge-in reply — no API key. STT runs locally on CPU.

Self-check (proves the STT-listen + CV-conditioning loop end to end):
    python -m app.sim.ai_interviewee
(run from the backend/ directory with ADC configured).
"""
from __future__ import annotations

import os
import tempfile
from typing import List, Optional, Tuple

# Lazily imported heavy deps (STT model, PDF) so importing this module is cheap.
_stt_model = None


def load_cv(path: str) -> str:
    """Extract plain text from a CV PDF (or read a .txt/.md as-is)."""
    if path.lower().endswith((".txt", ".md")):
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    from pypdf import PdfReader

    reader = PdfReader(path)
    return "\n".join((page.extract_text() or "") for page in reader.pages).strip()


def _get_stt(model_size: str = "base"):
    """Cached multilingual faster-whisper model (CPU, int8). 'base' handles
    English and Hebrew; the model is downloaded/cached once by huggingface."""
    global _stt_model
    if _stt_model is None:
        from faster_whisper import WhisperModel

        _stt_model = WhisperModel(model_size, device="cpu", compute_type="int8")
    return _stt_model


class AIInterviewee:
    """A candidate that hears (STT) and answers (Gemini + CV).

    Parameters
    ----------
    cv_text : str      the candidate's CV, verbatim (their only factual grounding)
    voice   : str      TTS voice id used by the harness when the candidate speaks
                       (kept distinct from the interviewer's voice)
    gender  : str      'male' | 'female' — for the harness's gendered TTS
    name    : str      display name
    """

    def __init__(self, cv_text: str, voice: str = "am_fenrir",
                 gender: str = "male", name: str = "Candidate") -> None:
        self.cv_text = cv_text or ""
        self.voice = voice
        self.gender = gender
        self.name = name
        # (speaker, text) where speaker in {'interviewer', 'candidate'}. The
        # 'interviewer' entries are TRANSCRIPTS of what was heard, never source.
        self.history: List[Tuple[str, str]] = []
        self._provider = None

    # --------------------------------------------------------------- listen
    def listen(self, audio_bytes: bytes, language: str = "en") -> str:
        """Transcribe the interviewer's spoken audio. This is the ONLY way the
        interviewer's words enter the candidate — as heard text, not source."""
        model = _get_stt()
        suffix = ".mp3"
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        try:
            tmp.write(audio_bytes)
            tmp.close()
            lang = "he" if language.lower().startswith("he") else "en"
            segments, _info = model.transcribe(tmp.name, language=lang, beam_size=1)
            heard = " ".join(seg.text for seg in segments).strip()
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
        self.history.append(("interviewer", heard))
        return heard

    # -------------------------------------------------------------- respond
    def respond(self, language: str = "en") -> str:
        """Answer the last thing the candidate HEARD (from self.history), via
        Gemini conditioned on the CV. Takes no text argument by design — the
        candidate cannot answer anything it did not hear."""
        if not any(s == "interviewer" for s, _ in self.history):
            raise RuntimeError("respond() called before listen(): nothing heard yet")

        system = (
            "You are a job candidate in a live, spoken technical interview. "
            "Answer in the first person as the candidate — concise, technically "
            "correct, and specific. Ground your experience STRICTLY in the CV "
            "below; never invent employers, degrees, or results not in it. If you "
            "are unsure, reason out loud briefly rather than bluffing.\n\nCV:\n"
            + self.cv_text[:6000]
        )
        convo = "\n".join(
            ("Interviewer: " if s == "interviewer" else "You: ") + t
            for s, t in self.history[-10:]
        )
        heard = next(t for s, t in reversed(self.history) if s == "interviewer")
        prompt = (
            convo
            + "\n\nThe interviewer just said (transcribed from their speech): \""
            + heard
            + "\"\n\nRespond as the candidate in 2-5 sentences."
            + (" Reply in fluent modern Hebrew." if language.lower().startswith("he") else "")
        )
        answer = self._gemini().complete_text(system, prompt, max_tokens=400,
                                               timeout=15.0).strip()
        self.history.append(("candidate", answer))
        return answer

    # ---------------------------------------------------------------- gemini
    def _gemini(self):
        if self._provider is None:
            from ..llm.provider import GeminiAPIProvider

            self._provider = GeminiAPIProvider()
        return self._provider


# --------------------------------------------------------------- self-check
def _demo() -> None:
    """End-to-end proof: synthesize an interviewer question to AUDIO, have the
    candidate hear it via STT (not read it), and answer from the CV."""
    from .. import voice_cloud
    import base64

    cv_path = os.environ.get(
        "TI_CV_PATH",
        r"C:\Users\ADMIN\Agentic_Projects\Job_Search\cv\amit-aminov-cv.pdf",
    )
    cv = load_cv(cv_path)
    assert len(cv) > 200, "CV text did not load"

    question = ("Tell me about a machine learning project you built end to end, "
                "and one modelling trade-off you had to make.")
    # Interviewer 'speaks' — the candidate will only ever get this as audio.
    tts = voice_cloud.synthesize(question, "en-US", "female", 1.0)
    audio = base64.b64decode(tts["audio"])
    assert audio, "interviewer TTS produced no audio"

    cand = AIInterviewee(cv, voice="am_fenrir", gender="male", name="Amit")
    heard = cand.listen(audio, language="en")
    print("HEARD (via STT):", heard)
    assert heard, "STT heard nothing"
    # The candidate never saw `question` — only `heard`.
    answer = cand.respond(language="en")
    print("ANSWER (Gemini+CV):", answer)
    assert len(answer.split()) >= 8, "answer implausibly short"
    print("OK: listened via STT and answered from the CV, no source-text backdoor.")


if __name__ == "__main__":
    _demo()
