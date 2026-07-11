"""FastAPI application entrypoint (DESIGN.md §1, §3, §4).

- REST routers under /api, WebSocket at /ws/interview/{session_id}.
- CORS for the Vite dev server (localhost:5173).
- Serves ../frontend/dist statically at / when it exists, with an SPA
  fallback to index.html for non-/api, non-/ws paths.
- Startup: ensure data dir + create tables.

Must import cleanly even when Agent-B packages (app.llm/app.rag/app.agents)
are absent — all such imports are function-level throughout the app.
"""
from __future__ import annotations

import logging
import os
import threading

# Defensive: before any (transitive) ML import.
os.environ.setdefault("USE_TF", "0")

from pathlib import Path  # noqa: E402

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402

from .api import (  # noqa: E402
    routes_misc,
    routes_privacy,
    routes_reports,
    routes_sessions,
    routes_users,
    routes_voice,
)
from .config import ensure_data_dir, settings  # noqa: E402
from .database import init_db  # noqa: E402
from .ws import interview_ws  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, version=settings.version)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:{0}".format(settings.port),
            "http://127.0.0.1:{0}".format(settings.port),
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # REST routers (paths are declared absolute inside each router).
    app.include_router(routes_misc.router)
    app.include_router(routes_users.router)
    app.include_router(routes_sessions.router)
    app.include_router(routes_reports.router)
    app.include_router(routes_privacy.router)
    app.include_router(routes_voice.router)
    # WebSocket.
    app.include_router(interview_ws.router)

    @app.on_event("startup")
    def _startup() -> None:
        ensure_data_dir()
        init_db()
        _warm_retriever_async()
        logger.info(
            "%s v%s started (data dir: %s)",
            settings.app_name,
            settings.version,
            settings.data_dir,
        )

    _mount_frontend(app)
    return app


def _warm_retriever_async() -> None:
    """Preload the embedding model + FAISS index in the background so the
    first session's planning stays well under the 30s spec bound. No-op when
    no wiki index exists (e.g. tests)."""

    def _warm() -> None:
        try:
            from .rag.retriever import get_retriever

            r = get_retriever()
            if r.loaded:
                r.search("warm up", k=1)
                logger.info("wiki retriever warmed")
        except Exception:  # noqa: BLE001 - warm-up must never break startup
            logger.warning("retriever warm-up failed", exc_info=True)

    threading.Thread(target=_warm, name="retriever-warmup", daemon=True).start()


def _mount_frontend(app: FastAPI) -> None:
    """Serve the built SPA from ../frontend/dist when present."""
    dist = Path(settings.frontend_dist)
    if not dist.is_dir() or not (dist / "index.html").is_file():
        logger.info("frontend/dist not found — API-only mode")
        return

    dist_resolved = dist.resolve()

    def _file(path: Path, *, immutable: bool) -> FileResponse:
        # Vite fingerprints everything under assets/ with a content hash, so
        # those are safe to cache forever. Everything else — index.html above
        # all, but also manifest.json, character images and GLBs we regenerate
        # in place — must be revalidated every load; otherwise the browser keeps
        # serving a stale index.html that points at an old JS bundle and none of
        # our rebuilds ever reach the user. ETag keeps revalidation cheap (304).
        cache = (
            "public, max-age=31536000, immutable"
            if immutable
            else "no-cache, must-revalidate"
        )
        return FileResponse(str(path), headers={"Cache-Control": cache})

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        # API/WS paths that reach here are genuinely unknown endpoints.
        if full_path.startswith("api/") or full_path == "api" or full_path.startswith("ws/"):
            raise HTTPException(status_code=404, detail="not found")
        if full_path:
            candidate = (dist_resolved / full_path).resolve()
            # Path-traversal guard: only serve files inside dist.
            if (
                str(candidate).startswith(str(dist_resolved))
                and candidate.is_file()
            ):
                return _file(candidate, immutable=full_path.startswith("assets/"))
        return _file(dist_resolved / "index.html", immutable=False)

    logger.info("Serving frontend from %s", dist_resolved)


# Ensure the schema exists as soon as the app module is imported (tests use
# TestClient without always triggering startup events).
ensure_data_dir()
init_db()

app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.host, port=settings.port)
