"""
notebook_db.py
==============
Database operations for the ``notebooks`` table.

Every function accepts/returns plain dicts — no business logic here.
"""

import logging
from typing import Dict, List, Optional

from src.db.connection import get_connection

logger = logging.getLogger(__name__)


def create_notebook(title: str = "Untitled notebook") -> Dict:
    """
    Insert a new notebook row.

    Args:
        title: Display title for the notebook.

    Returns:
        Dict with id, title, created_at, updated_at.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO notebooks (title)
                VALUES (%s)
                RETURNING id, title, created_at, updated_at
                """,
                (title,),
            )
            row = cur.fetchone()
    return _row_to_dict(row)


def list_notebooks() -> List[Dict]:
    """
    Return all notebooks ordered by most-recently updated first.

    Each dict includes a ``source_count`` derived from the sources table.

    Returns:
        List of notebook dicts.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT n.id, n.title, n.created_at, n.updated_at,
                       COALESCE(s.cnt, 0) AS source_count
                FROM notebooks n
                LEFT JOIN (
                    SELECT notebook_id, COUNT(*) AS cnt
                    FROM sources GROUP BY notebook_id
                ) s ON s.notebook_id = n.id
                ORDER BY n.updated_at DESC
                """
            )
            return [
                {
                    "id": str(r[0]),
                    "title": r[1],
                    "created_at": r[2].isoformat() if r[2] else None,
                    "updated_at": r[3].isoformat() if r[3] else None,
                    "source_count": r[4],
                }
                for r in cur.fetchall()
            ]


def get_notebook(notebook_id: str) -> Optional[Dict]:
    """
    Fetch a single notebook by ID.

    Args:
        notebook_id: UUID string.

    Returns:
        Notebook dict or None if not found.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, title, created_at, updated_at
                FROM notebooks WHERE id = %s
                """,
                (notebook_id,),
            )
            row = cur.fetchone()
    return _row_to_dict(row) if row else None


def update_notebook(notebook_id: str, title: str) -> Optional[Dict]:
    """
    Update a notebook's title.

    Args:
        notebook_id: UUID string.
        title: New title.

    Returns:
        Updated notebook dict or None if not found.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE notebooks SET title = %s
                WHERE id = %s
                RETURNING id, title, created_at, updated_at
                """,
                (title, notebook_id),
            )
            row = cur.fetchone()
    return _row_to_dict(row) if row else None


def delete_notebook(notebook_id: str) -> bool:
    """
    Delete a notebook and cascade-delete its sources and chunks.

    Args:
        notebook_id: UUID string.

    Returns:
        True if a row was deleted, False if not found.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM notebooks WHERE id = %s", (notebook_id,))
            return cur.rowcount > 0


def _row_to_dict(row) -> Dict:
    """Map a (id, title, created_at, updated_at) row to a dict."""
    return {
        "id": str(row[0]),
        "title": row[1],
        "created_at": row[2].isoformat() if row[2] else None,
        "updated_at": row[3].isoformat() if row[3] else None,
    }
