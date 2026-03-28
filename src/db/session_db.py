"""
session_db.py
=============
Database operations for ``worktrees`` and ``agent_sessions`` tables.

This is the DB-service layer: SQL only, no business logic.
"""

import json
import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2.extras import Json

from src.db.connection import get_connection, retry_on_disconnect


def _json_serial(obj: Any) -> str:
    """Serialize datetime/date for JSON columns."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _safe_json(data: Any) -> Json:
    """Wrap data in psycopg2 Json with datetime-safe serializer."""
    return Json(data, dumps=lambda o: json.dumps(o, default=_json_serial))

logger = logging.getLogger(__name__)

WORKTREES_TABLE = "worktrees"
AGENT_SESSIONS_TABLE = "agent_sessions"


def ensure_table() -> None:
    """Create ``worktrees``, ``agent_sessions`` tables and indexes if missing.

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
                f"""
                CREATE TABLE IF NOT EXISTS {WORKTREES_TABLE} (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    repo_id UUID NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
                    branch_name TEXT NOT NULL,
                    worktree_path TEXT NOT NULL,
                    base_commit TEXT,
                    status TEXT DEFAULT 'active',
                    files_changed INT DEFAULT 0,
                    insertions INT DEFAULT 0,
                    deletions INT DEFAULT 0,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {AGENT_SESSIONS_TABLE} (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    repo_id UUID NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
                    worktree_id UUID REFERENCES {WORKTREES_TABLE}(id),
                    task_description TEXT NOT NULL,
                    status TEXT DEFAULT 'queued',
                    current_step TEXT,
                    agent_log JSONB DEFAULT '[]',
                    plan JSONB DEFAULT '[]',
                    result_summary TEXT,
                    error_message TEXT,
                    context_snapshot JSONB DEFAULT '{{}}',
                    conversation_history JSONB DEFAULT '[]',
                    total_llm_calls INT DEFAULT 0,
                    total_tokens_used INT DEFAULT 0,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    started_at TIMESTAMPTZ,
                    completed_at TIMESTAMPTZ
                )
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_as_repo
                ON {AGENT_SESSIONS_TABLE}(repo_id)
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_as_status
                ON {AGENT_SESSIONS_TABLE}(repo_id, status)
                """
            )
    logger.info(
        "Tables '%s' and '%s' ensured",
        WORKTREES_TABLE,
        AGENT_SESSIONS_TABLE,
    )


def insert_worktree(
    repo_id: str,
    branch_name: str,
    worktree_path: str,
    base_commit: Optional[str] = None,
) -> Dict[str, Any]:
    """Insert a worktree row and return it as a dict.

    Args:
        repo_id:        UUID of the parent repo.
        branch_name:    Git branch name for the worktree.
        worktree_path:  Absolute path to the worktree directory.
        base_commit:    Optional base commit SHA.

    Returns:
        Dict with all columns of the new row.

    Raises:
        psycopg2.Error: If the insert fails.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {WORKTREES_TABLE}
                    (repo_id, branch_name, worktree_path, base_commit)
                VALUES (%s, %s, %s, %s)
                RETURNING *
                """,
                (repo_id, branch_name, worktree_path, base_commit),
            )
            row = cur.fetchone()
            cols = [desc[0] for desc in cur.description]
            return dict(zip(cols, row))


