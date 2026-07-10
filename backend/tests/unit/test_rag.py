"""Unit tests: RAG over the mini-wiki fixture index + safe unloaded paths."""
from __future__ import annotations

import pytest

from app.rag.retriever import WikiRetriever, get_retriever
from app.schemas import RagResult


# --------------------------------------------------------- unloaded (fast)
def test_unloaded_retriever_returns_empty(tmp_path):
    retriever = WikiRetriever(index_dir=str(tmp_path / "nowhere"))
    assert retriever.loaded is False
    assert retriever.search("gradient descent", k=3) == []


def test_get_retriever_singleton_is_safe_without_index():
    r1 = get_retriever()
    r2 = get_retriever()
    assert r1 is r2  # cached singleton per index dir
    # default test env points at an empty dir -> unloaded but safe
    assert r1.search("anything at all", k=2) == []


def test_search_rejects_blank_query_and_bad_k(tmp_path):
    retriever = WikiRetriever(index_dir=str(tmp_path))
    assert retriever.search("", k=5) == []
    assert retriever.search("   ", k=5) == []
    assert retriever.search("query", k=0) == []


# ------------------------------------------------- real fixture index (slow)
@pytest.mark.slow
def test_fixture_index_returns_relevant_result(mini_wiki_index):
    retriever = WikiRetriever(index_dir=mini_wiki_index)
    assert retriever.loaded is True
    results = retriever.search(
        "How does gradient descent minimize a loss function during training?", k=2
    )
    assert results, "seeded query must return results"
    assert all(isinstance(r, RagResult) for r in results)
    top = results[0]
    assert top.source == "concepts/gradient-descent.md"
    assert "gradient" in top.text.lower()
    assert isinstance(top.score, float)


@pytest.mark.slow
def test_fixture_index_distinguishes_topics(mini_wiki_index):
    retriever = WikiRetriever(index_dir=mini_wiki_index)
    sql = retriever.search("What is the difference between an inner and a left join in SQL?", k=1)
    assert sql and sql[0].source == "concepts/sql-joins.md"
    attn = retriever.search("Why do transformers use scaled dot product self-attention?", k=1)
    assert attn and attn[0].source == "concepts/transformer-attention.md"


@pytest.mark.slow
def test_search_respects_k(mini_wiki_index):
    retriever = WikiRetriever(index_dir=mini_wiki_index)
    assert len(retriever.search("machine learning optimization", k=2)) <= 2
    assert len(retriever.search("machine learning optimization", k=1)) == 1


@pytest.mark.slow
def test_concurrent_first_search_loads_index_exactly_once(mini_wiki_index):
    """Regression: the lazy first load must be thread-safe.

    The startup warm-up thread and an early request thread used to race
    through ``_ensure_loaded`` simultaneously, constructing the embedding
    model twice; a failure in either racer nulled the other's successful
    load and latched ``_load_failed``, silently disabling the retriever for
    the process lifetime (empty wiki_refs everywhere despite a healthy
    index). With the load serialized, N concurrent first searches perform
    exactly one load and all return results.
    """
    import threading
    import time

    from app.rag import indexer

    real_get_model = indexer.get_embedding_model
    load_calls = []

    def slow_counting_get_model(model_name=None):
        load_calls.append(threading.current_thread().name)
        time.sleep(0.3)  # widen the race window
        return real_get_model(model_name)

    retriever = WikiRetriever(index_dir=mini_wiki_index)
    n = 4
    barrier = threading.Barrier(n)
    results = {}

    def worker(name):
        barrier.wait()
        results[name] = retriever.search("gradient descent optimization", k=2)

    original = indexer.get_embedding_model
    indexer.get_embedding_model = slow_counting_get_model
    try:
        threads = [
            threading.Thread(target=worker, args=(str(i),)) for i in range(n)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        indexer.get_embedding_model = original

    assert len(load_calls) == 1, (
        "concurrent first searches must load the index exactly once, "
        "got {0} loads".format(len(load_calls))
    )
    assert retriever.loaded is True
    assert retriever._load_failed is False
    for name, res in results.items():
        assert res, "thread {0} must get search results".format(name)


@pytest.mark.slow
def test_rag_search_endpoint_with_fixture_index(client, mini_wiki_index, monkeypatch):
    monkeypatch.setenv("TI_WIKI_INDEX_DIR", mini_wiki_index)
    resp = client.post(
        "/api/rag/search",
        json={"query": "gradient descent learning rate schedules", "k": 2},
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert results
    assert {"text", "source", "score"} <= set(results[0])
    assert results[0]["source"].startswith("concepts/")


def test_rag_search_endpoint_without_index(client):
    resp = client.post("/api/rag/search", json={"query": "anything", "k": 3})
    assert resp.status_code == 200
    assert resp.json() == {"results": []}


def test_rag_search_endpoint_validates_payload(client):
    resp = client.post("/api/rag/search", json={"query": "", "k": 3})
    assert resp.status_code == 422
    resp = client.post("/api/rag/search", json={"query": "x", "k": 0})
    assert resp.status_code == 422


# ----------------------------------------------------------------- chunking
def test_chunk_markdown_skips_link_lists():
    from app.rag.indexer import chunk_markdown

    text = (
        "# Page\n\nThis section explains a concept in enough words to form a "
        "substantial chunk of meaningful prose about optimization methods and "
        "their behavior in practice today.\n\n"
        "## Related pages\n\n- [[a-link]]\n- [[another-link]]\n- [[third]]\n"
    )
    chunks = chunk_markdown(text, "concepts/page.md")
    assert chunks, "prose section must chunk"
    assert all("[[a-link]]" not in c["text"] for c in chunks)
    assert all(c["source"] == "concepts/page.md" for c in chunks)
