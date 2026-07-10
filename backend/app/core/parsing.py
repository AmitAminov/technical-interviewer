"""Resume & job-description parsing → skills/topics (DESIGN.md §1 core/parsing).

``parse_resume`` accepts raw bytes (PDF via pypdf, or text) or an already
decoded string; ``parse_job_description`` accepts plain text. Both return
``{"raw_text": str, "skills": [..], "topics": [..]}`` and never raise on
empty/garbage input.

Skill extraction is vocabulary-based: the exact TRACK_TOPICS lists from the
contract plus a curated set of common tech keywords, matched case-insensitively
on word boundaries.
"""
from __future__ import annotations

import base64
import binascii
import io
import logging
import re
from typing import Dict, List, Optional, Union

from ..schemas import TRACK_TOPICS

logger = logging.getLogger(__name__)

# Common tech keywords beyond the track-topic vocabulary (canonical casing).
TECH_KEYWORDS: List[str] = [
    "Python", "R", "SQL", "Java", "C++", "Scala", "Julia", "Go", "Rust",
    "PyTorch", "TensorFlow", "Keras", "scikit-learn", "sklearn", "XGBoost",
    "LightGBM", "CatBoost", "pandas", "NumPy", "SciPy", "statsmodels",
    "Matplotlib", "Seaborn", "Plotly", "Tableau", "Power BI",
    "Spark", "Hadoop", "Kafka", "Airflow", "dbt", "Snowflake", "BigQuery",
    "Redshift", "Databricks", "Docker", "Kubernetes", "Terraform",
    "AWS", "GCP", "Azure", "SageMaker", "Vertex AI",
    "MLflow", "Weights & Biases", "wandb", "Kubeflow", "Ray",
    "Hugging Face", "transformers", "LangChain", "LlamaIndex", "OpenAI",
    "Anthropic", "Claude", "GPT", "BERT", "T5", "LLaMA", "Mistral",
    "FAISS", "Pinecone", "Weaviate", "Milvus", "Chroma", "Elasticsearch",
    "PostgreSQL", "MySQL", "MongoDB", "Redis", "Neo4j",
    "FastAPI", "Flask", "Django", "gRPC", "REST",
    "Git", "CI/CD", "Linux", "Bash",
    "NLP", "computer vision", "CV", "reinforcement learning", "RL",
    "time series", "forecasting", "recommendation systems", "recommender",
    "anomaly detection", "causal inference", "Bayesian", "MCMC",
    "CUDA", "GPU", "ONNX", "TensorRT", "quantization", "distillation",
    "LoRA", "PEFT", "RLHF", "prompt engineering", "vector database",
    "ETL", "data pipeline", "feature store", "A/B testing",
    "hypothesis testing", "regression", "classification", "clustering",
    "neural network", "CNN", "RNN", "LSTM", "GAN", "diffusion",
    "attention", "self-attention", "embedding", "tokenization",
]


def _all_topics() -> List[str]:
    seen: List[str] = []
    for topics in TRACK_TOPICS.values():
        for t in topics:
            if t not in seen:
                seen.append(t)
    return seen


_TOPIC_VOCAB = _all_topics()


def _keyword_pattern(term: str) -> "re.Pattern":
    """Word-boundary regex for a vocabulary term (handles 'C++', 'CI/CD')."""
    escaped = re.escape(term)
    # \b doesn't work after '+' or '/', so use lookarounds on word chars.
    return re.compile(
        r"(?<![A-Za-z0-9_])" + escaped + r"(?![A-Za-z0-9_])", re.IGNORECASE
    )


def _extract_terms(text: str, vocab: List[str]) -> List[str]:
    found: List[str] = []
    if not text:
        return found
    for term in vocab:
        try:
            if _keyword_pattern(term).search(text):
                found.append(term)
        except re.error:  # pragma: no cover - defensive
            continue
    return found


_DATA_URL_RE = re.compile(
    r"^data:(?P<mime>[\w.+-]+/[\w.+-]+)?(;charset=[\w-]+)?;base64,(?P<b64>.*)$",
    re.DOTALL,
)


def _decode_bytes(data: bytes) -> str:
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, ValueError):
            continue
    return data.decode("utf-8", errors="replace")


def _extract_pdf_text(data: bytes) -> str:
    """Extract text from PDF bytes via pypdf; returns '' on any failure."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        pages: List[str] = []
        for page in reader.pages:
            try:
                pages.append(page.extract_text() or "")
            except Exception:  # noqa: BLE001 - single bad page must not abort
                continue
        return "\n".join(pages).strip()
    except Exception:  # noqa: BLE001
        logger.warning("PDF text extraction failed", exc_info=True)
        return ""


def _analyze(raw_text: str) -> Dict[str, object]:
    raw_text = (raw_text or "").strip()
    # Clamp pathological inputs; vocabulary scan is linear in text size.
    scan_text = raw_text[:200_000]
    topics = _extract_terms(scan_text, _TOPIC_VOCAB)
    skills = _extract_terms(scan_text, TECH_KEYWORDS)
    # Topics are also skills for downstream consumers; dedupe preserving order.
    merged_skills: List[str] = []
    for s in skills + topics:
        if s not in merged_skills:
            merged_skills.append(s)
    return {"raw_text": raw_text, "skills": merged_skills, "topics": topics}


def parse_resume(
    data: Union[bytes, str, None], filename: Optional[str] = None
) -> Dict[str, object]:
    """Parse a resume (.pdf via pypdf, or plain text) into skills/topics.

    Returns ``{"raw_text", "skills", "topics"}``. Never raises on empty or
    garbage input — a failed parse yields empty fields.
    """
    if data is None:
        return {"raw_text": "", "skills": [], "topics": []}
    if isinstance(data, str):
        # The frontend uploads .pdf resumes as a base64 data URL inside the
        # resume_text string field (contract only carries a string).
        m = _DATA_URL_RE.match(data.strip())
        if m:
            try:
                data = base64.b64decode(m.group("b64"), validate=False)
            except (binascii.Error, ValueError):
                return {"raw_text": "", "skills": [], "topics": []}
        else:
            return _analyze(data)
    name = (filename or "").lower()
    is_pdf = name.endswith(".pdf") or data[:5] == b"%PDF-"
    text = _extract_pdf_text(data) if is_pdf else _decode_bytes(data)
    return _analyze(text)


def parse_job_description(text: Optional[str]) -> Dict[str, object]:
    """Parse a job description string into the same shape as parse_resume."""
    if not text:
        return {"raw_text": "", "skills": [], "topics": []}
    return _analyze(str(text))
