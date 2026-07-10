"""Internet research agent (DESIGN.md §7) — untrusted-content hardened.

Fetched page text is DATA, never instructions: scripts/styles are stripped,
injection-looking lines are removed by :func:`sanitize_untrusted`, and only
question-like factual lines are extracted. Every fetched URL is logged as a
:class:`SourceCitationOut` (including rejected ones). The whole run is capped
at ``settings.research_time_cap_seconds`` (8s) and all network errors are
swallowed — partial or empty results are returned, never an exception.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Tuple

from ..config import ensure_data_dir, settings
from ..schemas import TRACK_TOPICS, QuestionBankItem, SourceCitationOut

# Curated seed URLs per role: official docs, educational resources, and
# reputable engineering blogs / community collections only.
_SEED_URLS = {
    "Data Scientist": [
        ("https://github.com/alexeygrigorev/data-science-interviews",
         "Data science interview questions (community collection)"),
        ("https://scikit-learn.org/stable/modules/model_evaluation.html",
         "scikit-learn: model evaluation guide"),
        ("https://developers.google.com/machine-learning/guides/rules-of-ml",
         "Google: Rules of Machine Learning"),
    ],
    "Algorithm Researcher": [
        ("https://cp-algorithms.com/",
         "cp-algorithms: competitive programming algorithm reference"),
        ("https://en.wikipedia.org/wiki/Analysis_of_algorithms",
         "Wikipedia: Analysis of algorithms"),
        ("https://github.com/jwasham/coding-interview-university",
         "Coding Interview University (community study guide)"),
    ],
    "AI Engineer": [
        ("https://huggingface.co/docs/transformers/llm_tutorial",
         "Hugging Face: LLM generation tutorial"),
        ("https://lilianweng.github.io/posts/2023-06-23-agent/",
         "Lilian Weng: LLM-powered autonomous agents"),
        ("https://www.anthropic.com/engineering/building-effective-agents",
         "Anthropic Engineering: building effective agents"),
    ],
}

_ROLE_ABBREV = {"Data Scientist": "ds", "Algorithm Researcher": "ar",
                "AI Engineer": "ai"}

# Prompt-injection patterns (case-insensitive), matched per line.
_INJECTION_RE = re.compile(
    r"(ignore\s+(all\s+)?previous\s+instructions"
    r"|disregard\s+.*instructions"
    r"|you\s+are\s+now"
    r"|system\s+prompt"
    r"|<\s*system"
    r"|BEGIN\s+INSTRUCTIONS"
    r"|do\s+anything\s+now)",
    re.IGNORECASE,
)

_MAX_SANITIZED_CHARS = 20000

# Generic role-relevant keywords, in addition to the track topic tokens.
_GENERIC_KEYWORDS = {
    "Data Scientist": ["data", "model", "metric", "regression", "hypothesis",
                       "sample", "distribution", "experiment", "test"],
    "Algorithm Researcher": ["algorithm", "complexity", "graph", "array",
                             "tree", "sort", "search", "proof", "optimal"],
    "AI Engineer": ["model", "llm", "training", "inference", "neural",
                    "prompt", "token", "gpu", "embedding", "agent"],
}


def contains_injection(text: str) -> bool:
    """True when the text matches any known prompt-injection pattern."""
    return bool(text) and bool(_INJECTION_RE.search(text))


def sanitize_untrusted(text: str, max_chars: int = _MAX_SANITIZED_CHARS) -> str:
    """Remove injection-looking lines from untrusted text and cap its length.

    The result is safe to embed in LLM prompts *as data*; instructions found
    in web content must never be executed.
    """
    if not text:
        return ""
    clean_lines = [line for line in text.splitlines()
                   if not _INJECTION_RE.search(line)]
    return "\n".join(clean_lines)[:max_chars]


def _role_keywords(role: str) -> List[str]:
    keywords = set(_GENERIC_KEYWORDS.get(role, []))
    keywords.update(w.casefold() for w in role.split())
    for topic in TRACK_TOPICS.get(role, []):
        for tok in re.findall(r"[a-z0-9/]+", topic.casefold()):
            if len(tok) >= 3:
                keywords.add(tok)
    return sorted(keywords)


def _extract_page(html: str) -> Tuple[str, str]:
    """(title, visible_text) with script/style/nav noise stripped via bs4."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.get_text(strip=True) if soup.title else "")[:200]
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript",
                     "iframe", "form", "svg"]):
        tag.decompose()
    return title, soup.get_text("\n")


def _question_lines(text: str, role: str) -> List[str]:
    """Question-like lines: end with '?', 8-60 words, role-relevant keyword."""
    keywords = _role_keywords(role)
    out: List[str] = []
    seen = set()
    for raw in text.splitlines():
        line = raw.strip().lstrip("-*+#>|").strip()
        line = re.sub(r"^\d+[\.\)]\s*", "", line).strip()
        if not line.endswith("?"):
            continue
        n_words = len(line.split())
        if not (8 <= n_words <= 60):
            continue
        cf = line.casefold()
        if not any(k in cf for k in keywords):
            continue
        key = cf
        if key in seen:
            continue
        seen.add(key)
        out.append(line)
    return out


