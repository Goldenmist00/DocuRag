"""
repo_reference_db.py
====================
Database operations for the ``repo_references`` table.

Stores cross-file reference edges (imports, calls, inheritance)
extracted during AST-based repository indexing.

DB layer only: SQL and adapters, no business logic.
"""

import logging
from typing import Any, Dict, List, Optional

from src.db.connection import get_connection, retry_on_disconnect

logger = logging.getLogger(__name__)

TABLE = "repo_references"


@retry_on_disconnect
def ensure_table() -> None:
    """Create ``repo_references`` table and indexes if missing.

    Returns:
        None

    Raises:
        psycopg2.Error: If DDL execution fails.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {TABLE} (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    repo_id UUID NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
                    source_file TEXT NOT NULL,
                    target_file TEXT NOT NULL,
                    reference_type TEXT NOT NULL,
                    source_symbol TEXT,
                    target_symbol TEXT,
                    line_number INT,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_ref_repo_source
                ON {TABLE}(repo_id, source_file)
            """)
            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_ref_repo_target
                ON {TABLE}(repo_id, target_file)
            """)
    logger.info("Table %s ensured", TABLE)


@retry_on_disconnect
def upsert_references(
    repo_id: str,
    edges: List[Dict[str, Any]],
) -> int:
    """Insert a batch of reference edges, replacing any existing for the source files.

    Each edge dict must contain: ``source_file``, ``target_file``,
    ``reference_type``.  Optional: ``source_symbol``, ``target_symbol``,
    ``line_number``.

    Args:
        repo_id: Repository UUID.
        edges:   List of edge dicts.

    Returns:
        Number of edges inserted.
    """
    if not edges:
        return 0

    source_files = {e["source_file"] for e in edges}

    with get_connection() as conn:
        with conn.cursor() as cur:
            for sf in source_files:
                cur.execute(
                    f"DELETE FROM {TABLE} WHERE repo_id = %s AND source_file = %s",
                    (repo_id, sf),
                )

            for e in edges:
                cur.execute(
                    f"""
                    INSERT INTO {TABLE}
                        (repo_id, source_file, target_file, reference_type,
                         source_symbol, target_symbol, line_number)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        repo_id,
                        e["source_file"],
                        e["target_file"],
                        e["reference_type"],
                        e.get("source_symbol"),
                        e.get("target_symbol"),
                        e.get("line_number"),
                    ),
                )
    return len(edges)


@retry_on_disconnect
def delete_for_repo(repo_id: str) -> int:
    """Delete all reference edges for a repository.

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
    """Delete reference edges originating from specific source files.

    Args:
        repo_id:    Repository UUID.
        file_paths: Source file paths to clear.

    Returns:
        Number of rows deleted.
    """
    if not file_paths:
        return 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {TABLE} WHERE repo_id = %s AND source_file = ANY(%s)",
                (repo_id, file_paths),
            )
            return cur.rowcount or 0


@retry_on_disconnect
def get_importers(repo_id: str, target_file: str) -> List[Dict[str, Any]]:
    """Find files that import/reference a given target file.

    Args:
        repo_id:     Repository UUID.
        target_file: Path of the target file.

    Returns:
        List of edge dicts with ``source_file``, ``reference_type``,
        ``source_symbol``, ``target_symbol``.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT source_file, reference_type, source_symbol,
                       target_symbol, line_number
                FROM {TABLE}
                WHERE repo_id = %s AND target_file = %s
                """,
                (repo_id, target_file),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


@retry_on_disconnect
def get_dependencies(repo_id: str, source_file: str) -> List[Dict[str, Any]]:
    """Find files that a given source file imports/references.

    Args:
        repo_id:     Repository UUID.
        source_file: Path of the source file.

    Returns:
        List of edge dicts with ``target_file``, ``reference_type``,
        ``source_symbol``, ``target_symbol``.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT target_file, reference_type, source_symbol,
                       target_symbol, line_number
                FROM {TABLE}
                WHERE repo_id = %s AND source_file = %s
                """,
                (repo_id, source_file),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


@retry_on_disconnect
def get_all_edges(repo_id: str) -> List[Dict[str, Any]]:
    """Retrieve all reference edges for a repository.

    Args:
        repo_id: Repository UUID.

    Returns:
        List of all edge dicts.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT source_file, target_file, reference_type,
                       source_symbol, target_symbol, line_number
                FROM {TABLE}
                WHERE repo_id = %s
                ORDER BY source_file, line_number
                """,
                (repo_id,),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
