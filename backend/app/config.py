"""Pinned app configuration (architecture contract, DESIGN.md)."""
import os

# Must be set before any transformers/sentence_transformers import anywhere.
os.environ.setdefault("USE_TF", "0")

from pathlib import Path  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
DATA_DIR = Path(os.environ.get("TI_DATA_DIR", str(BACKEND_DIR / "data")))


class Settings:
    app_name: str = "Technical Interviewer"
    version: str = "1.0.0"
    host: str = "127.0.0.1"
    port: int = 8011

    data_dir: str = str(DATA_DIR)
    database_url: str = os.environ.get(
        "TI_DATABASE_URL", f"sqlite:///{DATA_DIR / 'app.db'}"
    )
    secret_key_path: str = str(DATA_DIR / "secret.key")
    question_bank_path: str = str(DATA_DIR / "question_bank.json")
    internet_bank_path: str = str(DATA_DIR / "question_bank_internet.json")
    wiki_index_dir: str = os.environ.get(
        "TI_WIKI_INDEX_DIR", str(DATA_DIR / "wiki_index")
    )
    # Optional local knowledge base for RAG grounding (markdown files).
    # Point TI_WIKI_DIR at your own notes/wiki and run scripts/index_wiki.py.
    # When absent, the app still works — the retriever reports "unloaded" and
    # every consumer degrades gracefully (no wiki grounding, no errors).
    wiki_dir: str = os.environ.get("TI_WIKI_DIR", str(PROJECT_ROOT / "wiki"))
    embedding_model: str = os.environ.get(
        "TI_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
    )

    voice_server_url: str = os.environ.get("TI_VOICE_URL", "http://127.0.0.1:8012")

    anthropic_model: str = os.environ.get("TI_ANTHROPIC_MODEL", "claude-sonnet-4-6")
    # Gemini (barge-in reply) runs on Vertex AI, authenticated via the project's
    # Application Default Credentials — no API key is stored. Project defaults to
    # the user's GCP project; override with TI_GCP_PROJECT / TI_GCP_LOCATION.
    gcp_project: str = os.environ.get("TI_GCP_PROJECT", "radiant-mason-467110-u5")
    gcp_location: str = os.environ.get("TI_GCP_LOCATION", "us-central1")
    gemini_model: str = os.environ.get("TI_GEMINI_MODEL", "gemini-2.5-flash")
    disable_claude_cli: bool = os.environ.get("TI_DISABLE_CLAUDE_CLI", "") == "1"
    llm_timeout_seconds: float = float(os.environ.get("TI_LLM_TIMEOUT", "20"))
    research_time_cap_seconds: float = 8.0

    hint_penalty_per_hint: float = 0.15
    silence_checkin_seconds: float = 12.0

    frontend_dist: str = str(PROJECT_ROOT / "frontend" / "dist")


settings = Settings()


def ensure_data_dir() -> None:
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
