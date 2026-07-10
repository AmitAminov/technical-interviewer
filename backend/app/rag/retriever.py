"""FAISS-backed wiki retriever (DESIGN.md §7 pinned interface).

``WikiRetriever`` lazily loads the embedding model and index on the first
``search`` call. When the index directory (or its artifacts) is missing it
never raises: ``loaded`` is False and ``search`` returns ``[]``.
"""
from __future__ import annotations

import os

os.environ.setdefault("USE_TF", "0")  # must precede any ML import

import json  # noqa: E402
import logging  # noqa: E402
import threading  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Dict, List, Optional  # noqa: E402

from ..config import settings  # noqa: E402
from ..schemas import RagResult  # noqa: E402

logger = logging.getLogger(__name__)


def _resolve_index_dir() -> str:
    """Honor TI_WIKI_INDEX_DIR at call time (tests point it at fixtures)."""
    return os.environ.get("TI_WIKI_INDEX_DIR") or settings.wiki_index_dir


class WikiRetriever:
    """Semantic search over the persisted wiki index."""

    def __init__(self, index_dir: Optional[str] = None) -> None:
        # Default is settings.wiki_index_dir, resolved at construction time so
        # the TI_WIKI_INDEX_DIR env override is honored.
        self.index_dir = Path(index_dir if index_dir is not None
                              else _resolve_index_dir())
        self._index = None
        self._chunks: Optional[List[Dict[str, str]]] = None
        self._model = None
        self._load_failed = False
        # Serializes the lazy first load. Without it, the startup warm-up
        # thread and an early request thread race through the load path,
        # constructing the embedding model twice; if either attempt fails,
        # its except branch used to null out the other thread's successful
        # load and latch _load_failed, silently disabling the retriever for
        # the process lifetime.
        self._load_lock = threading.Lock()

    # ------------------------------------------------------------- internals
    @property
    def _index_path(self) -> Path:
        return self.index_dir / "index.faiss"

    @property
    def _chunks_path(self) -> Path:
        return self.index_dir / "chunks.json"

    def _artifacts_exist(self) -> bool:
        try:
            return self._index_path.is_file() and self._chunks_path.is_file()
        except OSError:  # pragma: no cover - exotic path errors
            return False

    def _ensure_loaded(self) -> bool:
        if self._index is not None:
            return True
        with self._load_lock:
            # Re-check under the lock: another thread may have just loaded
            # (or failed to load) while we were waiting.
            if self._index is not None:
                return True
            if self._load_failed or not self._artifacts_exist():
                return False
            try:
                import faiss

                from .indexer import get_embedding_model

                index = faiss.read_index(str(self._index_path))
                chunks = json.loads(
                    self._chunks_path.read_text(encoding="utf-8")
                )
                model = get_embedding_model()
                self._index, self._chunks, self._model = index, chunks, model
                return True
            except Exception:
                logger.warning(
                    "wiki index load failed (dir=%s)", self.index_dir,
                    exc_info=True,
                )
                self._load_failed = True
                self._index = None
                self._chunks = None
                self._model = None
                return False

    # -------------------------------------------------------------- pinned API
    @property
    def loaded(self) -> bool:
        """True when the index is loaded or loadable (artifacts on disk)."""
        if self._index is not None:
            return True
        return (not self._load_failed) and self._artifacts_exist()

    def search(self, query: str, k: int = 5) -> List[RagResult]:
        """Top-k semantic search. Returns [] when unavailable; never raises."""
        if not query or not query.strip() or k <= 0:
            return []
        if not self._ensure_loaded():
            return []
        try:
            import numpy as np

            emb = self._model.encode(
                [query.strip()],
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            ).astype(np.float32)
            ntotal = int(self._index.ntotal)
            if ntotal == 0:
                return []
            scores, idxs = self._index.search(emb, min(k, ntotal))
            results: List[RagResult] = []
            for score, idx in zip(scores[0], idxs[0]):
                if idx < 0 or idx >= len(self._chunks):
                    continue
                chunk = self._chunks[int(idx)]
                results.append(RagResult(
                    text=chunk.get("text", ""),
                    source=chunk.get("source", ""),
                    score=float(score),
                ))
            return results
        except Exception:
            logger.warning(
                "wiki search failed (dir=%s)", self.index_dir, exc_info=True
            )
            return []


_RETRIEVERS: Dict[str, WikiRetriever] = {}
_RETRIEVERS_LOCK = threading.Lock()


def get_retriever() -> WikiRetriever:
    """Cached singleton per resolved index dir (safe when no index exists)."""
    index_dir = _resolve_index_dir()
    try:
        key = str(Path(index_dir).resolve())
    except OSError:  # pragma: no cover
        key = str(index_dir)
    with _RETRIEVERS_LOCK:
        if key not in _RETRIEVERS:
            _RETRIEVERS[key] = WikiRetriever(index_dir)
        return _RETRIEVERS[key]
