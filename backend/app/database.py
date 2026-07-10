"""SQLAlchemy engine / session factory (SQLite at backend/data/app.db).

Owner: Agent A (backend-core). See DESIGN.md §1, §5.
"""
from __future__ import annotations

import logging
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import ensure_data_dir, settings

logger = logging.getLogger(__name__)

Base = declarative_base()


def _build_engine():
    ensure_data_dir()
    url = settings.database_url
    kwargs = {}
    if url.startswith("sqlite"):
        # WS handler + background report threads touch the DB from worker threads.
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url:
            # Share the single in-memory database across threads (tests).
            kwargs["poolclass"] = StaticPool
    return create_engine(url, future=True, **kwargs)


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    """Create all tables (idempotent)."""
    # Import models so their tables are registered on Base.metadata.
    from . import models  # noqa: F401

    ensure_data_dir()
    Base.metadata.create_all(bind=engine)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one ORM session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
