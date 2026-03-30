"""
repo_code_chunk_db.py
=====================
Database operations for the ``repo_code_chunks`` table.

Stores function-level code chunks with vector embeddings for
semantic search via pgvector.  Dimension is determined at runtime
by the active embedding provider.

DB layer only: SQL and adapters, no business logic.
"""

import logging
from typing import Any, Dict, List, Optional

import numpy as np
from psycopg2.extras import execute_values

from src.db.connection import get_connection, retry_on_disconnect

logger = logging.getLogger(__name__)

TABLE = "repo_code_chunks"


def _get_embed_dim() -> int:
    """Resolve the embedding dimension from the active provider.

    Returns:
        Dimension integer (768 for Gemini, 1024 for NVIDIA).
    """
    try:
        from src.embedder import get_embedder
        return get_embedder().embedding_dim
    except Exception:
        import os
        if os.getenv("GEMINI_API_KEY", "").strip():
            return 768
        return 1024


@retry_on_disconnect
def ensure_table() -> None:
    """Create ``repo_code_chunks`` table and indexes if missing.

    If the table already exists but the embedding column has a
    different vector dimension, existing embeddings are cleared and
    the column is re-typed to match the active provider.

    Returns:
        None

    Raises:
        psycopg2.Error: If DDL execution fails.
    """
    dim = _get_embed_dim()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {TABLE} (
                    id SERIAL PRIMARY KEY,
                    repo_id UUID NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
                    file_path TEXT NOT NULL,
                    symbol_name TEXT,
                    chunk_type TEXT DEFAULT 'function',
                    start_line INT,
                    end_line INT,
                    content TEXT NOT NULL,
                    embedding vector({dim}),
                    file_hash TEXT,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cur.execute("""
                SELECT pg_catalog.format_type(atttypid, atttypmod)
                FROM pg_attribute
                WHERE attrelid = %s::regclass AND attname = 'embedding'
            """, (TABLE,))
            row = cur.fetchone()
            if row:
                current_type = row[0]
                expected_type = f"vector({dim})"
                if current_type != expected_type:
                    logger.warning(
                        "Embedding dim mismatch (%s -> %s) — migrating column",
                        current_type, expected_type,
                    )
                    cur.execute(f"DROP INDEX IF EXISTS idx_code_chunks_embedding")
                    cur.execute(f"UPDATE {TABLE} SET embedding = NULL")
                    cur.execute(
                        f"ALTER TABLE {TABLE} ALTER COLUMN embedding "
                        f"TYPE vector({dim})"
                    )

            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_code_chunks_repo
                ON {TABLE}(repo_id)
            """)
            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_code_chunks_file
                ON {TABLE}(repo_id, file_path)
            """)
            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_code_chunks_embedding
                ON {TABLE} USING hnsw (embedding vector_cosine_ops)
            """)
    logger.info("Table %s ensured (dim=%d)", TABLE, dim)


@retry_on_disconnect
def insert_chunks(
    repo_id: str,
    chunks: List[Dict[str, Any]],
) -> int:
    """Batch-insert code chunks with embeddings.

    Each chunk dict should contain: ``file_path``, ``content``,
    ``embedding`` (list or numpy array of floats matching provider dim).
    Optional: ``symbol_name``, ``chunk_type``, ``start_line``,
    ``end_line``, ``file_hash``.

    Args:
        repo_id: Repository UUID.
        chunks:  List of chunk dicts.

    Returns:
        Number of chunks inserted.
    """
    if not chunks:
        return 0

    with get_connection() as conn:
        with conn.cursor() as cur:
            rows = []
            for c in chunks:
                emb = c.get("embedding")
                if emb is not None:
                    if isinstance(emb, np.ndarray):
                        emb = emb.tolist()
                    emb_str = "[" + ",".join(str(v) for v in emb) + "]"
                else:
                    emb_str = None
                rows.append((
                    repo_id,
                    c["file_path"],
                    c.get("symbol_name"),
                    c.get("chunk_type", "function"),
                    c.get("start_line"),
                    c.get("end_line"),
                    c["content"],
                    emb_str,
                    c.get("file_hash"),
                ))
            execute_values(
                cur,
                f"""
                INSERT INTO {TABLE}
                    (repo_id, file_path, symbol_name, chunk_type,
                     start_line, end_line, content, embedding, file_hash)
                VALUES %s
                """,
                rows,
                template="(%s, %s, %s, %s, %s, %s, %s, %s::vector, %s)",
                )
    return len(chunks)


@retry_on_disconnect
def get_file_hashes(repo_id: str) -> Dict[str, str]:
    """Return a map of file_path -> file_hash for existing chunks.

    Used to skip re-embedding unchanged files during full re-index.

    Args:
        repo_id: Repository UUID.

    Returns:
        Dict mapping file paths to their stored hashes.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT DISTINCT file_path, file_hash FROM {TABLE} WHERE repo_id = %s AND file_hash IS NOT NULL",
                (repo_id,),
            )
            return {row[0]: row[1] for row in cur.fetchall()}


