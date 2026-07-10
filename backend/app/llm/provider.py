"""LLM provider chain (DESIGN.md §7).

Chain order: AnthropicAPI (cloud, only with ANTHROPIC_API_KEY and not
disable_cloud_ai) -> ClaudeCLI (local agent runtime, skipped when
TI_DISABLE_CLAUDE_CLI=1) -> Offline (deterministic, never fails).

The public facade is :class:`LLMProvider`; obtain one via :func:`get_provider`.
Every call walks the chain and falls through on any exception, so callers can
rely on always getting a response (the offline provider is the terminal,
infallible link).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel

from ..config import settings


class ProviderUnavailable(Exception):
    """Raised when an inner provider cannot be constructed at all."""


class ProviderCallError(Exception):
    """Raised when an inner provider call fails; the facade falls through."""


# --------------------------------------------------------------------- utils
def _strip_json_payload(text: str) -> str:
    """Extract a JSON object from LLM output (strip code fences / prose)."""
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        text = text[start : end + 1]
    return text


def _validate_json(raw: str, schema_model: Type[BaseModel]) -> BaseModel:
    payload = _strip_json_payload(raw)
    data = json.loads(payload)
    return schema_model.model_validate(data)


def _json_instruction(schema_model: Type[BaseModel]) -> str:
    try:
        schema = json.dumps(schema_model.model_json_schema(), indent=None)
    except Exception:  # pragma: no cover - defensive
        schema = schema_model.__name__
    return (
        "\n\nRespond with ONLY a single JSON object (no prose, no code fences) "
        "that validates against this JSON schema:\n" + schema
    )


# ------------------------------------------------------ Anthropic API (cloud)
class AnthropicAPIProvider:
    """Cloud provider using the official ``anthropic`` SDK."""

    name = "anthropic-api"

    def __init__(self) -> None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise ProviderUnavailable("ANTHROPIC_API_KEY not set")
        try:
            import anthropic
        except Exception as exc:  # pragma: no cover - sdk installed per contract
            raise ProviderUnavailable(str(exc))
        self._client = anthropic.Anthropic()
        self._model = settings.anthropic_model

    def _create(self, system: str, prompt: str, max_tokens: int, timeout: float) -> str:
        client = self._client.with_options(timeout=timeout)
        msg = client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system or "You are a helpful assistant.",
            messages=[{"role": "user", "content": prompt}],
        )
        parts = [b.text for b in msg.content if getattr(b, "type", "") == "text"]
        text = "\n".join(parts).strip()
        if not text:
            raise ProviderCallError("empty completion from Anthropic API")
        return text

    def complete_text(self, system: str, prompt: str, max_tokens: int = 800,
                      timeout: float = 20.0) -> str:
        return self._create(system, prompt, max_tokens, timeout)

    def complete_json(self, system: str, prompt: str,
                      schema_model: Type[BaseModel],
                      timeout: float = 30.0) -> BaseModel:
        raw = self._create(system, prompt + _json_instruction(schema_model),
                           max_tokens=1500, timeout=timeout)
        try:
            return _validate_json(raw, schema_model)
        except Exception as exc:
            raise ProviderCallError("Anthropic JSON validation failed: %s" % exc)


# ------------------------------------------- Gemini via Vertex AI (fast, cloud)
class GeminiAPIProvider:
    """Low-latency Gemini provider via Vertex AI, authenticated with the GCP
    project's Application Default Credentials (ADC). No API key is read, stored,
    or fetched anywhere — the only credential is the short-lived OAuth token ADC
    mints from the project, refreshed automatically.

    Used specifically for the live barge-in reply, where the Anthropic model or
    the Claude CLI would be too slow. Requires ADC (``gcloud auth
    application-default login`` locally, or a service account on GCP) and the
    Vertex AI API enabled on the project. Constructing raises ProviderUnavailable
    when google-auth or ADC is missing, so the reply falls back to the existing
    provider chain.
    """

    name = "gemini-vertex"

    _SCOPE = "https://www.googleapis.com/auth/cloud-platform"

    def __init__(self) -> None:
        try:
            import google.auth
            from google.auth.transport.requests import Request as _AuthRequest
        except Exception as exc:  # google-auth not installed
            raise ProviderUnavailable("google-auth unavailable: %s" % exc)
        try:
            creds, adc_project = google.auth.default(scopes=[self._SCOPE])
        except Exception as exc:  # no ADC configured
            raise ProviderUnavailable("no Application Default Credentials: %s" % exc)
        self._creds = creds
        self._auth_request = _AuthRequest()
        self._project = settings.gcp_project or adc_project
        if not self._project:
            raise ProviderUnavailable("no GCP project for Vertex AI")
        self._location = settings.gcp_location
        self._model = settings.gemini_model

    def _token(self) -> str:
        if not self._creds.valid:
            self._creds.refresh(self._auth_request)
        return self._creds.token

    def complete_text(self, system: str, prompt: str, max_tokens: int = 300,
                      timeout: float = 8.0) -> str:
        import urllib.request

        url = (
            "https://%s-aiplatform.googleapis.com/v1/projects/%s/locations/%s/"
            "publishers/google/models/%s:generateContent"
            % (self._location, self._project, self._location, self._model)
        )
        body: Dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": 0.7,
                # Gemini 2.5 "thinks" by default, burning the output budget on
                # internal reasoning (a low cap then returns a candidate with no
                # parts). Barge-in replies are short and latency-critical, so
                # disable thinking for a direct, fast answer.
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer %s" % self._token()},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # network / HTTP / decode / auth
            raise ProviderCallError("Vertex Gemini call failed: %s" % exc)
        try:
            parts = payload["candidates"][0]["content"].get("parts", [])
            text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderCallError("Vertex Gemini unexpected response: %s" % exc)
        if not text:
            raise ProviderCallError("empty completion from Vertex Gemini")
        return text

    def complete_json(self, system: str, prompt: str,
                      schema_model: Type[BaseModel],
                      timeout: float = 15.0) -> BaseModel:
        raw = self.complete_text(system, prompt + _json_instruction(schema_model),
                                 max_tokens=1500, timeout=timeout)
        try:
            return _validate_json(raw, schema_model)
        except Exception as exc:
            raise ProviderCallError("Vertex Gemini JSON validation failed: %s" % exc)


# ------------------------------------------------------- Claude Code CLI
class ClaudeCLIProvider:
    """Local agent runtime via headless ``claude -p`` (Claude Code CLI)."""

    name = "claude-cli"

    def __init__(self) -> None:
        exe = shutil.which("claude") or self._well_known_exe()
        if not exe:
            raise ProviderUnavailable("claude CLI not on PATH")
        # On Windows shutil.which resolves the .cmd shim; keep the full path
        # and always run with shell=False.
        self._exe = exe

    @staticmethod
    def _well_known_exe() -> Optional[str]:
        """Fallback install locations not always on a subprocess PATH
        (e.g. the WinGet Links dir when launched from Git Bash)."""
        local = os.environ.get("LOCALAPPDATA", "")
        candidates = [
            os.path.join(local, "Microsoft", "WinGet", "Links", "claude.exe"),
            os.path.expanduser("~/.local/bin/claude.exe"),
            os.path.expanduser("~/.local/bin/claude"),
        ]
        for c in candidates:
            if os.path.isfile(c) and os.access(c, os.X_OK):
                return c
        return None

    @staticmethod
    def _clean_env() -> Dict[str, str]:
        """Environment without Claude-Code nesting variables."""
        env = {
            k: v
            for k, v in os.environ.items()
            if not (k.startswith("CLAUDECODE") or k.startswith("CLAUDE_CODE"))
        }
        env.setdefault("USE_TF", "0")
        return env

    def _run(self, system: str, prompt: str, timeout: float) -> str:
        full_prompt = (system.strip() + "\n\n" + prompt.strip()) if system else prompt
        tmp = tempfile.mkdtemp(prefix="ti-claude-")
        try:
            proc = subprocess.run(
                [self._exe, "-p", full_prompt, "--output-format", "json",
                 "--max-turns", "1"],
                capture_output=True,
                text=True,
                # The CLI emits UTF-8 JSON. Without an explicit encoding,
                # subprocess decodes with the OS locale (cp1252 on Windows),
                # turning em-dashes/quotes into mojibake ("—" -> "â€""). Pin
                # UTF-8 so interviewer text and feedback stay clean.
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                cwd=tmp,
                env=self._clean_env(),
                shell=False,
            )
        except subprocess.TimeoutExpired:
            raise ProviderCallError("claude CLI timed out")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if proc.returncode != 0:
            raise ProviderCallError(
                "claude CLI exit %s: %s" % (proc.returncode, (proc.stderr or "")[:300])
            )
        try:
            data = json.loads(proc.stdout.strip() or "{}")
        except json.JSONDecodeError as exc:
            raise ProviderCallError("claude CLI produced non-JSON stdout: %s" % exc)
        result = data.get("result")
        if not isinstance(result, str) or not result.strip():
            raise ProviderCallError("claude CLI JSON had no usable 'result' field")
        from ..core.textfix import fix_mojibake

        return fix_mojibake(result.strip())

    def complete_text(self, system: str, prompt: str, max_tokens: int = 800,
                      timeout: float = 20.0) -> str:
        return self._run(system, prompt, timeout)

    def complete_json(self, system: str, prompt: str,
                      schema_model: Type[BaseModel],
                      timeout: float = 30.0) -> BaseModel:
        raw = self._run(system, prompt + _json_instruction(schema_model), timeout)
        try:
            return _validate_json(raw, schema_model)
        except Exception as exc:
            raise ProviderCallError("claude CLI JSON validation failed: %s" % exc)


# --------------------------------------------------------------- Offline
_OFFLINE_TEMPLATES = [
    # (keywords, response) — first match wins; keys checked casefolded.
    (("study plan",), (
        "Suggested study plan: 1) Revisit the fundamentals of the topics where "
        "your answers missed expected points. 2) Practice explaining each weak "
        "concept out loud in under three minutes, covering definition, example, "
        "and trade-offs. 3) Do one timed mock question per weak topic and "
        "compare your answer against the expected points. 4) Re-run a mock "
        "interview at the same difficulty and track your score delta."
    )),
    (("summar",), (
        "The candidate completed a structured mock interview. They worked "
        "through background, technical, and wrap-up sections, answering each "
        "question in turn. Strengths and gaps are reflected in the per-question "
        "scores; overall the session shows which topics are solid and which "
        "need focused review before a real interview."
    )),
    (("feedback",), (
        "Overall this was a solid effort. The strongest answers stated the "
        "approach clearly, justified the key decisions, and acknowledged "
        "trade-offs. To improve, structure each answer as: restate the problem, "
        "outline the approach, cover the expected key points explicitly, and "
        "close with limitations or alternatives. Practice quantifying claims "
        "with concrete numbers where possible."
    )),
    (("greet",), (
        "Hello, and welcome. Thanks for joining today's interview. We'll start "
        "with a short background question, then move through a few technical "
        "sections, and leave time at the end for your questions. Take your "
        "time with each answer, and feel free to think out loud."
    )),
    (("follow",), (
        "Could you go one level deeper on that? In particular, what are the "
        "main trade-offs of your approach, and when would it break down?"
    )),
    (("more time", "silence", "check in", "checkin", "stuck"), (
        "No rush — would you like a bit more time to think, or would a hint "
        "help you get moving?"
    )),
    (("clos", "wrap up", "goodbye"), (
        "That brings us to the end of the interview. Thank you for working "
        "through the questions — your detailed report with scores and study "
        "suggestions will be ready in a moment. Best of luck with your "
        "preparation."
    )),
    (("background",), (
        "To start, could you tell me briefly about your background and the "
        "project you're most proud of?"
    )),
]


class OfflineProvider:
    """Terminal chain link: deterministic templates, never raises."""

    name = "offline"

    def complete_text(self, system: str, prompt: str, max_tokens: int = 800,
                      timeout: float = 20.0) -> str:
        haystack = ((system or "") + "\n" + (prompt or "")).casefold()
        for keys, response in _OFFLINE_TEMPLATES:
            if any(k in haystack for k in keys):
                return response
        return (
            "Understood. Let's continue with the interview — please walk me "
            "through your reasoning step by step, covering your approach, the "
            "key decisions, and the trade-offs involved."
        )

    def complete_json(self, system: str, prompt: str,
                      schema_model: Type[BaseModel],
                      timeout: float = 30.0) -> BaseModel:
        # Scoring models are answered with the deterministic heuristic scorer.
        from . import scorer  # lazy import avoids a circular dependency

        from ..schemas import MetricScores

        if schema_model in (MetricScores, scorer.EvaluationResult):
            transcript = scorer.extract_marked(prompt, scorer.ANSWER_BEGIN,
                                               scorer.ANSWER_END)
            points_blob = scorer.extract_marked(prompt, scorer.POINTS_BEGIN,
                                                scorer.POINTS_END)
            points = [p.strip("- ").strip() for p in points_blob.splitlines()
                      if p.strip("- ").strip()]
            metrics, feedback = scorer.heuristic_evaluate(points, transcript)
            if schema_model is MetricScores:
                return metrics
            return scorer.EvaluationResult(metrics=metrics, feedback=feedback)
        return _default_instance(schema_model)

    # complete_json must never fail, so default construction is defensive.


def _default_value(annotation: Any, int_value: int) -> Any:
    """Best-effort neutral value for a field annotation."""
    import typing
    from datetime import datetime, timezone

    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin is typing.Union:  # Optional[X] and unions -> None if allowed
        if type(None) in args:
            return None
        return _default_value(args[0], int_value)
    if origin is not None and origin in (list, List):
        return []
    if origin is not None and origin in (dict, Dict):
        return {}
    try:
        from typing import Literal
        if origin is Literal:
            return args[0]
    except Exception:  # pragma: no cover
        pass
    if annotation is str:
        return "not available offline"
    if annotation is int:
        return int_value
    if annotation is float:
        return float(int_value)
    if annotation is bool:
        return False
    if annotation is datetime:
        return datetime.now(timezone.utc)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return _default_instance(annotation)
    return None


def _default_instance(schema_model: Type[BaseModel]) -> BaseModel:
    """Construct a valid neutral instance of ``schema_model``."""
    for int_value in (3, 1, 0):
        kwargs: Dict[str, Any] = {}
        for name, field in schema_model.model_fields.items():
            if not field.is_required():
                continue
            kwargs[name] = _default_value(field.annotation, int_value)
        try:
            return schema_model.model_validate(kwargs)
        except Exception:
            continue
    # Last resort: bypass validation (still returns the right type).
    return schema_model.model_construct()


# --------------------------------------------------------------- facade
class LLMProvider:
    """Facade over the ordered provider chain (pinned interface)."""

    def __init__(self, providers: List[Any]) -> None:
        if not providers:
            providers = [OfflineProvider()]
        self._providers = list(providers)
        #: name of the first (preferred) available provider — for /api/health
        self.name: str = self._providers[0].name

    @property
    def providers(self) -> List[Any]:
        return list(self._providers)

    def complete_text(self, system: str, prompt: str, max_tokens: int = 800,
                      timeout: float = 20.0) -> str:
        last_exc: Optional[Exception] = None
        for prov in self._providers:
            try:
                return prov.complete_text(system, prompt, max_tokens=max_tokens,
                                          timeout=timeout)
            except Exception as exc:  # fall down the chain
                last_exc = exc
        raise ProviderCallError("all providers failed: %s" % last_exc)

    def complete_json(self, system: str, prompt: str,
                      schema_model: Type[BaseModel],
                      timeout: float = 30.0) -> BaseModel:
        last_exc: Optional[Exception] = None
        for prov in self._providers:
            try:
                return prov.complete_json(system, prompt, schema_model,
                                          timeout=timeout)
            except Exception as exc:
                last_exc = exc
        raise ProviderCallError("all providers failed: %s" % last_exc)


def _cli_disabled() -> bool:
    """TI_DISABLE_CLAUDE_CLI is honored at call time (tests toggle it)."""
    return os.environ.get("TI_DISABLE_CLAUDE_CLI", "") == "1" or settings.disable_claude_cli


def get_provider(disable_cloud_ai: bool = False, fast_only: bool = False) -> LLMProvider:
    """Build the provider chain for one session/call site.

    ``disable_cloud_ai=True`` skips the Anthropic API entirely (privacy
    toggle); the local Claude CLI remains allowed unless TI_DISABLE_CLAUDE_CLI
    is set. The offline provider is always appended so the chain never fails.

    ``fast_only=True`` additionally skips the Claude CLI: its per-call latency
    (a full ``claude -p`` headless run, typically 10-20s) does not fit the
    live loop's <2.5s response target or synchronous planning's 30s bound.
    The live WS loop AND synchronous session planning use the fast chain
    (Anthropic API when configured, else instant deterministic offline);
    only background report generation keeps the full chain including the CLI.
    """
    providers: List[Any] = []
    if not disable_cloud_ai:
        try:
            providers.append(AnthropicAPIProvider())
        except Exception:
            pass
    if not fast_only and not _cli_disabled():
        try:
            providers.append(ClaudeCLIProvider())
        except Exception:
            pass
    providers.append(OfflineProvider())
    return LLMProvider(providers)


_GEMINI_SINGLETON: Optional[Any] = None
_GEMINI_TRIED = False


def get_gemini_provider() -> Optional[GeminiAPIProvider]:
    """Cached Gemini provider for the barge-in reply, or None if unavailable."""
    global _GEMINI_SINGLETON, _GEMINI_TRIED
    if not _GEMINI_TRIED:
        _GEMINI_TRIED = True
        try:
            _GEMINI_SINGLETON = GeminiAPIProvider()
        except Exception:
            _GEMINI_SINGLETON = None
    return _GEMINI_SINGLETON