def find_worktree_by_id(worktree_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a worktree by UUID.

    Args:
        worktree_id: UUID of the worktree.

    Returns:
        Dict with all columns, or ``None`` if not found.

    Raises:
        psycopg2.Error: If the query fails.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT * FROM {WORKTREES_TABLE} WHERE id = %s",
                (worktree_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cols = [desc[0] for desc in cur.description]
            return dict(zip(cols, row))


def update_worktree_status(worktree_id: str, status: str) -> None:
    """Update worktree ``status`` and ``updated_at``.

    Args:
        worktree_id: UUID of the worktree.
        status:      New status value.

    Returns:
        None

    Raises:
        psycopg2.Error: If the update fails.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {WORKTREES_TABLE}
                SET status = %s,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (status, worktree_id),
            )


def update_worktree_stats(
    worktree_id: str,
    files_changed: int,
    insertions: int,
    deletions: int,
) -> None:
    """Update worktree diff stats and ``updated_at``.

    Args:
        worktree_id:   UUID of the worktree.
        files_changed: Count of files changed.
        insertions:    Line insertions count.
        deletions:     Line deletions count.

    Returns:
        None

    Raises:
        psycopg2.Error: If the update fails.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {WORKTREES_TABLE}
                SET files_changed = %s,
                    insertions = %s,
                    deletions = %s,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (files_changed, insertions, deletions, worktree_id),
            )


def list_active_worktrees(repo_id: str) -> List[Dict[str, Any]]:
    """Return worktrees for a repo with ``status`` = ``active``.

    Args:
        repo_id: UUID of the repo.

    Returns:
        List of row dicts.

    Raises:
        psycopg2.Error: If the query fails.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT * FROM {WORKTREES_TABLE}
                WHERE repo_id = %s AND status = 'active'
                ORDER BY created_at DESC
                """,
                (repo_id,),
            )
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


@retry_on_disconnect
def insert_session(
    repo_id: str,
    worktree_id: Optional[str],
    task_description: str,
    context_snapshot: Dict[str, Any],
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Insert an agent session with JSONB ``context_snapshot``.

    Args:
        repo_id:           UUID of the repo.
        worktree_id:       UUID of the worktree, or ``None``.
        task_description:  User-facing task text.
        context_snapshot:  Serializable dict stored as JSONB.
        session_id:        If set, use this UUID as primary key (else DB-generated).

    Returns:
        Dict with all columns of the new row.

    Raises:
        psycopg2.Error: If the insert fails.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            if session_id is None:
                cur.execute(
                    f"""
                    INSERT INTO {AGENT_SESSIONS_TABLE}
                        (repo_id, worktree_id, task_description, context_snapshot)
                    VALUES (%s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        repo_id,
                        worktree_id,
                        task_description,
                        _safe_json(context_snapshot),
                    ),
                )
            else:
                cur.execute(
                    f"""
                    INSERT INTO {AGENT_SESSIONS_TABLE}
                        (id, repo_id, worktree_id, task_description, context_snapshot)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        session_id,
                        repo_id,
                        worktree_id,
                        task_description,
                        _safe_json(context_snapshot),
                    ),
                )
            row = cur.fetchone()
            cols = [desc[0] for desc in cur.description]
            return dict(zip(cols, row))


def find_by_id(session_id: str) -> Optional[Dict[str, Any]]:
    """Fetch an agent session by UUID.

    Args:
        session_id: UUID of the session.

    Returns:
        Dict with all columns, or ``None`` if not found.

    Raises:
        psycopg2.Error: If the query fails.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT * FROM {AGENT_SESSIONS_TABLE} WHERE id = %s",
                (session_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cols = [desc[0] for desc in cur.description]
            return dict(zip(cols, row))


def list_by_repo(repo_id: str) -> List[Dict[str, Any]]:
    """List all sessions for a repo, newest first.

    Args:
        repo_id: UUID of the repo.

    Returns:
        List of row dicts ordered by ``created_at`` descending.

    Raises:
        psycopg2.Error: If the query fails.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT * FROM {AGENT_SESSIONS_TABLE}
                WHERE repo_id = %s
                ORDER BY created_at DESC
                """,
                (repo_id,),
            )
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


@retry_on_disconnect
def update_session_status(
    session_id: str,
    status: str,
    current_step: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    """Update session status and optionally ``current_step`` / ``error_message``.

    Args:
        session_id:     UUID of the session.
        status:         New status value.
        current_step:   If not ``None``, updates ``current_step``.
        error_message:  If not ``None``, updates ``error_message``.

    Returns:
        None

    Raises:
        psycopg2.Error: If the update fails.
    """
    sets = ["status = %s"]
    params: List[Any] = [status]
    if current_step is not None:
        sets.append("current_step = %s")
        params.append(current_step)
    if error_message is not None:
        sets.append("error_message = %s")
        params.append(error_message)
    params.append(session_id)
    sql = f"""
        UPDATE {AGENT_SESSIONS_TABLE}
        SET {", ".join(sets)}
        WHERE id = %s
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))


