"""
source_service.py
=================
Orchestrates source ingestion: upload/paste -> chunk -> embed -> store.

This is the core pipeline that makes per-notebook RAG work.
Processing runs concurrently in a thread pool via asyncio.run_in_executor.

Optimisations:
  - Streamed embed→insert: each API batch is inserted into the DB as soon
    as its embeddings return, overlapping network + DB latency.
  - Granular progress: status column is updated at every pipeline stage
    so the frontend can display meaningful progress.
"""

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from src.db import source_db, chunk_db, notebook_db
from src.pdf_processor import (
    SectionBlock,
    extract_pages,
    detect_sections,
)
from src.embedder import Embedder, EmbeddingTier

logger = logging.getLogger(__name__)

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

_embedder: Optional[Embedder] = None


def _get_embedder() -> Embedder:
    """
    Lazily initialise a shared Embedder instance.

    Returns:
        Configured Embedder.
    """
    global _embedder
    if _embedder is None:
        _embedder = Embedder(tier=EmbeddingTier.NVIDIA)
    return _embedder


def set_embedder(embedder: Embedder) -> None:
    """
    Inject an already-initialised Embedder (called from api.py lifespan).

    Args:
        embedder: Pre-configured Embedder instance.
    """
    global _embedder
    _embedder = embedder


def add_file_source(notebook_id: str, filename: str, file_bytes: bytes) -> Dict:
    """
    Save an uploaded file and create a source record (status=pending).

    The actual processing happens in ``process_source`` via BackgroundTasks.

    Args:
        notebook_id: Parent notebook UUID.
        filename: Original filename.
        file_bytes: Raw file content.

    Returns:
        Source dict with status="pending".

    Raises:
        ValueError: If notebook not found or file is empty.
    """
    _validate_notebook(notebook_id)

    if not file_bytes:
        raise ValueError("Uploaded file is empty.")

    nb_dir = UPLOAD_DIR / notebook_id
    nb_dir.mkdir(parents=True, exist_ok=True)
    dest = nb_dir / filename
    dest.write_bytes(file_bytes)

    source = source_db.create_source(
        notebook_id=notebook_id,
        name=filename,
        source_type="file",
        file_path=str(dest),
        status="pending",
    )
    logger.info("File source created: %s (%s)", source["id"], filename)
    return source


def add_text_source(notebook_id: str, name: str, text: str) -> Dict:
    """
    Create a source record for pasted text (status=pending).

    The actual processing happens in ``process_source`` via BackgroundTasks.

    Args:
        notebook_id: Parent notebook UUID.
        name: Display name for the source.
        text: Full pasted text content.

    Returns:
        Source dict with status="pending".

    Raises:
        ValueError: If notebook not found or text is empty.
    """
    _validate_notebook(notebook_id)

    clean = text.strip()
    if not clean:
        raise ValueError("Pasted text is empty.")

    source = source_db.create_source(
        notebook_id=notebook_id,
        name=name or "Pasted text",
        source_type="text",
        raw_content=clean,
        status="pending",
    )
    logger.info("Text source created: %s (%s)", source["id"], name)
    return source


_EMBED_BATCH_SIZE = 48
_MAX_CHUNK_CHARS = 3000
_MIN_CHUNK_CHARS = 80
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def process_source(source_id: str) -> None:
    """
    Run the optimised ingestion pipeline for a source.

    Stages:
      1. extracting   — PDF / JSON / text extraction into sections
      2. chunking     — text-based paragraph grouping (no API call)
      3. embedding    — embed chunks with streamed DB inserts
      4. ready        — all done

    Uses text-based chunking instead of paragraph-level embedding
    to eliminate a full round of NVIDIA API calls, and streams
    embed batches directly into PostgreSQL as they return.

    Args:
        source_id: UUID of the source to process.
    """
    source = source_db.get_source(source_id)
    if not source:
        logger.error("Source %s not found — skipping processing", source_id)
        return

    notebook_id = source["notebook_id"]

    try:
        _set_status(source_id, "extracting")
        sections = _extract_sections(source)

        if not sections:
            source_db.update_source(source_id, status="ready", chunk_count=0)
            logger.warning("Source %s produced 0 sections", source_id)
            return

        embedder = _get_embedder()

        _set_status(source_id, "chunking")
        chunk_dicts = _text_chunk(sections)

        if not chunk_dicts:
            source_db.update_source(source_id, status="ready", chunk_count=0)
            logger.warning("Source %s produced 0 chunks", source_id)
            return

        _set_status(source_id, "embedding")
        inserted = _stream_embed_and_store(
            chunk_dicts, embedder, notebook_id, source_id,
        )

        source_db.update_source(source_id, status="ready", chunk_count=inserted)
        logger.info("Source %s ready — %d chunks stored", source_id, inserted)

    except Exception as exc:
        logger.error("Source %s processing failed: %s", source_id, exc, exc_info=True)
        source_db.update_source(
            source_id,
            status="error",
            error_message=str(exc)[:500],
        )


