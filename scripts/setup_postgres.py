#!/usr/bin/env python3
"""
Setup PostgreSQL / Supabase database for RAG system.
Skips database creation (Supabase manages that) and goes straight
to schema initialisation.
"""

import os
import sys
import logging
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env before anything else
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def get_conn_params() -> dict:
    password = os.getenv("POSTGRES_PASSWORD", "")
    if not password:
        logger.error("POSTGRES_PASSWORD is not set. Add it to your .env file.")
        sys.exit(1)

    return {
        "host":    os.getenv("POSTGRES_HOST", "localhost"),
        "port":    int(os.getenv("POSTGRES_PORT", "5432")),
        "dbname":  os.getenv("POSTGRES_DB", "postgres"),
        "user":    os.getenv("POSTGRES_USER", "postgres"),
        "password": password,
        "sslmode": os.getenv("POSTGRES_SSLMODE", "require"),
    }


def initialize_schema(params: dict) -> None:
    """Run init_db.sql against the target database."""
    init_script = Path(__file__).parent / "init_db.sql"
    if not init_script.exists():
        raise FileNotFoundError(f"Init script not found: {init_script}")

    sql = init_script.read_text()

    conn = psycopg2.connect(**params)
    try:
        with conn.cursor() as cur:
            logger.info("Running schema initialisation...")
            cur.execute(sql)
        conn.commit()
        logger.info("✓ Schema initialised successfully")
    except Exception as exc:
        conn.rollback()
        raise RuntimeError(f"Schema initialisation failed: {exc}") from exc
    finally:
        conn.close()


def verify_setup(params: dict) -> None:
    """Quick sanity check — confirm table and pgvector exist."""
    conn = psycopg2.connect(**params)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
            )
            row = cur.fetchone()
            if not row:
                raise RuntimeError("pgvector extension not found after setup.")
            logger.info(f"✓ pgvector {row[0]} is active")

            cur.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_name = 'document_chunks'"
            )
            if cur.fetchone()[0] == 0:
                raise RuntimeError("document_chunks table was not created.")
            logger.info("✓ document_chunks table exists")
    finally:
        conn.close()


def main():
    logger.info("=" * 50)
    logger.info("PostgreSQL / Supabase Setup")
    logger.info("=" * 50)

    params = get_conn_params()
    logger.info(f"Host:     {params['host']}:{params['port']}")
    logger.info(f"Database: {params['dbname']}")
    logger.info(f"User:     {params['user']}")
    logger.info(f"SSL:      {params['sslmode']}")
    logger.info("=" * 50)

    try:
        initialize_schema(params)
        verify_setup(params)
        logger.info("=" * 50)
        logger.info("✓ Setup complete! Ready to ingest data.")
        logger.info("=" * 50)
    except Exception as exc:
        logger.error(f"❌ Setup failed: {exc}")
        logger.error("Troubleshooting:")
        logger.error("  1. Check POSTGRES_HOST in .env matches your Supabase project URL")
        logger.error("  2. Verify POSTGRES_PASSWORD is correct")
        logger.error("  3. Ensure your IP is allowed in Supabase → Settings → Database → Connection Pooling")
        sys.exit(1)


if __name__ == "__main__":
    main()