@retry_on_disconnect
def delete_for_repo(repo_id: str) -> int:
    """Delete all code chunks for a repository.

    Args:
        repo_id: Repository UUID.

    Returns:
        Number of rows deleted.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {TABLE} WHERE repo_id = %s",
                (repo_id,),
            )
            return cur.rowcount or 0


@retry_on_disconnect
def delete_for_files(repo_id: str, file_paths: List[str]) -> int:
    """Delete code chunks for specific files (used during incremental re-embed).

    Args:
        repo_id:    Repository UUID.
        file_paths: File paths to clear.

    Returns:
        Number of rows deleted.
    """
    if not file_paths:
        return 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {TABLE} WHERE repo_id = %s AND file_path = ANY(%s)",
                (repo_id, file_paths),
            )
            return cur.rowcount or 0


@retry_on_disconnect
def search_similar(
    repo_id: str,
    query_embedding: List[float],
    limit: int = 15,
    threshold: float = 0.3,
) -> List[Dict[str, Any]]:
    """Find code chunks most similar to a query embedding using cosine distance.

    Args:
        repo_id:         Repository UUID.
        query_embedding: Query vector (dimension must match the column).
        limit:           Maximum results to return.
        threshold:       Maximum cosine distance (lower = more similar).

    Returns:
        List of chunk dicts with ``file_path``, ``symbol_name``,
        ``chunk_type``, ``content``, ``start_line``, ``end_line``,
        ``similarity`` (1 - distance).
    """
    emb_str = "[" + ",".join(str(v) for v in query_embedding) + "]"

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT file_path, symbol_name, chunk_type,
                       content, start_line, end_line,
                       1 - (embedding <=> %s::vector) AS similarity
                FROM {TABLE}
                WHERE repo_id = %s
                  AND embedding IS NOT NULL
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (emb_str, repo_id, emb_str, limit),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
            return [r for r in rows if r.get("similarity", 0) >= (1 - threshold)]


@retry_on_disconnect
def get_chunks_for_file(repo_id: str, file_path: str) -> List[Dict[str, Any]]:
    """Retrieve all chunks for a specific file.

    Args:
        repo_id:   Repository UUID.
        file_path: File path.

    Returns:
        List of chunk dicts.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT file_path, symbol_name, chunk_type,
                       content, start_line, end_line, file_hash
                FROM {TABLE}
                WHERE repo_id = %s AND file_path = %s
                ORDER BY start_line
                """,
                (repo_id, file_path),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


@retry_on_disconnect
def count_chunks(repo_id: str) -> int:
    """Count total code chunks for a repository.

    Args:
        repo_id: Repository UUID.

    Returns:
        Chunk count.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) FROM {TABLE} WHERE repo_id = %s",
                (repo_id,),
            )
            return cur.fetchone()[0]