def list_sources(notebook_id: str) -> List[Dict]:
    """
    List all sources for a notebook.

    Args:
        notebook_id: UUID string.

    Returns:
        List of source dicts.
    """
    return source_db.list_sources(notebook_id)


def delete_source(source_id: str) -> None:
    """
    Delete a source and its chunks. Also removes uploaded file from disk.

    Args:
        source_id: UUID string.

    Raises:
        ValueError: If source not found.
    """
    source = source_db.get_source(source_id)
    if not source:
        raise ValueError(f"Source not found: {source_id}")

    if source.get("file_path"):
        try:
            Path(source["file_path"]).unlink(missing_ok=True)
        except Exception as exc:
            logger.warning("Could not remove file %s: %s", source["file_path"], exc)

    deleted = source_db.delete_source(source_id)
    if not deleted:
        raise ValueError(f"Source not found: {source_id}")
    logger.info("Deleted source %s", source_id)


# ─── Internal helpers ───


def _set_status(source_id: str, status: str) -> None:
    """
    Update the source status column with retry.

    Status updates are non-critical progress signals — a transient
    DB timeout should not kill the entire ingestion pipeline.

    Args:
        source_id: UUID string.
        status: New status value.
    """
    import time as _time
    for attempt in range(3):
        try:
            source_db.update_source(source_id, status=status)
            return
        except Exception as exc:
            if attempt < 2:
                logger.warning(
                    "Status update to '%s' failed (attempt %d/3): %s — retrying",
                    status, attempt + 1, exc,
                )
                _time.sleep(2 ** attempt)
            else:
                logger.error("Status update to '%s' failed after 3 attempts: %s", status, exc)


def _validate_notebook(notebook_id: str) -> None:
    """Raise ValueError if notebook doesn't exist."""
    if not notebook_db.get_notebook(notebook_id):
        raise ValueError(f"Notebook not found: {notebook_id}")


def _extract_sections(source: Dict) -> List[SectionBlock]:
    """
    Extract text from a source and produce SectionBlock objects.

    For PDFs: extract_pages -> detect_sections.
    For JSON: parse and flatten text content.
    For text: wrap in a single SectionBlock.

    Args:
        source: Source dict from DB.

    Returns:
        List of SectionBlock objects.
    """
    if source["source_type"] == "file":
        file_path = source.get("file_path", "")
        if not file_path or not Path(file_path).exists():
            raise FileNotFoundError(f"Source file not found: {file_path}")

        ext = Path(file_path).suffix.lower()

        if ext == ".json":
            return _extract_json_sections(file_path, source.get("name", "JSON file"))

        pages = extract_pages(file_path)
        return detect_sections(pages)

    text = source.get("raw_content", "")
    if not text:
        return []

    return [SectionBlock(
        chapter_id="0",
        section_id="0.0",
        section_title=source.get("name", "Pasted text"),
        page_start=1,
        page_end=1,
        text=text,
    )]


