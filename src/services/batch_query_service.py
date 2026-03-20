"""
batch_query_service.py
======================
Service for extracting questions from uploaded files (JSON / PDF)
and running them through the RAG pipeline in sequence.
"""

from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import fitz

logger = logging.getLogger(__name__)

_QUESTION_PATTERNS = [
    re.compile(r"^\s*(?:Q|Question)\s*\.?\s*\d+[\.\):\-]\s*(.+)", re.IGNORECASE),
    re.compile(r"^\s*\d+[\.\):\-]\s*(.+\?)\s*$"),
    re.compile(r"^\s*[-•]\s*(.+\?)\s*$"),
    re.compile(r"^(.+\?)\s*$"),
]

_MIN_QUESTION_LEN = 8
_MAX_QUESTION_LEN = 1000


@dataclass
class BatchResult:
    """Container for one question's outcome within a batch."""
    question: str
    answer: Optional[str] = None
    error: Optional[str] = None
    sources: List[Dict] = field(default_factory=list)
    grade: Optional[Dict] = None
    latency_ms: float = 0.0


def extract_questions_from_json(raw_bytes: bytes) -> List[str]:
    """
    Parse a JSON file and extract a flat list of question strings.

    Accepts:
      - A JSON array of strings:        ``["Q1?", "Q2?"]``
      - An object with a questions key:  ``{"questions": ["Q1?", "Q2?"]}``

    Args:
        raw_bytes: Raw file content.

    Returns:
        List of cleaned question strings.

    Raises:
        ValueError: If the JSON structure is unrecognised or empty.
    """
    try:
        data = json.loads(raw_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"Invalid JSON file: {exc}") from exc

    questions: List[str] = []

    if isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                questions.append(item.strip())
            elif isinstance(item, dict) and "question" in item:
                questions.append(str(item["question"]).strip())
    elif isinstance(data, dict):
        for key in ("questions", "items", "data", "queries"):
            if key in data and isinstance(data[key], list):
                for item in data[key]:
                    if isinstance(item, str):
                        questions.append(item.strip())
                    elif isinstance(item, dict) and "question" in item:
                        questions.append(str(item["question"]).strip())
                break
        if not questions and "question" in data:
            questions.append(str(data["question"]).strip())

    questions = [q for q in questions if _MIN_QUESTION_LEN <= len(q) <= _MAX_QUESTION_LEN]

    if not questions:
        raise ValueError(
            "No questions found. Expected a JSON array of strings "
            'or an object with a "questions" key.'
        )

    logger.info("Extracted %d questions from JSON", len(questions))
    return questions


def extract_questions_from_pdf(raw_bytes: bytes) -> List[str]:
    """
    Extract question-like lines from a PDF file.

    Scans every page for lines that match common question patterns
    (numbered questions, bullet questions, lines ending with '?').

    Args:
        raw_bytes: Raw PDF file content.

    Returns:
        List of cleaned question strings.

    Raises:
        ValueError: If the PDF is unreadable or contains no questions.
    """
    try:
        doc = fitz.open(stream=raw_bytes, filetype="pdf")
    except Exception as exc:
        raise ValueError(f"Cannot open PDF: {exc}") from exc

    questions: List[str] = []
    seen: set = set()

    for page in doc:
        text = page.get_text("text")
        for line in text.split("\n"):
            line = line.strip()
            if not line or len(line) < _MIN_QUESTION_LEN:
                continue

            for pat in _QUESTION_PATTERNS:
                m = pat.match(line)
                if m:
                    q = m.group(1) if m.lastindex else m.group(0)
                    q = q.strip()
                    if (
                        _MIN_QUESTION_LEN <= len(q) <= _MAX_QUESTION_LEN
                        and q not in seen
                    ):
                        questions.append(q)
                        seen.add(q)
                    break

    doc.close()

    if not questions:
        raise ValueError(
            "No questions found in the PDF. Lines should end with '?' "
            "or follow patterns like 'Q1.', '1)', '- question?'."
        )

    logger.info("Extracted %d questions from PDF", len(questions))
    return questions


