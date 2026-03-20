"""
source_db.py
============
Database operations for the ``sources`` table.
"""

import logging
from typing import Dict, List, Optional

from src.db.connection import get_connection

logger = logging.getLogger(__name__)

_COLUMNS = (
    "id", "notebook_id", "name", "source_type", "file_path",
    "raw_content", "status", "error_message", "chunk_count",
    "created_at", "updated_at",
)


def create_source(
    notebook_id: str,
    name: str,
    source_type: str = "file",
    file_path: Optional[str] = None,
    raw_content: Optional[str] = None,
    status: str = "pending",
) -> Dict:
    """
    Insert a new source record.

    Args:
        notebook_id: Parent notebook UUID.
        name:        Display name (e.g. "report.pdf" or "Pasted text").
        source_type: "file" or "text".
        file_path:   Disk path for uploaded files.
        raw_content: Full text for pasted-text sources.
        status:      Initial status (default "pending").

    Returns:
        Source dict with all columns.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO sources
                    (notebook_id, name, source_type, file_path, raw_content, status)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING {', '.join(_COLUMNS)}
                """,
                (notebook_id, name, source_type, file_path, raw_content, status),
            )
            return _row_to_dict(cur.fetchone())


def list_sources(notebook_id: str) -> List[Dict]:
    """
    Return all sources for a notebook, newest first.

    Args:
        notebook_id: Parent notebook UUID.

    Returns:
        List of source dicts.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {', '.join(_COLUMNS)}
                FROM sources
                WHERE notebook_id = %s
                ORDER BY created_at DESC
                """,
                (notebook_id,),
            )
            return [_row_to_dict(r) for r in cur.fetchall()]


def get_source(source_id: str) -> Optional[Dict]:
    """
    Fetch a single source by ID.

    Args:
        source_id: UUID string.

    Returns:
        Source dict or None if not found.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {', '.join(_COLUMNS)} FROM sources WHERE id = %s",
                (source_id,),
            )
            row = cur.fetchone()
    return _row_to_dict(row) if row else None


def update_source(source_id: str, **fields) -> Optional[Dict]:
    """
    Update arbitrary fields on a source row.

    Allowed keys: status, error_message, chunk_count, name.

    Args:
        source_id: UUID string.
        **fields:  Column-value pairs to update.

    Returns:
        Updated source dict, or None if not found.

    Raises:
        ValueError: If an unknown field is passed.
    """
    allowed = {"status", "error_message", "chunk_count", "name"}
    invalid = set(fields.keys()) - allowed
    if invalid:
        raise ValueError(f"Cannot update fields: {invalid}")

    set_clauses = ", ".join(f"{k} = %s" for k in fields)
    values = list(fields.values()) + [source_id]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE sources SET {set_clauses}
                WHERE id = %s
                RETURNING {', '.join(_COLUMNS)}
                """,
                values,
            )
            row = cur.fetchone()
    return _row_to_dict(row) if row else None


def delete_source(source_id: str) -> bool:
    """
    Delete a source (chunks are cascade-deleted by FK).

    Args:
        source_id: UUID string.

    Returns:
        True if a row was deleted.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sources WHERE id = %s", (source_id,))
            return cur.rowcount > 0


def _row_to_dict(row) -> Dict:
    """Map a full source row tuple to a dict."""
    d = dict(zip(_COLUMNS, row))
    d["id"] = str(d["id"])
    d["notebook_id"] = str(d["notebook_id"])
    for ts in ("created_at", "updated_at"):
        if d.get(ts):
            d[ts] = d[ts].isoformat()
    return d
