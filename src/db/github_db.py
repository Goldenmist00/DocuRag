"""
github_db.py
============
Database operations for GitHub OAuth tokens.

Stores one access token per unique GitHub username so the
``create_github_pr`` flow can authenticate API requests.
"""

import logging
from typing import Any, Dict, Optional

from src.db.connection import get_connection, retry_on_disconnect

logger = logging.getLogger(__name__)

TABLE = "github_tokens"


def ensure_table() -> None:
    """Create the ``github_tokens`` table if it does not exist.

    Returns:
        None

    Raises:
        psycopg2.Error: If DDL execution fails.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {TABLE} (
                    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    github_user   TEXT NOT NULL UNIQUE,
                    access_token  TEXT NOT NULL,
                    token_type    TEXT DEFAULT 'bearer',
                    scope         TEXT DEFAULT '',
                    created_at    TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    updated_at    TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
        conn.commit()
    logger.info("github_tokens table ensured")


@retry_on_disconnect
def upsert_token(
    github_user: str,
    access_token: str,
    token_type: str = "bearer",
    scope: str = "",
) -> Dict[str, Any]:
    """Insert or update a GitHub access token for a user.

    Args:
        github_user:  GitHub username.
        access_token: OAuth access token.
        token_type:   Token type string (usually ``"bearer"``).
        scope:        Granted OAuth scopes.

    Returns:
        Dict with ``github_user`` and ``updated`` flag.

    Raises:
        psycopg2.Error: On database failure.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {TABLE} (github_user, access_token, token_type, scope)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (github_user)
                DO UPDATE SET access_token = EXCLUDED.access_token,
                              token_type   = EXCLUDED.token_type,
                              scope        = EXCLUDED.scope,
                              updated_at   = CURRENT_TIMESTAMP
                RETURNING id;
                """,
                (github_user, access_token, token_type, scope),
            )
            row = cur.fetchone()
        conn.commit()
    logger.info("Upserted GitHub token for user=%s", github_user)
    return {"github_user": github_user, "id": str(row[0]) if row else None}


@retry_on_disconnect
def get_token() -> Optional[str]:
    """Return the most recently updated GitHub access token.

    Since MindSync is currently single-user, this simply returns the
    latest token.  For multi-user, filter by the authenticated user.

    Returns:
        The access token string, or ``None`` if none stored.

    Raises:
        psycopg2.Error: On database failure.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT access_token FROM {TABLE} ORDER BY updated_at DESC LIMIT 1"
            )
            row = cur.fetchone()
    return row[0] if row else None


@retry_on_disconnect
def get_github_user() -> Optional[Dict[str, Any]]:
    """Return the most recently connected GitHub user info.

    Returns:
        Dict with ``github_user`` and ``scope``, or ``None``.

    Raises:
        psycopg2.Error: On database failure.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT github_user, scope, updated_at FROM {TABLE} "
                f"ORDER BY updated_at DESC LIMIT 1"
            )
            row = cur.fetchone()
    if not row:
        return None
    return {
        "github_user": row[0],
        "scope": row[1],
        "connected_at": str(row[2]) if row[2] else None,
    }


@retry_on_disconnect
def delete_token(github_user: str) -> bool:
    """Remove a stored GitHub token (disconnect).

    Args:
        github_user: GitHub username to remove.

    Returns:
        True if a row was deleted.

    Raises:
        psycopg2.Error: On database failure.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {TABLE} WHERE github_user = %s", (github_user,)
            )
            deleted = cur.rowcount > 0
        conn.commit()
    return deleted
