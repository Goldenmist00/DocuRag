"""
chunk_db.py
===========
Database operations for the ``document_chunks`` table,
extended with notebook_id / source_id scoping.

Wraps raw SQL for insert, scoped search, and deletion.
Embedding search uses the same cosine-similarity approach as
``vector_store.py`` but adds a ``WHERE notebook_id = %s`` filter.
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

import numpy as np
from psycopg2.extras import execute_values

from src.db.connection import get_connection

logger = logging.getLogger(__name__)

TABLE = "document_chunks"
EMBEDDING_DIM = 1024

_INSERT_BATCH = 200
_INSERT_WORKERS = 4

_UPSERT_SQL = f"""
    INSERT INTO {TABLE} (
        chunk_id, text, embedding,
        notebook_id, source_id,
        section_id, chapter_id, section_title,
        page_num, chunk_index, char_count, word_count
    ) VALUES %s
    ON CONFLICT (chunk_id) DO UPDATE SET
        text        = EXCLUDED.text,
        embedding   = EXCLUDED.embedding,
        notebook_id = EXCLUDED.notebook_id,
        source_id   = EXCLUDED.source_id,
        updated_at  = CURRENT_TIMESTAMP
"""


def _get(obj, attr, default=None):
    """Safely access a dict key or object attribute."""
    return obj.get(attr, default) if isinstance(obj, dict) else getattr(obj, attr, default)


def _deduplicate(chunks: List[Dict], embeddings: np.ndarray):
    """
    Remove rows with duplicate chunk_ids, keeping the last occurrence.

    Args:
        chunks: List of chunk dicts.
        embeddings: Corresponding embedding array.

    Returns:
        Tuple of (deduplicated chunks, deduplicated embeddings).
    """
    seen: Dict[str, int] = {}
    for i, c in enumerate(chunks):
        seen[_get(c, "chunk_id")] = i
    unique_idx = sorted(seen.values())
    if len(unique_idx) < len(chunks):
        logger.warning(
            "Removed %d duplicate chunk_ids before insert",
            len(chunks) - len(unique_idx),
        )
    return [chunks[i] for i in unique_idx], embeddings[unique_idx]


def _insert_worker(
    group_chunks: List[Dict],
    group_embeddings: np.ndarray,
    notebook_id: str,
    source_id: str,
) -> int:
    """
    Insert one group of chunks using its own pooled connection.

    Each worker commits independently so progress is incremental
    and no single transaction holds locks for the entire duration.

    Args:
        group_chunks: Slice of chunk dicts for this worker.
        group_embeddings: Corresponding embedding slice.
        notebook_id: Parent notebook UUID.
        source_id: Parent source UUID.

    Returns:
        Number of rows upserted by this worker.
    """
    count = 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            for i in range(0, len(group_chunks), _INSERT_BATCH):
                batch_c = group_chunks[i : i + _INSERT_BATCH]
                batch_e = group_embeddings[i : i + _INSERT_BATCH]
                rows = [
                    (
                        _get(c, "chunk_id"),
                        _get(c, "text"),
                        batch_e[j].tolist(),
                        notebook_id,
                        source_id,
                        _get(c, "section_id"),
                        _get(c, "chapter_id"),
                        _get(c, "section_title"),
                        _get(c, "page_num", 0),
                        _get(c, "chunk_index", 0),
                        _get(c, "char_count", 0),
                        _get(c, "word_count", 0),
                    )
                    for j, c in enumerate(batch_c)
                ]
                execute_values(cur, _UPSERT_SQL, rows)
                count += len(batch_c)
    return count


def insert_chunks(
    chunks: List[Dict],
    embeddings: np.ndarray,
    notebook_id: str,
    source_id: str,
) -> int:
    """
    Upsert document chunks with their embeddings, scoped to a notebook/source.

    Deduplicates by chunk_id, then distributes inserts across parallel
    workers (each with its own DB connection) for faster throughput.

    Args:
        chunks:      List of chunk dicts (chunk_id, text, section_id, …).
        embeddings:  Float32 array of shape ``(n, dim)``.
        notebook_id: Parent notebook UUID.
        source_id:   Parent source UUID.

    Returns:
        Number of rows upserted.

    Raises:
        ValueError:   If lengths don't match.
        RuntimeError: On database error.
    """
    if len(chunks) != len(embeddings):
        raise ValueError(f"Length mismatch: {len(chunks)} chunks vs {len(embeddings)} embeddings.")

    chunks, embeddings = _deduplicate(chunks, embeddings)

    if not chunks:
        return 0

    t0 = time.time()
    n = len(chunks)
    workers = min(_INSERT_WORKERS, max(1, n // _INSERT_BATCH))

    if workers <= 1:
        inserted = _insert_worker(chunks, embeddings, notebook_id, source_id)
    else:
        group_size = (n + workers - 1) // workers
        inserted = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = []
            for w in range(workers):
                start = w * group_size
                end = min(start + group_size, n)
                if start >= end:
                    break
                futures.append(
                    pool.submit(
                        _insert_worker,
                        chunks[start:end],
                        embeddings[start:end],
                        notebook_id,
                        source_id,
                    )
                )
            for f in as_completed(futures):
                inserted += f.result()

    elapsed = time.time() - t0
    logger.info(
        "Upserted %d chunks in %.2fs (%d workers, notebook=%s, source=%s)",
        inserted, elapsed, workers, notebook_id, source_id,
    )
    return inserted


def search(
    query_embedding: np.ndarray,
    top_k: int = 5,
    notebook_id: Optional[str] = None,
) -> List[Dict]:
    """
    Cosine-similarity search, optionally scoped to a single notebook.

    Args:
        query_embedding: 1-D float array (1024,).
        top_k:           Number of results.
        notebook_id:     If provided, only search this notebook's chunks.

    Returns:
        List of result dicts sorted by score descending.
    """
    vec = query_embedding.tolist()
    t0 = time.time()

    if notebook_id:
        sql = f"""
            SELECT chunk_id, text, section_id, chapter_id,
                   section_title, page_num, chunk_index,
                   char_count, word_count,
                   1 - (embedding <=> %s::vector({EMBEDDING_DIM})) AS score
            FROM {TABLE}
            WHERE notebook_id = %s
            ORDER BY embedding <=> %s::vector({EMBEDDING_DIM})
            LIMIT %s
        """
        params = (vec, notebook_id, vec, top_k)
    else:
        sql = f"""
            SELECT chunk_id, text, section_id, chapter_id,
                   section_title, page_num, chunk_index,
                   char_count, word_count,
                   1 - (embedding <=> %s::vector({EMBEDDING_DIM})) AS score
            FROM {TABLE}
            ORDER BY embedding <=> %s::vector({EMBEDDING_DIM})
            LIMIT %s
        """
        params = (vec, vec, top_k)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            results = [
                {
                    "chunk_id":      r[0],
                    "text":          r[1],
                    "section_id":    r[2],
                    "chapter_id":    r[3],
                    "section_title": r[4],
                    "page_num":      r[5],
                    "chunk_index":   r[6],
                    "char_count":    r[7],
                    "word_count":    r[8],
                    "score":         float(r[9]),
                }
                for r in cur.fetchall()
            ]

    elapsed = (time.time() - t0) * 1000
    logger.info("Scoped search returned %d results in %.1fms (notebook=%s)", len(results), elapsed, notebook_id)
    return results


def delete_by_source(source_id: str) -> int:
    """
    Delete all chunks belonging to a specific source.

    Args:
        source_id: UUID string.

    Returns:
        Number of rows deleted.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {TABLE} WHERE source_id = %s", (source_id,))
            count = cur.rowcount
    logger.info("Deleted %d chunks for source %s", count, source_id)
    return count
