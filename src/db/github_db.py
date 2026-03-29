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

    Also adds the ``user_id`` column for multi-tenancy if missing.

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
            cur.execute(
                f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = '{TABLE}'
                          AND column_name = 'user_id'
                    ) THEN
                        ALTER TABLE {TABLE} ADD COLUMN user_id TEXT;
                        CREATE INDEX IF NOT EXISTS idx_github_tokens_user_id
                            ON {TABLE}(user_id);
                    END IF;
                END $$;
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
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Insert or update a GitHub access token for a user.

    Args:
        github_user:  GitHub username.
        access_token: OAuth access token.
        token_type:   Token type string (usually ``"bearer"``).
        scope:        Granted OAuth scopes.
        user_id:      App user email for multi-tenancy association.

    Returns:
        Dict with ``github_user`` and ``updated`` flag.

    Raises:
        psycopg2.Error: On database failure.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {TABLE} (github_user, access_token, token_type, scope, user_id)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (github_user)
                DO UPDATE SET access_token = EXCLUDED.access_token,
                              token_type   = EXCLUDED.token_type,
                              scope        = EXCLUDED.scope,
                              user_id      = EXCLUDED.user_id,
                              updated_at   = CURRENT_TIMESTAMP
                RETURNING id;
                """,
                (github_user, access_token, token_type, scope, user_id),
            )
            row = cur.fetchone()
        conn.commit()
    logger.info("Upserted GitHub token for user=%s (app_user=%s)", github_user, user_id)
    return {"github_user": github_user, "id": str(row[0]) if row else None}


@retry_on_disconnect
def get_token(user_id: Optional[str] = None) -> Optional[str]:
    """Return the GitHub access token for a specific app user.

    When ``user_id`` is provided, returns the token associated with
    that app user. Falls back to the latest token if no user is specified
    (backward-compatible).

    Args:
        user_id: App user email to look up.

    Returns:
        The access token string, or ``None`` if none stored.

    Raises:
        psycopg2.Error: On database failure.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            if user_id:
                cur.execute(
                    f"SELECT access_token FROM {TABLE} WHERE user_id = %s LIMIT 1",
                    (user_id,),
                )
            else:
                cur.execute(
                    f"SELECT access_token FROM {TABLE} ORDER BY updated_at DESC LIMIT 1"
                )
            row = cur.fetchone()
    return row[0] if row else None


@retry_on_disconnect
def get_github_user(user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Return the GitHub user info for a specific app user.

    When ``user_id`` is provided, returns only the connection belonging
    to that app user. Falls back to the latest entry if unspecified.

    Args:
        user_id: App user email to look up.

    Returns:
        Dict with ``github_user`` and ``scope``, or ``None``.

    Raises:
        psycopg2.Error: On database failure.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            if user_id:
                cur.execute(
                    f"SELECT github_user, scope, updated_at FROM {TABLE} "
                    f"WHERE user_id = %s LIMIT 1",
                    (user_id,),
                )
            else:
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
def delete_token(github_user: Optional[str] = None, user_id: Optional[str] = None) -> bool:
    """Remove a stored GitHub token (disconnect).

    Can delete by GitHub username, by app user_id, or both.

    Args:
        github_user: GitHub username to remove.
        user_id:     App user email to remove token for.

    Returns:
        True if a row was deleted.

    Raises:
        psycopg2.Error: On database failure.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            if user_id:
                cur.execute(
                    f"DELETE FROM {TABLE} WHERE user_id = %s", (user_id,)
                )
            elif github_user:
                cur.execute(
                    f"DELETE FROM {TABLE} WHERE github_user = %s", (github_user,)
                )
            else:
                return False
            deleted = cur.rowcount > 0
        conn.commit()
    return deleted