def _split_paragraphs(text: str) -> List[str]:
    """Split text into paragraphs on double-newlines, falling back to single."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paras and text.strip():
        paras = [p.strip() for p in text.split("\n") if p.strip()]
    if not paras and text.strip():
        paras = [text.strip()]
    return paras


def _get_last_sentence(text: str) -> str:
    """Return the last complete sentence from a text block."""
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text.strip()) if s.strip()]
    return sentences[-1] if sentences else ""


def _split_by_max_size(paragraphs: List[str], max_chars: int) -> List[str]:
    """
    Group paragraphs into text blocks that stay under max_chars.

    Args:
        paragraphs: List of paragraph strings.
        max_chars: Maximum characters per group.

    Returns:
        List of combined text blocks.
    """
    result: List[str] = []
    current: List[str] = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para) + 2
        if current_len + para_len > max_chars and current:
            result.append("\n\n".join(current))
            current = []
            current_len = 0
        current.append(para)
        current_len += para_len

    if current:
        result.append("\n\n".join(current))
    return result


def _text_chunk(sections: List[SectionBlock]) -> List[Dict]:
    """
    Fast text-based chunking using paragraph grouping by size.

    Groups paragraphs within each section up to _MAX_CHUNK_CHARS,
    respecting section boundaries. No API calls — purely local.

    Args:
        sections: List of SectionBlock objects from extraction.

    Returns:
        List of chunk dicts ready for embedding.
    """
    chunk_dicts: List[Dict] = []
    chunk_idx = 0

    for section in sections:
        paras = _split_paragraphs(section.text)
        if not paras:
            continue

        text_blocks = _split_by_max_size(paras, _MAX_CHUNK_CHARS)

        for text in text_blocks:
            if len(text) < _MIN_CHUNK_CHARS:
                continue

            cid = hashlib.sha256(
                f"{section.section_id}{chunk_idx}{text[:64]}".encode()
            ).hexdigest()[:16]

            chunk_dicts.append({
                "chunk_id": cid,
                "text": text,
                "section_id": section.section_id,
                "chapter_id": section.chapter_id,
                "section_title": section.section_title,
                "page_num": section.page_start,
                "chunk_index": chunk_idx,
                "char_count": len(text),
                "word_count": len(text.split()),
            })
            chunk_idx += 1

    logger.info("Text chunking produced %d chunks from %d sections", len(chunk_dicts), len(sections))
    return chunk_dicts


def _stream_embed_and_store(
    chunk_dicts: List[Dict],
    embedder: Embedder,
    notebook_id: str,
    source_id: str,
) -> int:
    """
    Embed chunks and insert into DB in a streamed fashion.

    Each NVIDIA API batch is inserted into PostgreSQL as soon as
    its embeddings return, overlapping network and DB latency.

    Args:
        chunk_dicts: List of chunk dicts from _text_chunk.
        embedder: Configured Embedder instance.
        notebook_id: Parent notebook UUID.
        source_id: Parent source UUID.

    Returns:
        Total rows inserted.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    enriched_texts: List[str] = []
    for i, chunk in enumerate(chunk_dicts):
        prefix = f"{chunk['section_title']} | "
        if i > 0:
            prev_last = _get_last_sentence(chunk_dicts[i - 1]["text"])
            if prev_last:
                prefix += prev_last + " "
        enriched_texts.append(prefix + chunk["text"])

    batch_size = _EMBED_BATCH_SIZE
    batches = [
        (enriched_texts[i:i + batch_size], chunk_dicts[i:i + batch_size], idx)
        for idx, i in enumerate(range(0, len(enriched_texts), batch_size))
    ]
    n_batches = len(batches)
    inserted = 0

    def _embed_one(texts: List[str]) -> np.ndarray:
        return embedder.embed_batch(texts, show_progress=False, use_cache=True)

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="db-store") as db_pool:
        db_futures = []

        for batch_texts, batch_chunks, b_idx in batches:
            embs = _embed_one(batch_texts)
            _set_status(source_id, f"embedding {b_idx + 1}/{n_batches}")

            fut = db_pool.submit(
                chunk_db.insert_chunks,
                chunks=batch_chunks,
                embeddings=embs,
                notebook_id=notebook_id,
                source_id=source_id,
            )
            db_futures.append(fut)

        for fut in as_completed(db_futures):
            inserted += fut.result()

    logger.info(
        "Streamed embed+store: %d chunks in %d batches (source=%s)",
        inserted, n_batches, source_id,
    )
    return inserted


