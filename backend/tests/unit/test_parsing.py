"""Unit tests: resume (txt + real PDF bytes + garbage) and JD parsing."""
from __future__ import annotations

from app.core.parsing import parse_job_description, parse_resume

RESUME_TXT = """
Jane Doe — Data Scientist
Experience: 5 years building models in Python with pandas and scikit-learn.
Designed A/B testing frameworks, applied statistics and SQL daily,
deployed models with Docker on AWS. Deep learning side projects in PyTorch.
"""


def _minimal_pdf(text: str) -> bytes:
    """Assemble a tiny but structurally valid single-page PDF with text."""
    content = "BT /F1 24 Tf 72 720 Td ({0}) Tj ET".format(text).encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n"
        + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objs, start=1):
        offsets.append(len(out))
        out += str(i).encode("ascii") + b" 0 obj\n" + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += b"xref\n0 " + str(len(objs) + 1).encode("ascii") + b"\n"
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += ("%010d 00000 n \n" % off).encode("ascii")
    out += (
        b"trailer\n<< /Size " + str(len(objs) + 1).encode("ascii")
        + b" /Root 1 0 R >>\nstartxref\n"
        + str(xref_pos).encode("ascii") + b"\n%%EOF"
    )
    return bytes(out)


def test_parse_resume_txt_string():
    result = parse_resume(RESUME_TXT, "resume.txt")
    assert "Jane Doe" in result["raw_text"]
    assert "Python" in result["topics"]
    assert "SQL" in result["topics"]
    assert "Statistics" in result["topics"]
    assert "A/B testing" in result["topics"]
    assert "Docker" in result["skills"]
    assert "PyTorch" in result["skills"]


def test_parse_resume_txt_bytes():
    result = parse_resume(RESUME_TXT.encode("utf-8"), "resume.txt")
    assert "SQL" in result["topics"]
    assert "AWS" in result["skills"]


def test_parse_resume_pdf_bytes():
    pdf = _minimal_pdf("Skilled in Python, SQL, Statistics and Deep learning")
    result = parse_resume(pdf, "resume.pdf")
    assert "Python" in result["raw_text"]
    assert "Python" in result["topics"]
    assert "SQL" in result["topics"]
    assert "Deep learning" in result["topics"]


def test_parse_resume_pdf_detected_by_magic_bytes():
    """PDF sniffing works even without a .pdf filename."""
    pdf = _minimal_pdf("Expert in Transformers and RAG systems")
    result = parse_resume(pdf, None)
    assert "RAG" in result["topics"]


def test_parse_resume_pdf_data_url_string():
    """Frontend sends .pdf uploads as a base64 data URL in resume_text."""
    import base64

    pdf = _minimal_pdf("Skilled in Python, SQL and Model evaluation")
    data_url = "data:application/pdf;base64," + base64.b64encode(pdf).decode("ascii")
    result = parse_resume(data_url, None)
    assert "Python" in result["topics"]
    assert "SQL" in result["topics"]
    assert "data:" not in result["raw_text"]


def test_parse_resume_data_url_garbage_never_raises():
    result = parse_resume("data:application/pdf;base64,!!!not-base64!!!", None)
    assert set(result) == {"raw_text", "skills", "topics"}


def test_parse_resume_garbage_never_raises():
    for garbage in (b"\x00\x01\xffnot a pdf\x9c", b"", b"%PDF-broken\x00\x00"):
        result = parse_resume(garbage, "resume.pdf" if b"PDF" in garbage else None)
        assert set(result) == {"raw_text", "skills", "topics"}
        assert isinstance(result["skills"], list)
        assert isinstance(result["topics"], list)


def test_parse_resume_none_and_empty():
    assert parse_resume(None) == {"raw_text": "", "skills": [], "topics": []}
    assert parse_resume("")["topics"] == []


def test_parse_job_description():
    jd = (
        "We are hiring a data scientist. Must know SQL, statistics, "
        "experiment design and a/b testing; bonus for Spark and Airflow."
    )
    result = parse_job_description(jd)
    assert "SQL" in result["topics"]
    assert "Statistics" in result["topics"]  # case-insensitive matching
    assert "Experiment design" in result["topics"]
    assert "A/B testing" in result["topics"]
    assert "Spark" in result["skills"]
    assert "Airflow" in result["skills"]


def test_parse_job_description_empty():
    assert parse_job_description(None) == {"raw_text": "", "skills": [], "topics": []}
    assert parse_job_description("")["skills"] == []


def test_word_boundary_matching_no_false_positives():
    # 'Rust' must not match inside 'trust'; 'R' must not match inside words.
    result = parse_resume("I trust the process and program daily.", "r.txt")
    assert "Rust" not in result["skills"]
    assert "R" not in result["skills"]
