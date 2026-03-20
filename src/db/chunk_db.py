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
from typing import Dict, List, Optional

import numpy as np
from psycopg2.extras import execute_values

from src.db.connection import get_connection

logger = logging.getLogger(__name__)

TABLE = "document_chunks"
EMBEDDING_DIM = 4096


def insert_chunks(
    chunks: List[Dict],
    embeddings: np.ndarray,
    notebook_id: str,
    source_id: str,
    batch_size: int = 300,
) -> int:
    """
    Upsert document chunks with their embeddings, scoped to a notebook/source.

    Uses larger batch sizes to reduce round-trips to the database.

    Args:
        chunks:      List of chunk dicts (chunk_id, text, section_id, …).
        embeddings:  Float32 array of shape ``(n, 4096)``.
        notebook_id: Parent notebook UUID.
        source_id:   Parent source UUID.
        batch_size:  Rows per INSERT statement (default 300).

    Returns:
        Number of rows upserted.

    Raises:
        ValueError:   If lengths don't match.
        RuntimeError: On database error.
    """
    if len(chunks) != len(embeddings):
        raise ValueError(f"Length mismatch: {len(chunks)} chunks vs {len(embeddings)} embeddings.")

    sql = f"""
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
        return obj.get(attr, default) if isinstance(obj, dict) else getattr(obj, attr, default)

    inserted = 0
    t0 = time.time()

    with get_connection() as conn:
        with conn.cursor() as cur:
            for i in range(0, len(chunks), batch_size):
                batch_c = chunks[i : i + batch_size]
                batch_e = embeddings[i : i + batch_size]

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
                execute_values(cur, sql, rows)
                inserted += len(batch_c)

    elapsed = time.time() - t0
    logger.info("Upserted %d chunks in %.2fs (notebook=%s, source=%s)", inserted, elapsed, notebook_id, source_id)
    return inserted


def search(
    query_embedding: np.ndarray,
    top_k: int = 5,
    notebook_id: Optional[str] = None,
) -> List[Dict]:
    """
    Cosine-similarity search, optionally scoped to a single notebook.

    Args:
        query_embedding: 1-D float array (4096,).
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
                   1 - (embedding <=> %s::halfvec({EMBEDDING_DIM})) AS score
            FROM {TABLE}
            WHERE notebook_id = %s
            ORDER BY embedding <=> %s::halfvec({EMBEDDING_DIM})
            LIMIT %s
        """
        params = (vec, notebook_id, vec, top_k)
    else:
        sql = f"""
            SELECT chunk_id, text, section_id, chapter_id,
                   section_title, page_num, chunk_index,
                   char_count, word_count,
                   1 - (embedding <=> %s::halfvec({EMBEDDING_DIM})) AS score
            FROM {TABLE}
            ORDER BY embedding <=> %s::halfvec({EMBEDDING_DIM})
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
