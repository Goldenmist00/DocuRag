"""
podcast_db.py
=============
Database operations for the ``podcasts`` table.

Each notebook can have one podcast generated from its sources.
"""

import logging
from typing import Dict, List, Optional

from src.db.connection import get_connection

logger = logging.getLogger(__name__)

_COLUMNS = (
    "id", "notebook_id", "status", "transcript",
    "audio_path", "error_message", "created_at", "updated_at",
)


def ensure_table() -> None:
    """
    Create the podcasts table if it does not exist.

    Called once during app startup to ensure the schema is ready.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS podcasts (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    notebook_id UUID NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
                    status TEXT NOT NULL DEFAULT 'pending',
                    transcript TEXT,
                    audio_path TEXT,
                    error_message TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
    logger.info("podcasts table ensured")


def create_podcast(notebook_id: str, status: str = "pending") -> Dict:
    """
    Insert a new podcast record.

    Args:
        notebook_id: Parent notebook UUID.
        status: Initial status (default "pending").

    Returns:
        Podcast dict with all columns.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO podcasts (notebook_id, status)
                VALUES (%s, %s)
                RETURNING {', '.join(_COLUMNS)}
                """,
                (notebook_id, status),
            )
            return _row_to_dict(cur.fetchone())


def get_podcast(podcast_id: str) -> Optional[Dict]:
    """
    Fetch a single podcast by its ID.

    Args:
        podcast_id: UUID string.

    Returns:
        Podcast dict or None if not found.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {', '.join(_COLUMNS)} FROM podcasts WHERE id = %s",
                (podcast_id,),
            )
            row = cur.fetchone()
    return _row_to_dict(row) if row else None


def get_podcast_by_notebook(notebook_id: str) -> Optional[Dict]:
    """
    Fetch the most recent podcast for a notebook.

    Args:
        notebook_id: Parent notebook UUID.

    Returns:
        Podcast dict or None if no podcast exists.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {', '.join(_COLUMNS)}
                FROM podcasts
                WHERE notebook_id = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (notebook_id,),
            )
            row = cur.fetchone()
    return _row_to_dict(row) if row else None


def list_podcasts(notebook_id: str) -> List[Dict]:
    """
    Return all podcasts for a notebook, newest first.

    Args:
        notebook_id: Parent notebook UUID.

    Returns:
        List of podcast dicts.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {', '.join(_COLUMNS)}
                FROM podcasts
                WHERE notebook_id = %s
                ORDER BY created_at DESC
                """,
                (notebook_id,),
            )
            return [_row_to_dict(r) for r in cur.fetchall()]


def update_podcast(podcast_id: str, **fields) -> Optional[Dict]:
    """
    Update fields on a podcast row.

    Allowed keys: status, transcript, audio_path, error_message.

    Args:
        podcast_id: UUID string.
        **fields: Column-value pairs to update.

    Returns:
        Updated podcast dict, or None if not found.

    Raises:
        ValueError: If an unknown field is passed.
    """
    allowed = {"status", "transcript", "audio_path", "error_message"}
    invalid = set(fields.keys()) - allowed
    if invalid:
        raise ValueError(f"Cannot update fields: {invalid}")

    set_clauses = ", ".join(f"{k} = %s" for k in fields)
    values = list(fields.values()) + [podcast_id]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE podcasts SET {set_clauses}, updated_at = NOW()
                WHERE id = %s
                RETURNING {', '.join(_COLUMNS)}
                """,
                values,
            )
            row = cur.fetchone()
    return _row_to_dict(row) if row else None


def delete_podcast(podcast_id: str) -> bool:
    """
    Delete a podcast record.

    Args:
        podcast_id: UUID string.

    Returns:
        True if a row was deleted.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM podcasts WHERE id = %s", (podcast_id,))
            return cur.rowcount > 0


def delete_by_notebook(notebook_id: str) -> int:
    """
    Delete all podcasts for a notebook.

    Args:
        notebook_id: Parent notebook UUID.

    Returns:
        Number of rows deleted.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM podcasts WHERE notebook_id = %s", (notebook_id,))
            return cur.rowcount


def _row_to_dict(row) -> Dict:
    """Map a full podcast row tuple to a dict."""
    d = dict(zip(_COLUMNS, row))
    d["id"] = str(d["id"])
    d["notebook_id"] = str(d["notebook_id"])
    for ts in ("created_at", "updated_at"):
        if d.get(ts):
            d[ts] = d[ts].isoformat()
    return d