def extract_questions(filename: str, raw_bytes: bytes) -> List[str]:
    """
    Route to the correct extractor based on file extension.

    Args:
        filename:  Original upload filename.
        raw_bytes: Raw file content.

    Returns:
        List of question strings.

    Raises:
        ValueError: If the file type is unsupported.
    """
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    if ext == "json":
        return extract_questions_from_json(raw_bytes)
    if ext == "pdf":
        return extract_questions_from_pdf(raw_bytes)
    raise ValueError(
        f"Unsupported file type '.{ext}'. Upload a .json or .pdf file."
    )


_BATCH_WORKERS = 3


def _run_one(
    index: int,
    question: str,
    run_query_fn,
    top_k: int,
    notebook_id: str,
    total: int,
) -> BatchResult:
    """
    Execute a single question through the RAG pipeline.

    Args:
        index:        Zero-based question index (for logging).
        question:     The question text.
        run_query_fn: Callable(question, top_k, notebook_id) -> response.
        top_k:        Number of chunks to retrieve.
        notebook_id:  Notebook scope.
        total:        Total number of questions (for log messages).

    Returns:
        BatchResult for this question.
    """
    t0 = time.perf_counter()
    try:
        resp = run_query_fn(question, top_k, notebook_id)
        elapsed = (time.perf_counter() - t0) * 1000

        grade_dict = None
        if hasattr(resp, "grade") and resp.grade is not None:
            grade_dict = {
                "faithfulness": resp.grade.faithfulness,
                "completeness": resp.grade.completeness,
                "citation_accuracy": resp.grade.citation_accuracy,
                "overall": resp.grade.overall,
                "passed": resp.grade.passed,
                "issues": resp.grade.issues,
            }

        sources = []
        if hasattr(resp, "sources"):
            for s in resp.sources:
                sources.append({
                    "citation": s.citation if hasattr(s, "citation") else "",
                    "source_name": s.source_name if hasattr(s, "source_name") else "",
                    "page": s.page if hasattr(s, "page") else 0,
                    "score": s.score if hasattr(s, "score") else 0.0,
                })

        logger.info(
            "Batch Q %d/%d answered in %.0fms: %.50s",
            index + 1, total, elapsed, question,
        )
        return BatchResult(
            question=question,
            answer=resp.answer if hasattr(resp, "answer") else str(resp),
            sources=sources,
            grade=grade_dict,
            latency_ms=round(elapsed, 1),
        )
    except Exception as exc:
        elapsed = (time.perf_counter() - t0) * 1000
        logger.warning(
            "Batch Q %d/%d failed (%.0fms): %s — %s",
            index + 1, total, elapsed, question, exc,
        )
        return BatchResult(
            question=question,
            error=str(exc),
            latency_ms=round(elapsed, 1),
        )


def run_batch(
    questions: List[str],
    run_query_fn,
    notebook_id: str,
    top_k: int = 5,
) -> List[BatchResult]:
    """
    Execute a list of questions in parallel through the RAG pipeline.

    Uses a thread pool to process up to ``_BATCH_WORKERS`` questions
    concurrently.  Each question is run independently; failures are
    captured per-question so the batch continues even if individual
    questions error out.

    Args:
        questions:    List of question strings.
        run_query_fn: Callable(question, top_k, notebook_id) -> QueryResponse-like obj.
        notebook_id:  Notebook scope for retrieval.
        top_k:        Number of chunks per question.

    Returns:
        List of BatchResult, one per question in the original order.
    """
    total = len(questions)
    workers = min(_BATCH_WORKERS, total)

    ordered: Dict[int, BatchResult] = {}

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="batchq") as pool:
        futures = {
            pool.submit(
                _run_one, i, q, run_query_fn, top_k, notebook_id, total,
            ): i
            for i, q in enumerate(questions)
        }
        for future in as_completed(futures):
            idx = futures[future]
            ordered[idx] = future.result()

    return [ordered[i] for i in range(total)]