def _flatten_json_strings(obj, prefix: str = "") -> List[str]:
    """
    Recursively extract all string values from a JSON structure.

    Objects produce "key: value" lines, arrays are iterated in order.
    Non-string scalars (numbers, booleans, None) are stringified.

    Args:
        obj: Parsed JSON value (dict, list, or scalar).
        prefix: Dot-delimited path for context (e.g. "user.address").

    Returns:
        Flat list of human-readable text lines.
    """
    lines: List[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            child_prefix = f"{prefix}.{key}" if prefix else key
            if isinstance(value, str):
                lines.append(f"{child_prefix}: {value}")
            elif isinstance(value, (dict, list)):
                lines.extend(_flatten_json_strings(value, child_prefix))
            elif value is not None:
                lines.append(f"{child_prefix}: {value}")
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            lines.extend(_flatten_json_strings(item, f"{prefix}[{i}]"))
    elif isinstance(obj, str):
        lines.append(f"{prefix}: {obj}" if prefix else obj)
    elif obj is not None:
        lines.append(f"{prefix}: {obj}" if prefix else str(obj))
    return lines


_JSON_BATCH_TARGET = 600


def _extract_json_sections(file_path: str, source_name: str) -> List[SectionBlock]:
    """
    Parse a JSON file and produce SectionBlock(s) for chunking.

    If the top-level value is an array, items are batched into sections
    of ~600 chars each so short entries don't fall below the minimum
    chunk threshold. Single objects are flattened into one section.

    Args:
        file_path: Path to the JSON file on disk.
        source_name: Display name for the source.

    Returns:
        List of SectionBlock objects.

    Raises:
        ValueError: If the file cannot be parsed as JSON.
    """
    try:
        raw = Path(file_path).read_text(encoding="utf-8")
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"Invalid JSON file ({source_name}): {exc}") from exc

    sections: List[SectionBlock] = []

    if isinstance(data, list):
        batch_lines: List[str] = []
        batch_len = 0
        batch_idx = 0

        for idx, item in enumerate(data):
            lines = _flatten_json_strings(item)
            if not lines:
                continue
            entry_text = "\n".join(lines)
            batch_lines.append(entry_text)
            batch_len += len(entry_text)

            if batch_len >= _JSON_BATCH_TARGET or idx == len(data) - 1:
                sections.append(SectionBlock(
                    chapter_id="0",
                    section_id=f"0.{batch_idx}",
                    section_title=f"{source_name} — part {batch_idx + 1}",
                    page_start=1,
                    page_end=1,
                    text="\n\n".join(batch_lines),
                ))
                batch_lines = []
                batch_len = 0
                batch_idx += 1
    else:
        lines = _flatten_json_strings(data)
        if lines:
            sections.append(SectionBlock(
                chapter_id="0",
                section_id="0.0",
                section_title=source_name,
                page_start=1,
                page_end=1,
                text="\n".join(lines),
            ))

    logger.info("JSON source '%s' produced %d sections", source_name, len(sections))
    return sections


def _chunk_text(chunk) -> str:
    """Extract text from a Chunk object or dict."""
    if isinstance(chunk, dict):
        return chunk.get("text", "")
    return getattr(chunk, "text", "")


def _chunk_to_dict(chunk) -> dict:
    """Convert a Chunk pydantic model to a plain dict for chunk_db."""
    if isinstance(chunk, dict):
        return chunk
    return {
        "chunk_id":      chunk.chunk_id,
        "text":          chunk.text,
        "section_id":    chunk.section_id,
        "chapter_id":    chunk.chapter_id,
        "section_title": chunk.section_title,
        "page_num":      getattr(chunk, "page_num", chunk.page_start),
        "chunk_index":   chunk.chunk_index,
        "char_count":    chunk.char_count,
        "word_count":    chunk.word_count,
    }