def _best_topic(question: str, role: str) -> str:
    """Track topic whose tokens best overlap the question text."""
    cf = question.casefold()
    topics = TRACK_TOPICS.get(role, [])
    best, best_score = (topics[0] if topics else "General"), 0
    for topic in topics:
        tokens = [t for t in re.findall(r"[a-z0-9/]+", topic.casefold())
                  if len(t) >= 3]
        score = sum(1 for t in tokens if t in cf)
        if topic.casefold() in cf:
            score += 2
        if score > best_score:
            best, best_score = topic, score
    return best


def _make_item(question: str, role: str, difficulty: str) -> QuestionBankItem:
    digest = hashlib.md5(question.casefold().encode("utf-8")).hexdigest()[:8]
    return QuestionBankItem(
        id="net-%s-%s" % (_ROLE_ABBREV.get(role, "xx"), digest),
        role=role,
        topic=_best_topic(question, role),
        difficulty=difficulty,
        question_text=question,
        expected_points=[],
        followups=[],
        is_behavioral=False,
        source="internet",
    )


def _citation(url: str, title: str, quality: str, notes: str,
              session_id: Optional[str]) -> SourceCitationOut:
    return SourceCitationOut(
        id=str(uuid.uuid4()),
        session_id=session_id,
        url=url,
        title=title,
        quality=quality,  # type: ignore[arg-type]
        fetched_at=datetime.now(timezone.utc),
        notes=notes,
    )


def research_questions(role: str, difficulty: str, allow_internet: bool,
                       provider, session_id: Optional[str] = None
                       ) -> Tuple[List[QuestionBankItem],
                                  List[SourceCitationOut]]:
    """Fetch curated sources and extract interview questions (pinned API).

    ``allow_internet=False`` returns ``([], [])`` immediately. Otherwise the
    run is bounded by an overall wall-clock cap and every failure is degraded
    to a rejected citation or simply skipped — this function never raises.
    """
    if not allow_internet:
        return [], []

    items: List[QuestionBankItem] = []
    citations: List[SourceCitationOut] = []
    deadline = time.monotonic() + float(settings.research_time_cap_seconds)

    try:
        import httpx

        timeout = httpx.Timeout(5.0, connect=3.0)
        headers = {"User-Agent": "TechnicalInterviewer/1.0 (research-agent)"}
        with httpx.Client(timeout=timeout, follow_redirects=True,
                          headers=headers) as client:
            for url, default_title in _SEED_URLS.get(role, []):
                remaining = deadline - time.monotonic()
                if remaining < 0.5:
                    break
                try:
                    # Clamp the per-request timeout to the remaining budget
                    # so total wall clock stays inside the 8s cap even when
                    # a server trickles bytes (DESIGN.md §7).
                    resp = client.get(url, timeout=httpx.Timeout(
                        min(5.0, remaining), connect=min(3.0, remaining)))
                    resp.raise_for_status()
                    html = resp.text
                except Exception as exc:
                    citations.append(_citation(
                        url, default_title, "rejected",
                        "fetch failed: %s" % type(exc).__name__, session_id))
                    continue
                try:
                    title, raw_text = _extract_page(html)
                except Exception:
                    citations.append(_citation(
                        url, default_title, "rejected",
                        "could not parse page content", session_id))
                    continue
                flagged = contains_injection(raw_text)
                clean = sanitize_untrusted(raw_text)
                questions = _question_lines(clean, role)
                if flagged:
                    quality, notes = "rejected", (
                        "content flagged for prompt-injection patterns; "
                        "extracted text discarded")
                    questions = []
                elif not questions:
                    quality, notes = "rejected", "no usable questions extracted"
                elif len(questions) >= 3:
                    quality, notes = "high", "%d questions extracted" % len(questions)
                else:
                    quality, notes = "medium", "%d questions extracted" % len(questions)
                citations.append(_citation(url, title or default_title,
                                           quality, notes, session_id))
                for q in questions[:5]:
                    items.append(_make_item(q, role, difficulty))
    except Exception:
        # Any unexpected failure (httpx missing, DNS storms, ...) degrades to
        # whatever was collected so far.
        pass

    # De-duplicate by id (hash of casefolded question text).
    unique: List[QuestionBankItem] = []
    seen_ids = set()
    for item in items:
        if item.id not in seen_ids:
            seen_ids.add(item.id)
            unique.append(item)
    return unique, citations


def merge_into_internet_bank(items: List[QuestionBankItem]) -> int:
    """Append de-duplicated items to the persistent internet question bank.

    Returns the number of newly added items. Failures are swallowed (returns
    the count merged before the failure, or 0).
    """
    if not items:
        return 0
    try:
        ensure_data_dir()
        path = Path(settings.internet_bank_path)
        existing: List[dict] = []
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    existing = data
            except (json.JSONDecodeError, OSError):
                existing = []
        seen_ids = {e.get("id") for e in existing if isinstance(e, dict)}
        seen_texts = {str(e.get("question_text", "")).casefold()
                      for e in existing if isinstance(e, dict)}
        added = 0
        for item in items:
            if item.id in seen_ids:
                continue
            if item.question_text.casefold() in seen_texts:
                continue
            existing.append(item.model_dump())
            seen_ids.add(item.id)
            seen_texts.add(item.question_text.casefold())
            added += 1
        if added:
            path.write_text(json.dumps(existing, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        return added
    except Exception:
        return 0
