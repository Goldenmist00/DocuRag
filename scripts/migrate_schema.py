"""
migrate_schema.py
=================
Run against the live Neon-hosted PostgreSQL to add notebooks, sources tables
and the notebook_id / source_id columns on document_chunks.

Idempotent: safe to run multiple times.

Usage:
    python scripts/migrate_schema.py
"""

import logging
import os
import sys

import psycopg2
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

MIGRATIONS = [
    # 1. Notebooks table
    """
    CREATE TABLE IF NOT EXISTS notebooks (
        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        title       TEXT NOT NULL DEFAULT 'Untitled notebook',
        created_at  TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at  TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    """,
    # 2. Sources table
    """
    CREATE TABLE IF NOT EXISTS sources (
        id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        notebook_id   UUID NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
        name          TEXT NOT NULL,
        source_type   TEXT NOT NULL DEFAULT 'file',
        file_path     TEXT,
        raw_content   TEXT,
        status        TEXT NOT NULL DEFAULT 'pending',
        error_message TEXT,
        chunk_count   INTEGER DEFAULT 0,
        created_at    TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at    TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_sources_notebook ON sources(notebook_id);",
    # 3. Add notebook_id / source_id columns to document_chunks (idempotent)
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'document_chunks' AND column_name = 'notebook_id'
        ) THEN
            ALTER TABLE document_chunks
                ADD COLUMN notebook_id UUID REFERENCES notebooks(id) ON DELETE CASCADE;
        END IF;
    END $$;
    """,
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'document_chunks' AND column_name = 'source_id'
        ) THEN
            ALTER TABLE document_chunks
                ADD COLUMN source_id UUID REFERENCES sources(id) ON DELETE CASCADE;
        END IF;
    END $$;
    """,
    "CREATE INDEX IF NOT EXISTS idx_chunks_notebook ON document_chunks(notebook_id);",
    "CREATE INDEX IF NOT EXISTS idx_chunks_source   ON document_chunks(source_id);",
    # 4. updated_at triggers (OR REPLACE makes these idempotent)
    """
    CREATE OR REPLACE FUNCTION update_updated_at_column()
    RETURNS TRIGGER AS $$
    BEGIN
        NEW.updated_at = CURRENT_TIMESTAMP;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """,
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_trigger WHERE tgname = 'update_notebooks_updated_at'
        ) THEN
            CREATE TRIGGER update_notebooks_updated_at
                BEFORE UPDATE ON notebooks
                FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
        END IF;
    END $$;
    """,
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_trigger WHERE tgname = 'update_sources_updated_at'
        ) THEN
            CREATE TRIGGER update_sources_updated_at
                BEFORE UPDATE ON sources
                FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
        END IF;
    END $$;
    """,
]


def run_migrations() -> None:
    """Connect to the Neon DB and apply all migrations."""
    password = os.environ.get("POSTGRES_PASSWORD", "")
    if not password:
        logger.error("POSTGRES_PASSWORD not set. Aborting.")
        sys.exit(1)

    conn_params = {
        "host":     os.environ.get("POSTGRES_HOST", "localhost"),
        "port":     int(os.environ.get("POSTGRES_PORT", 5432)),
        "database": os.environ.get("POSTGRES_DB", "rag_db"),
        "user":     os.environ.get("POSTGRES_USER", "postgres"),
        "password": password,
        "sslmode":  os.environ.get("POSTGRES_SSLMODE", "require"),
    }

    logger.info("Connecting to %s:%s/%s …", conn_params["host"], conn_params["port"], conn_params["database"])
    conn = psycopg2.connect(**conn_params)
    conn.autocommit = True

    try:
        with conn.cursor() as cur:
            for i, sql in enumerate(MIGRATIONS, 1):
                logger.info("Running migration %d/%d …", i, len(MIGRATIONS))
                cur.execute(sql)
            logger.info("All %d migrations applied successfully.", len(MIGRATIONS))
    finally:
        conn.close()


if __name__ == "__main__":
    run_migrations()
