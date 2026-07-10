"""Wiki chunking + embedding + FAISS index build (DESIGN.md §7).

Chunking: per markdown file, split on h2 (``## ``) headings, then window each
section at ~250 words with 40 words of overlap. Pure link-list sections
(Obsidian "Related pages" / "In the sources" style) are skipped. Each chunk
records its source as the path relative to the wiki root, e.g.
``concepts/backpropagation.md``.

Artifacts written to the output dir: ``index.faiss`` (IndexFlatIP over
normalized embeddings) and ``chunks.json`` (list of ``{"text","source"}``).
"""
from __future__ import annotations

import os

os.environ.setdefault("USE_TF", "0")  # must precede any ML import

import json  # noqa: E402
import re  # noqa: E402
from functools import lru_cache  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Dict, List, Optional, Sequence, Tuple  # noqa: E402

from ..config import settings  # noqa: E402

CHUNK_WORDS = 250
OVERLAP_WORDS = 40
MIN_CHUNK_WORDS = 15

_H2_SPLIT_RE = re.compile(r"^(?=##\s)", re.MULTILINE)
_BULLET_RE = re.compile(r"^\s*[-*+]\s")
_LINK_RE = re.compile(r"\[\[[^\]]*\]\]|\[[^\]]*\]\([^)]*\)")


@lru_cache(maxsize=2)
def get_embedding_model(model_name: Optional[str] = None):
    """Load (once) the sentence-transformers model on cuda if available."""
    import torch
    from sentence_transformers import SentenceTransformer

    device = "cuda" if torch.cuda.is_available() else "cpu"
    return SentenceTransformer(model_name or settings.embedding_model,
                               device=device)


def _split_h2_sections(text: str) -> List[str]:
    """Split markdown into sections at h2 headings (preamble kept as first)."""
    parts = [p for p in _H2_SPLIT_RE.split(text) if p.strip()]
    return parts if parts else ([text] if text.strip() else [])


def _is_link_list_section(section: str) -> bool:
    """True for sections that are essentially just lists of links."""
    lines = [l for l in section.splitlines() if l.strip()]
    body = [l for l in lines if not l.strip().startswith("#")]
    if not body:
        return True
    linkish = 0
    for line in body:
        has_link = "[[" in line or "](" in line
        is_bullet = bool(_BULLET_RE.match(line))
        residual = _LINK_RE.sub(" ", line)
        residual_words = len(re.findall(r"[A-Za-z0-9']+", residual))
        if (is_bullet and has_link) or (has_link and residual_words < 3):
            linkish += 1
    return linkish / float(len(body)) >= 0.7


def _substantial(chunk_text: str) -> bool:
    """Reject chunks that carry almost no prose once links are stripped."""
    residual = _LINK_RE.sub(" ", chunk_text)
    return len(re.findall(r"[A-Za-z0-9']+", residual)) >= MIN_CHUNK_WORDS


def chunk_markdown(text: str, source: str) -> List[Dict[str, str]]:
    """Chunk one markdown document into {'text','source'} dicts."""
    chunks: List[Dict[str, str]] = []
    step = CHUNK_WORDS - OVERLAP_WORDS
    for section in _split_h2_sections(text):
        if _is_link_list_section(section):
            continue
        words = section.split()
        start = 0
        while start < len(words):
            piece = " ".join(words[start:start + CHUNK_WORDS])
            if _substantial(piece):
                chunks.append({"text": piece, "source": source})
            if start + CHUNK_WORDS >= len(words):
                break
            start += step
    return chunks


def build_index(wiki_dir: str, out_dir: str,
                subdirs: Sequence[str] = ("concepts",),
                verbose: bool = True) -> Tuple[int, int]:
    """Build and persist the FAISS index. Returns (n_files, n_chunks)."""
    import numpy as np
    import faiss

    wiki = Path(wiki_dir)
    files: List[Path] = []
    for sub in subdirs:
        d = wiki / sub
        if d.is_dir():
            files.extend(sorted(d.rglob("*.md")))
        elif verbose:
            print("  [skip] subdir not found: %s" % d)

    chunks: List[Dict[str, str]] = []
    for i, path in enumerate(files):
        rel = path.relative_to(wiki).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        chunks.extend(chunk_markdown(text, rel))
        if verbose and (i + 1) % 25 == 0:
            print("  chunked %d/%d files (%d chunks so far)"
                  % (i + 1, len(files), len(chunks)))

    if verbose:
        print("Embedding %d chunks with %s ..."
              % (len(chunks), settings.embedding_model))
    model = get_embedding_model()
    dim = model.get_sentence_embedding_dimension()
    index = faiss.IndexFlatIP(dim)
    if chunks:
        emb = model.encode(
            [c["text"] for c in chunks],
            batch_size=64,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        ).astype(np.float32)
        index.add(emb)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(out / "index.faiss"))
    (out / "chunks.json").write_text(
        json.dumps(chunks, ensure_ascii=False), encoding="utf-8"
    )
    if verbose:
        print("Wrote %s (%d files, %d chunks)" % (out, len(files), len(chunks)))
    return len(files), len(chunks)
