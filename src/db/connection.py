"""
connection.py
=============
Shared PostgreSQL connection pool used by all DB service modules.

Provides a single ``get_pool()`` accessor that lazily creates a
``ThreadedConnectionPool`` on first call and reuses it afterward.
"""

import functools
import logging
import os
import time
from contextlib import contextmanager
from typing import Generator, Optional

import psycopg2
from psycopg2 import pool
from pgvector.psycopg2 import register_vector
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

_pool: Optional[pool.ThreadedConnectionPool] = None


def get_pool(min_conn: int = 1, max_conn: int = 5) -> pool.ThreadedConnectionPool:
    """
    Return the shared connection pool, creating it on first call.

    Reads credentials from environment variables:
        POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB,
        POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_SSLMODE

    Returns:
        ThreadedConnectionPool instance.

    Raises:
        RuntimeError: If POSTGRES_PASSWORD is not set or connection fails.
    """
    global _pool
    if _pool is not None:
        return _pool

    password = os.environ.get("POSTGRES_PASSWORD", "")
    if not password:
        raise RuntimeError("POSTGRES_PASSWORD is not set.")

    params = {
        "host":     os.environ.get("POSTGRES_HOST", "localhost"),
        "port":     int(os.environ.get("POSTGRES_PORT", 5432)),
        "database": os.environ.get("POSTGRES_DB", "rag_db"),
        "user":     os.environ.get("POSTGRES_USER", "postgres"),
        "password": password,
        "sslmode":  os.environ.get("POSTGRES_SSLMODE", "require"),
        "connect_timeout":     30,
        "keepalives":          1,
        "keepalives_idle":     30,
        "keepalives_interval": 10,
        "keepalives_count":    3,
    }

    _pool = pool.ThreadedConnectionPool(min_conn, max_conn, **params)
    logger.info("Shared DB pool created (min=%d, max=%d)", min_conn, max_conn)
    return _pool


@contextmanager
def get_connection() -> Generator:
    """
    Yield a pooled connection with pgvector registered.

    Automatically commits on success, rolls back on error,
    and returns the connection to the pool in all cases.

    Handles Neon's aggressive idle-connection drops by detecting
    stale connections during ``register_vector`` (the first real
    SQL query) and transparently replacing them.
    """
    p = get_pool()
    conn = None
    try:
        conn = p.getconn()
        if conn.closed:
            p.putconn(conn, close=True)
            conn = p.getconn()

        try:
            register_vector(conn)
        except psycopg2.OperationalError:
            logger.warning("Stale connection detected, replacing")
            try:
                p.putconn(conn, close=True)
            except Exception:
                pass
            conn = p.getconn()
            register_vector(conn)

        yield conn
        conn.commit()
    except psycopg2.OperationalError:
        if conn:
            try:
                p.putconn(conn, close=True)
            except Exception:
                pass
            conn = None
        raise
    except Exception:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        raise
    finally:
        if conn:
            p.putconn(conn)


MAX_DB_RETRIES = 2
RETRY_DELAY_S = 1.0


def retry_on_disconnect(fn):
    """Retry a DB-service function when the server drops the connection mid-query.

    Wraps *fn* so that ``psycopg2.OperationalError`` (e.g. Neon idle
    disconnect) triggers up to ``MAX_DB_RETRIES`` transparent retries with
    a brief sleep between attempts.  The function **must** obtain its own
    connection via ``get_connection()`` on each call — this is the normal
    pattern in our db-service modules.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        last_err: Optional[Exception] = None
        for attempt in range(MAX_DB_RETRIES + 1):
            try:
                return fn(*args, **kwargs)
            except psycopg2.OperationalError as exc:
                last_err = exc
                if attempt < MAX_DB_RETRIES:
                    logger.warning(
                        "DB connection lost in %s (attempt %d/%d), retrying in %.1fs: %s",
                        fn.__name__,
                        attempt + 1,
                        MAX_DB_RETRIES + 1,
                        RETRY_DELAY_S,
                        exc,
                    )
                    time.sleep(RETRY_DELAY_S)
                    continue
        logger.error("All %d retries exhausted for %s", MAX_DB_RETRIES + 1, fn.__name__)
        raise last_err  # type: ignore[misc]

    return wrapper


def close_pool() -> None:
    """Shut down the shared pool (call at app shutdown)."""
    global _pool
    if _pool:
        _pool.closeall()
        _pool = None
        logger.info("Shared DB pool closed.")
