"""Shared test setup (DESIGN.md §12).

CRITICAL: all TI_* environment variables must be set at *module import time*,
before any ``app.*`` import, because ``app.config`` reads them when it is
first imported. pytest imports this conftest before any test module, so the
top-of-file block below runs first.

Everything here runs with NO network and NO API key:
- ``TI_DISABLE_CLAUDE_CLI=1`` -> provider chain collapses to OfflineProvider.
- ``ANTHROPIC_API_KEY`` is removed from the environment.
- ``TI_DATA_DIR`` / ``TI_DATABASE_URL`` point at a per-session tmp dir with the
  real seed ``question_bank.json`` copied in.
- ``TI_WIKI_INDEX_DIR`` points at an (initially empty) tmp dir; the
  session-scoped ``mini_wiki_index`` fixture builds a real FAISS index from
  ``tests/fixtures/mini_wiki`` for the tests that need one (marked ``slow``).
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

# --------------------------------------------------------------- env (first!)
os.environ.setdefault("USE_TF", "0")
os.environ["TI_DISABLE_CLAUDE_CLI"] = "1"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("OPENAI_API_KEY", None)

TESTS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = TESTS_DIR.parent
FIXTURES_DIR = TESTS_DIR / "fixtures"

_SESSION_TMP = Path(tempfile.mkdtemp(prefix="ti-tests-"))
atexit.register(shutil.rmtree, str(_SESSION_TMP), True)  # ignore_errors=True

_DATA_DIR = _SESSION_TMP / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)
os.environ["TI_DATA_DIR"] = str(_DATA_DIR)
os.environ["TI_DATABASE_URL"] = "sqlite:///" + (_SESSION_TMP / "test.db").as_posix()

# Default index dir is empty -> retriever is safely "unloaded" unless a test
# points TI_WIKI_INDEX_DIR at the built mini-wiki index.
_EMPTY_INDEX_DIR = _SESSION_TMP / "empty_wiki_index"
_EMPTY_INDEX_DIR.mkdir(parents=True, exist_ok=True)
os.environ["TI_WIKI_INDEX_DIR"] = str(_EMPTY_INDEX_DIR)
os.environ["TI_WIKI_DIR"] = str(FIXTURES_DIR / "mini_wiki")

# Copy the real seed question bank into the test data dir.
_REAL_BANK = BACKEND_DIR / "data" / "question_bank.json"
if _REAL_BANK.is_file():
    shutil.copyfile(str(_REAL_BANK), str(_DATA_DIR / "question_bank.json"))

# Make ``import app`` work regardless of pytest's sys.path handling.
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# ------------------------------------------------------------------- fixtures
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="session")
def client():
    """FastAPI TestClient over the real app (offline provider chain)."""
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def db():
    """A raw SQLAlchemy ORM session against the test database."""
    from app.database import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def make_user(client):
    """Factory: create a user via the API, returns the UserOut dict."""

    def _make(name: str = "Test Candidate", target_roles=None):
        resp = client.post(
            "/api/users",
            json={"name": name, "target_roles": target_roles or ["Data Scientist"]},
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    return _make


@pytest.fixture()
def make_session(client, make_user):
    """Factory: create an interview session via the API (offline defaults).

    Defaults: allow_internet=False, disable_cloud_ai=True, use_wiki=False,
    Quick Practice / Data Scientist / Mid-level / 10 minutes.
    """

    def _make(user_id=None, **overrides):
        if user_id is None:
            user_id = make_user()["id"]
        payload = {
            "user_id": user_id,
            "role": "Data Scientist",
            "mode": "Quick Practice",
            "difficulty": "Mid-level",
            "duration_minutes": 10,
            "language": "en",
            "hint_policy": "on_request",
            "interviewer_style": "Friendly",
            "use_resume": False,
            "use_job_description": False,
            "use_wiki": False,
            "allow_internet": False,
            "record_session": False,
            "disable_cloud_ai": True,
        }
        payload.update(overrides)
        resp = client.post("/api/sessions", json=payload)
        assert resp.status_code == 200, resp.text
        return resp.json()

    return _make


@pytest.fixture()
def offline_provider():
    """The offline-terminal LLM provider chain (no cloud, no CLI)."""
    from app.llm.provider import get_provider

    provider = get_provider(disable_cloud_ai=True)
    assert provider.name == "offline"
    return provider


@pytest.fixture()
def bank():
    """The real seed question bank, parsed into QuestionBankItem models."""
    from app.api.routes_sessions import load_bank

    items = load_bank()
    assert items, "seed question bank must load"
    return items


@pytest.fixture(scope="session")
def mini_wiki_index():
    """Build a REAL FAISS index from tests/fixtures/mini_wiki (once/session).

    Loads the MiniLM embedding model; tests depending on this fixture should
    be marked ``slow``.
    """
    from app.rag.indexer import build_index

    out_dir = _SESSION_TMP / "mini_wiki_index"
    if not (out_dir / "index.faiss").is_file():
        n_files, n_chunks = build_index(
            str(FIXTURES_DIR / "mini_wiki"), str(out_dir), verbose=False
        )
        assert n_files == 3, "expected the 3 fixture markdown files"
        assert n_chunks > 0, "fixture wiki must produce chunks"
    return str(out_dir)


@pytest.fixture()
def mock_httpx(monkeypatch):
    """Install a fake ``httpx.Client`` serving canned pages (NO network).

    Usage: ``mock_httpx({url: html_or_exception, ...})``. URLs not in the map
    raise (simulating unreachable hosts). The research agent imports httpx
    lazily and looks up ``httpx.Client`` at call time, so this patch reaches
    it; starlette's TestClient subclass binding is unaffected.
    """
    import httpx

    def _install(pages):
        class _FakeResponse:
            def __init__(self, text):
                self.text = text
                self.status_code = 200

            def raise_for_status(self):
                return None

        class _FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def get(self, url, **kwargs):
                # accepts timeout=... like the real httpx.Client.get
                if url not in pages:
                    raise ConnectionError("blocked in tests: {0}".format(url))
                value = pages[url]
                if isinstance(value, Exception):
                    raise value
                return _FakeResponse(value)

        monkeypatch.setattr(httpx, "Client", _FakeClient)
        return _FakeClient

    return _install


ANSWER_GOOD = (
    "First, let me restate the problem. The core idea is to compare the "
    "options systematically: I would start from the definition, explain how "
    "the method works step by step, and then discuss the trade-offs. For "
    "example, in practice you monitor the key metric in production and run "
    "an A/B test with a clear hypothesis, because the business impact "
    "depends on statistical significance, sample size, and the variance of "
    "the distribution. However, there is a trade-off between speed and "
    "rigor: a longer experiment gives tighter confidence intervals at the "
    "cost of time. Finally, to summarize, I would validate assumptions, "
    "quantify uncertainty with a p-value or confidence interval, and "
    "communicate the limitations and alternatives clearly to stakeholders."
)


@pytest.fixture()
def completed_session(client, make_session, db):
    """Factory: drive a session to completion through the orchestrator.

    Returns the session id. Answers every question (plus the final
    candidate-questions wrap-up) with a substantive text.
    """
    from app.core.orchestrator import InterviewOrchestrator
    from app.models import InterviewSession

    def _run(**overrides):
        sess = make_session(**overrides)
        sid = sess["id"]
        orch = InterviewOrchestrator(sid)
        orch.handle(db, {"type": "start"})
        for i in range(40):  # generous upper bound; Quick Practice needs ~3
            row = db.get(InterviewSession, sid)
            if row.status == "completed":
                break
            orch.handle(
                db,
                {
                    "type": "answer",
                    "text": ANSWER_GOOD,
                    "duration_seconds": 30.0 + i,
                    "input_mode": "text",
                },
            )
        row = db.get(InterviewSession, sid)
        assert row.status == "completed"
        return sid

    return _run
