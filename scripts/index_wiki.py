"""Build the FAISS wiki index (DESIGN.md §1 [B]).

Usage (from the project root)::

    python scripts/index_wiki.py                      # concepts/ only (fast)
    python scripts/index_wiki.py --include-sources    # concepts/ + sources/
    python scripts/index_wiki.py --wiki-dir D:/wiki --out-dir backend/data/wiki_index
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("USE_TF", "0")  # before any ML import

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.config import settings  # noqa: E402
from app.rag.indexer import build_index  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the wiki FAISS index.")
    parser.add_argument("--wiki-dir", default=settings.wiki_dir,
                        help="Wiki root directory (default: %(default)s)")
    parser.add_argument("--out-dir", default=settings.wiki_index_dir,
                        help="Output index directory (default: %(default)s)")
    parser.add_argument("--subdirs", default="concepts",
                        help="Comma-separated wiki subdirs to index "
                             "(default: concepts)")
    parser.add_argument("--include-sources", action="store_true",
                        help="Also index the sources/ subdir")
    args = parser.parse_args()

    wiki_dir = Path(args.wiki_dir)
    if not wiki_dir.is_dir():
        print("ERROR: wiki dir not found: %s" % wiki_dir)
        return 1

    subdirs = [s.strip() for s in args.subdirs.split(",") if s.strip()]
    if args.include_sources and "sources" not in subdirs:
        subdirs.append("sources")

    print("Indexing wiki: %s" % wiki_dir)
    print("Subdirs: %s" % ", ".join(subdirs))
    print("Output:  %s" % args.out_dir)
    t0 = time.perf_counter()
    n_files, n_chunks = build_index(str(wiki_dir), str(args.out_dir),
                                    subdirs=subdirs, verbose=True)
    dt = time.perf_counter() - t0
    print("Done in %.1fs — indexed %d files into %d chunks."
          % (dt, n_files, n_chunks))
    return 0 if n_chunks > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
