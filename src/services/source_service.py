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

import logging
from pathlib import Path
from typing import Dict, List, Optional

from src.db import source_db, chunk_db, notebook_db
from src.pdf_processor import (
    SectionBlock,
    chunk_sections,
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


def process_source(source_id: str) -> None:
    """
    Run the full ingestion pipeline for a source with streamed embed→insert.

    Stages (each updates the source status for frontend polling):
      1. extracting  — PDF / text extraction
      2. chunking    — sentence-aware chunking
      3. embedding X/Y — API batches, inserted into DB as they complete
      4. ready       — all done

    Runs inside a thread pool executor (see api.py), so multiple sources
    are processed concurrently.

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
        chunks = _extract_and_chunk(source)

        if not chunks:
            source_db.update_source(source_id, status="ready", chunk_count=0)
            logger.warning("Source %s produced 0 chunks", source_id)
            return

        _set_status(source_id, "chunking")
        chunk_dicts = [_chunk_to_dict(c) for c in chunks]
        texts = [_chunk_text(c) for c in chunks]

        embedder = _get_embedder()
        total_batches = (len(texts) + _EMBED_BATCH_SIZE - 1) // _EMBED_BATCH_SIZE
        inserted = 0

        def _on_batch_done(done: int, total: int) -> None:
            _set_status(source_id, f"embedding {done}/{total}")

        _set_status(source_id, f"embedding 0/{total_batches}")

        embeddings = embedder.embed_batch(
            texts,
            show_progress=False,
            on_batch_done=_on_batch_done,
        )

        _set_status(source_id, "storing")
        inserted = chunk_db.insert_chunks(
            chunks=chunk_dicts,
            embeddings=embeddings,
            notebook_id=notebook_id,
            source_id=source_id,
        )

        source_db.update_source(source_id, status="ready", chunk_count=inserted)
        logger.info("Source %s ready — %d chunks embedded", source_id, inserted)

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
    """Update the source status column (used for granular progress tracking)."""
    source_db.update_source(source_id, status=status)


def _validate_notebook(notebook_id: str) -> None:
    """Raise ValueError if notebook doesn't exist."""
    if not notebook_db.get_notebook(notebook_id):
        raise ValueError(f"Notebook not found: {notebook_id}")


def _extract_and_chunk(source: Dict) -> list:
    """
    Extract text from a source and produce chunks.

    For PDFs: extract_pages -> detect_sections -> chunk_sections.
    For text: wrap in a single SectionBlock -> chunk_sections.

    Args:
        source: Source dict from DB.

    Returns:
        List of Chunk objects (from pdf_processor).
    """
    if source["source_type"] == "file":
        file_path = source.get("file_path", "")
        if not file_path or not Path(file_path).exists():
            raise FileNotFoundError(f"Source file not found: {file_path}")

        pages = extract_pages(file_path)
        sections = detect_sections(pages)
        return chunk_sections(sections)

    text = source.get("raw_content", "")
    if not text:
        return []

    section = SectionBlock(
        chapter_id="0",
        section_id="0.0",
        section_title=source.get("name", "Pasted text"),
        page_start=1,
        page_end=1,
        text=text,
    )
    return chunk_sections([section])


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