@retry_on_disconnect
def update_session_log(
    session_id: str,
    agent_log: List[Any],
    plan: List[Any],
) -> None:
    """Persist ``agent_log`` and ``plan`` JSONB arrays.

    Args:
        session_id: UUID of the session.
        agent_log:  List serialized to JSONB.
        plan:       List serialized to JSONB.

    Returns:
        None

    Raises:
        psycopg2.Error: If the update fails.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {AGENT_SESSIONS_TABLE}
                SET agent_log = %s,
                    plan = %s
                WHERE id = %s
                """,
                (_safe_json(agent_log), _safe_json(plan), session_id),
            )


@retry_on_disconnect
def update_session_result(
    session_id: str,
    result_summary: str,
    total_llm_calls: int,
    total_tokens_used: int,
) -> None:
    """Update result summary and token/call counters.

    Args:
        session_id:        UUID of the session.
        result_summary:    Final or partial summary text.
        total_llm_calls:   Cumulative LLM call count.
        total_tokens_used: Cumulative token usage.

    Returns:
        None

    Raises:
        psycopg2.Error: If the update fails.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {AGENT_SESSIONS_TABLE}
                SET result_summary = %s,
                    total_llm_calls = %s,
                    total_tokens_used = %s
                WHERE id = %s
                """,
                (result_summary, total_llm_calls, total_tokens_used, session_id),
            )


def update_conversation_history(
    session_id: str,
    conversation_history: List[Any],
) -> None:
    """Replace ``conversation_history`` JSONB for a session.

    Args:
        session_id:            UUID of the session.
        conversation_history:  List serialized to JSONB.

    Returns:
        None

    Raises:
        psycopg2.Error: If the update fails.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {AGENT_SESSIONS_TABLE}
                SET conversation_history = %s
                WHERE id = %s
                """,
                (_safe_json(conversation_history), session_id),
            )


def list_running_sessions(repo_id: str) -> List[Dict[str, Any]]:
    """Sessions for a repo in queued, planning, or running state.

    Args:
        repo_id: UUID of the repo.

    Returns:
        List of row dicts.

    Raises:
        psycopg2.Error: If the query fails.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT * FROM {AGENT_SESSIONS_TABLE}
                WHERE repo_id = %s
                  AND status IN ('queued', 'planning', 'running')
                ORDER BY created_at ASC
                """,
                (repo_id,),
            )
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def mark_session_completed(session_id: str, result_summary: str) -> None:
    """Set session to completed with summary and ``completed_at``.

    Args:
        session_id:     UUID of the session.
        result_summary: Final summary text.

    Returns:
        None

    Raises:
        psycopg2.Error: If the update fails.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {AGENT_SESSIONS_TABLE}
                SET status = 'completed',
                    result_summary = %s,
                    completed_at = NOW()
                WHERE id = %s
                """,
                (result_summary, session_id),
            )


def mark_session_failed(session_id: str, error_message: str) -> None:
    """Set session to failed with error text and ``completed_at``.

    Args:
        session_id:    UUID of the session.
        error_message: Failure description.

    Returns:
        None

    Raises:
        psycopg2.Error: If the update fails.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {AGENT_SESSIONS_TABLE}
                SET status = 'failed',
                    error_message = %s,
                    completed_at = NOW()
                WHERE id = %s
                """,
                (error_message, session_id),
            )
