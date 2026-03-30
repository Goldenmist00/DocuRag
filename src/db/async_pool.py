"""
async_pool.py
=============
Async PostgreSQL connection pool powered by ``asyncpg``.

Used by FastAPI endpoint handlers so they can ``await`` DB queries
directly on the event loop instead of blocking a thread-pool worker.

Background agents (ingest, consolidate, coding-agent) continue to
use the synchronous ``psycopg2`` pool in ``connection.py``.

Lifecycle
---------
Call ``init_async_pool()`` during FastAPI startup and
``close_async_pool()`` during shutdown.
"""

from __future__ import annotations

import logging
import os
import ssl
from typing import Any, Dict, List, Optional

import asyncpg

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None


async def init_async_pool() -> asyncpg.Pool:
    """Create the process-wide asyncpg pool (call once at startup).

    Reads the same ``POSTGRES_*`` env vars as ``connection.py``.

    Returns:
        The initialised pool.

    Raises:
        RuntimeError: If ``POSTGRES_PASSWORD`` is missing.
    """
    global _pool
    if _pool is not None:
        return _pool

    password = os.environ.get("POSTGRES_PASSWORD", "")
    if not password:
        raise RuntimeError("POSTGRES_PASSWORD is not set.")

    sslmode = os.environ.get("POSTGRES_SSLMODE", "require")
    ssl_ctx: Any = None
    if sslmode in ("require", "verify-ca", "verify-full"):
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

    max_conn = int(os.environ.get("DB_POOL_MAX_CONN", "20"))
    min_conn = int(os.environ.get("DB_POOL_MIN_CONN", "2"))

    async def _init_conn(conn: asyncpg.Connection) -> None:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        from pgvector.asyncpg import register_vector
        await register_vector(conn)

    _pool = await asyncpg.create_pool(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", 5432)),
        database=os.environ.get("POSTGRES_DB", "rag_db"),
        user=os.environ.get("POSTGRES_USER", "postgres"),
        password=password,
        ssl=ssl_ctx,
        min_size=min_conn,
        max_size=max_conn,
        command_timeout=30,
        init=_init_conn,
    )
    logger.info("Async DB pool created (min=%d, max=%d)", min_conn, max_conn)
    return _pool


def get_async_pool() -> asyncpg.Pool:
    """Return the live pool (must be initialised first).

    Returns:
        The asyncpg pool.

    Raises:
        RuntimeError: If the pool has not been initialised.
    """
    if _pool is None:
        raise RuntimeError("Async pool not initialised — call init_async_pool() first")
    return _pool


async def close_async_pool() -> None:
    """Gracefully shut down the async pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Async DB pool closed.")


async def fetch_rows(
    query: str, *args: Any,
) -> List[Dict[str, Any]]:
    """Run a SELECT and return rows as list of dicts.

    Args:
        query: SQL query string with ``$1``, ``$2`` placeholders.
        args:  Positional bind parameters.

    Returns:
        List of row dicts.
    """
    pool = get_async_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *args)
    return [dict(r) for r in rows]


async def fetch_row(
    query: str, *args: Any,
) -> Optional[Dict[str, Any]]:
    """Run a SELECT and return a single row dict or ``None``.

    Args:
        query: SQL query string.
        args:  Positional bind parameters.

    Returns:
        Row dict or ``None``.
    """
    pool = get_async_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, *args)
    return dict(row) if row else None


async def execute(query: str, *args: Any) -> str:
    """Run a non-SELECT statement (INSERT / UPDATE / DELETE).

    Args:
        query: SQL statement.
        args:  Positional bind parameters.

    Returns:
        Command status string (e.g. ``'UPDATE 1'``).
    """
    pool = get_async_pool()
    async with pool.acquire() as conn:
        return await conn.execute(query, *args)
