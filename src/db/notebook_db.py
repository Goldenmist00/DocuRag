"""
notebook_db.py
==============
Database operations for the ``notebooks`` table.

Every function accepts/returns plain dicts — no business logic here.
"""

import logging
from typing import Any, Dict, List, Optional

from psycopg2.extras import Json

from src.db.connection import get_connection

logger = logging.getLogger(__name__)


def ensure_user_id_column() -> None:
    """Add ``user_id`` TEXT column to notebooks if missing.

    Raises:
        psycopg2.Error: If DDL execution fails.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'notebooks'
                          AND column_name = 'user_id'
                    ) THEN
                        ALTER TABLE notebooks ADD COLUMN user_id TEXT;
                        CREATE INDEX IF NOT EXISTS idx_notebooks_user_id
                            ON notebooks(user_id);
                    END IF;
                END $$;
                """
            )
    logger.info("Ensured 'user_id' column on notebooks table")


def create_notebook(title: str = "Untitled notebook", user_id: Optional[str] = None) -> Dict:
    """
    Insert a new notebook row.

    Args:
        title:   Display title for the notebook.
        user_id: Email of the owning user (for multi-tenancy).

    Returns:
        Dict with id, title, created_at, updated_at.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO notebooks (title, user_id)
                VALUES (%s, %s)
                RETURNING id, title, created_at, updated_at
                """,
                (title, user_id),
            )
            row = cur.fetchone()
    return _row_to_dict(row)


def list_notebooks(user_id: Optional[str] = None) -> List[Dict]:
    """
    Return notebooks ordered by most-recently updated first.

    When ``user_id`` is provided, only notebooks owned by that user
    (or unowned legacy notebooks) are returned.

    Args:
        user_id: If set, filter to this user's notebooks.

    Returns:
        List of notebook dicts.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            if user_id:
                cur.execute(
                    """
                    SELECT n.id, n.title, n.created_at, n.updated_at,
                           COALESCE(s.cnt, 0) AS source_count
                    FROM notebooks n
                    LEFT JOIN (
                        SELECT notebook_id, COUNT(*) AS cnt
                        FROM sources GROUP BY notebook_id
                    ) s ON s.notebook_id = n.id
                    WHERE n.user_id = %s OR n.user_id IS NULL
                    ORDER BY n.updated_at DESC
                    """,
                    (user_id,),
                )
            else:
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


def ensure_conversation_history_column() -> None:
    """Add ``conversation_history`` JSONB column to notebooks if missing.

    Args:
        None

    Returns:
        None

    Raises:
        psycopg2.Error: If DDL execution fails.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'notebooks'
                          AND column_name = 'conversation_history'
                    ) THEN
                        ALTER TABLE notebooks
                            ADD COLUMN conversation_history JSONB DEFAULT '[]';
                    END IF;
                END $$;
                """
            )
    logger.info("Ensured 'conversation_history' column on notebooks table")


def get_conversation_history(notebook_id: str) -> List[Dict[str, Any]]:
    """Fetch the conversation history for a notebook.

    Args:
        notebook_id: UUID string.

    Returns:
        List of message dicts (role + content), or empty list.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COALESCE(conversation_history, '[]'::jsonb)
                FROM notebooks WHERE id = %s
                """,
                (notebook_id,),
            )
            row = cur.fetchone()
    if row is None:
        return []
    return list(row[0]) if row[0] else []


def append_conversation_entry(
    notebook_id: str,
    entry: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Append a single message entry to the notebook conversation history.

    Args:
        notebook_id: UUID string.
        entry:       Dict with at least ``role`` and ``content``.

    Returns:
        The updated full conversation history list.

    Raises:
        psycopg2.Error: If the update fails.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE notebooks
                SET conversation_history = COALESCE(conversation_history, '[]'::jsonb) || %s::jsonb
                WHERE id = %s
                RETURNING conversation_history
                """,
                (Json([entry]), notebook_id),
            )
            row = cur.fetchone()
    return list(row[0]) if row and row[0] else []


def clear_conversation_history(notebook_id: str) -> bool:
    """Reset the conversation history for a notebook to an empty array.

    Args:
        notebook_id: UUID string.

    Returns:
        True if the notebook was found and updated.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE notebooks
                SET conversation_history = '[]'::jsonb
                WHERE id = %s
                """,
                (notebook_id,),
            )
            return cur.rowcount > 0


def _row_to_dict(row) -> Dict:
    """Map a (id, title, created_at, updated_at) row to a dict."""
    return {
        "id": str(row[0]),
        "title": row[1],
        "created_at": row[2].isoformat() if row[2] else None,
        "updated_at": row[3].isoformat() if row[3] else None,
    }
