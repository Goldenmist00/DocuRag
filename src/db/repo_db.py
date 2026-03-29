"""
repo_db.py
==========
Database operations for the ``repos`` table.

This is the DB-service layer: SQL only, no business logic.
All business rules live in the git and orchestrator service modules.
"""

import logging
from typing import Any, Dict, List, Optional

from src.db.connection import get_connection

logger = logging.getLogger(__name__)

TABLE = "repos"


def ensure_table() -> None:
    """Create the ``repos`` table and indexes if they do not exist.

    Also adds the ``user_id`` column for multi-tenancy if missing.

    Raises:
        RuntimeError: If table creation fails.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {TABLE} (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    name TEXT NOT NULL,
                    remote_url TEXT NOT NULL,
                    local_path TEXT NOT NULL,
                    default_branch TEXT DEFAULT 'main',
                    auth_token_hash TEXT,
                    total_files INT DEFAULT 0,
                    indexed_files INT DEFAULT 0,
                    indexing_status TEXT DEFAULT 'pending',
                    indexing_phase TEXT DEFAULT '',
                    indexing_progress REAL DEFAULT 0,
                    indexing_detail TEXT DEFAULT '',
                    error_message TEXT,
                    last_indexed_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_repos_status
                ON {TABLE}(indexing_status)
            """)
            cur.execute(f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = '{TABLE}'
                          AND column_name = 'user_id'
                    ) THEN
                        ALTER TABLE {TABLE} ADD COLUMN user_id TEXT;
                        CREATE INDEX IF NOT EXISTS idx_repos_user_id
                            ON {TABLE}(user_id);
                    END IF;
                END $$;
            """)
    logger.info("Table '%s' ensured", TABLE)


def insert(
    name: str,
    remote_url: str,
    local_path: str,
    default_branch: str = "main",
    auth_token_hash: Optional[str] = None,
    repo_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Insert a new repo record and return it as a dict.

    Args:
        name:             Repository display name.
        remote_url:       GitHub clone URL.
        local_path:       Filesystem path where the repo is cloned.
        default_branch:   Default branch name.
        auth_token_hash:  Hashed PAT for private repos (optional).
        repo_id:          If set, use this UUID as primary key (else DB-generated).
        user_id:          Email of the owning user (for multi-tenancy).

    Returns:
        Dict with all columns of the new row.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            if repo_id is None:
                cur.execute(
                    f"""
                    INSERT INTO {TABLE}
                        (name, remote_url, local_path, default_branch, auth_token_hash, user_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (name, remote_url, local_path, default_branch, auth_token_hash, user_id),
                )
            else:
                cur.execute(
                    f"""
                    INSERT INTO {TABLE}
                        (id, name, remote_url, local_path, default_branch, auth_token_hash, user_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (repo_id, name, remote_url, local_path, default_branch, auth_token_hash, user_id),
                )
            row = cur.fetchone()
            cols = [desc[0] for desc in cur.description]
            return dict(zip(cols, row))


def find_by_id(repo_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a repo by its UUID.

    Args:
        repo_id: UUID of the repo.

    Returns:
        Dict with all columns, or ``None`` if not found.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM {TABLE} WHERE id = %s", (repo_id,))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [desc[0] for desc in cur.description]
            return dict(zip(cols, row))


def find_by_remote_url(remote_url: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Fetch a repo by its remote URL, optionally scoped to a user.

    Args:
        remote_url: GitHub clone URL.
        user_id:    If set, restrict to this user's repos.

    Returns:
        Dict with all columns, or ``None`` if not found.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            if user_id:
                cur.execute(
                    f"SELECT * FROM {TABLE} WHERE remote_url = %s AND (user_id = %s OR user_id IS NULL)",
                    (remote_url, user_id),
                )
            else:
                cur.execute(
                    f"SELECT * FROM {TABLE} WHERE remote_url = %s", (remote_url,),
                )
            row = cur.fetchone()
            if row is None:
                return None
            cols = [desc[0] for desc in cur.description]
            return dict(zip(cols, row))


def list_all(user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return repos ordered by creation date descending.

    When ``user_id`` is provided, only repos owned by that user
    (or unowned legacy repos) are returned.

    Args:
        user_id: If set, filter to this user's repos.

    Returns:
        List of dicts, one per repo.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            if user_id:
                cur.execute(
                    f"SELECT * FROM {TABLE} WHERE user_id = %s OR user_id IS NULL ORDER BY created_at DESC",
                    (user_id,),
                )
            else:
                cur.execute(
                    f"SELECT * FROM {TABLE} ORDER BY created_at DESC",
                )
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def update_status(
    repo_id: str,
    indexing_status: str,
    error_message: Optional[str] = None,
) -> None:
    """Update the indexing status of a repo.

    Args:
        repo_id:          UUID of the repo.
        indexing_status:   New status string.
        error_message:     Optional error detail (cleared if ``None``).
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {TABLE}
                SET indexing_status = %s,
                    error_message  = %s,
                    updated_at     = NOW()
                WHERE id = %s
                """,
                (indexing_status, error_message, repo_id),
            )


def update_file_counts(
    repo_id: str,
    total_files: int,
    indexed_files: int,
) -> None:
    """Update file-count progress columns.

    Args:
        repo_id:       UUID of the repo.
        total_files:   Total files discovered.
        indexed_files: Files ingested so far.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {TABLE}
                SET total_files   = %s,
                    indexed_files = %s,
                    updated_at    = NOW()
                WHERE id = %s
                """,
                (total_files, indexed_files, repo_id),
            )


def update_progress(
    repo_id: str,
    phase: str,
    current: int,
    total: int,
    detail: str = "",
) -> None:
    """Update granular progress columns for real-time UI feedback.

    Only writes to ``indexed_files`` when the phase is ``ingesting`` or
    ``complete`` — other phases (embedding, consolidating, etc.) use
    ``current`` for their own counters which must not overwrite the
    actual file count.

    Args:
        repo_id:  UUID of the repo.
        phase:    Current pipeline phase (e.g. 'cloning', 'parsing', 'ingesting',
                  'embedding', 'building_graph', 'consolidating').
        current:  Items completed so far in this phase.
        total:    Total items expected in this phase.
        detail:   Human-readable detail string (e.g. current file name).
    """
    pct = round((current / total) * 100, 1) if total > 0 else 0.0
    updates_indexed = phase in ("ingesting", "complete")
    with get_connection() as conn:
        with conn.cursor() as cur:
            if updates_indexed:
                cur.execute(
                    f"""
                    UPDATE {TABLE}
                    SET indexing_phase    = %s,
                        indexing_progress = %s,
                        indexed_files     = %s,
                        indexing_detail   = %s,
                        updated_at        = NOW()
                    WHERE id = %s
                    """,
                    (phase, pct, current, detail[:200], repo_id),
                )
            else:
                cur.execute(
                    f"""
                    UPDATE {TABLE}
                    SET indexing_phase    = %s,
                        indexing_progress = %s,
                        indexing_detail   = %s,
                        updated_at        = NOW()
                    WHERE id = %s
                    """,
                    (phase, pct, detail[:200], repo_id),
                )


def mark_indexed(repo_id: str) -> None:
    """Mark a repo as fully indexed and set ``last_indexed_at``.

    Clears progress fields so the UI no longer shows an active phase.

    Args:
        repo_id: UUID of the repo.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {TABLE}
                SET indexing_status   = 'ready',
                    indexing_phase    = '',
                    indexing_progress = 0,
                    indexing_detail   = '',
                    last_indexed_at   = NOW(),
                    updated_at        = NOW()
                WHERE id = %s
                """,
                (repo_id,),
            )


def delete(repo_id: str) -> bool:
    """Delete a repo by its UUID (cascades to all child tables).

    Args:
        repo_id: UUID of the repo.

    Returns:
        ``True`` if a row was deleted, ``False`` otherwise.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {TABLE} WHERE id = %s", (repo_id,))
            return cur.rowcount > 0
