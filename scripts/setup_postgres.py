#!/usr/bin/env python3
"""
Setup PostgreSQL database for RAG system.
Can be run standalone or as part of the pipeline.
"""

import os
import sys
import logging
from pathlib import Path

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_database_if_not_exists(
    host: str,
    port: int,
    user: str,
    password: str,
    database: str
) -> None:
    """
    Create database if it doesn't exist.
    
    Args:
        host: PostgreSQL host
        port: PostgreSQL port
        user: Database user
        password: Database password
        database: Database name to create
        
    Raises:
        RuntimeError: If database creation fails
    """
    conn = None
    try:
        # Connect to default 'postgres' database
        conn = psycopg2.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database="postgres"
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        
        with conn.cursor() as cur:
            # Check if database exists
            cur.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (database,)
            )
            exists = cur.fetchone()
            
            if not exists:
                logger.info(f"Creating database: {database}")
                cur.execute(f"CREATE DATABASE {database}")
                logger.info(f"✓ Database {database} created")
            else:
                logger.info(f"✓ Database {database} already exists")
    
    except Exception as e:
        raise RuntimeError(f"Failed to create database: {e}") from e
    finally:
        if conn:
            conn.close()


def initialize_schema(
    host: str,
    port: int,
    user: str,
    password: str,
    database: str
) -> None:
    """
    Initialize database schema with pgvector extension.
    
    Args:
        host: PostgreSQL host
        port: PostgreSQL port
        user: Database user
        password: Database password
        database: Database name
        
    Raises:
        FileNotFoundError: If init_db.sql not found
        RuntimeError: If schema initialization fails
    """
    conn = None
    try:
        conn = psycopg2.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database
        )
        
        # Read init script
        init_script = Path(__file__).parent / "init_db.sql"
        if not init_script.exists():
            raise FileNotFoundError(f"Init script not found: {init_script}")
        
        with open(init_script) as f:
            sql = f.read()
        
        with conn.cursor() as cur:
            logger.info("Initializing database schema...")
            cur.execute(sql)
            conn.commit()
            logger.info("✓ Schema initialized successfully")
    
    except Exception as e:
        if conn:
            conn.rollback()
        raise RuntimeError(f"Schema initialization failed: {e}") from e
    finally:
        if conn:
            conn.close()


def main():
    """
    Main setup function with comprehensive error handling.
    
    Exits with code 1 on failure.
    """
    # Get connection params from environment
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = int(os.getenv("POSTGRES_PORT", "5432"))
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "")
    database = os.getenv("POSTGRES_DB", "rag_db")

    if not password:
        logger.error("POSTGRES_PASSWORD environment variable is not set.")
        logger.error("Add it to your .env file: POSTGRES_PASSWORD=yourpassword")
        sys.exit(1)
    
    logger.info("=" * 60)
    logger.info("PostgreSQL Setup for RAG System")
    logger.info("=" * 60)
    logger.info(f"Host: {host}:{port}")
    logger.info(f"Database: {database}")
    logger.info(f"User: {user}")
    logger.info("=" * 60)
    
    try:
        # Create database
        logger.info("Step 1: Creating database...")
        create_database_if_not_exists(host, port, user, password, database)
        
        # Initialize schema
        logger.info("Step 2: Initializing schema...")
        initialize_schema(host, port, user, password, database)
        
        logger.info("=" * 60)
        logger.info("✓ PostgreSQL setup complete!")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error("=" * 60)
        logger.error(f"❌ Setup failed: {e}")
        logger.error("=" * 60)
        logger.error("Troubleshooting tips:")
        logger.error("1. Ensure PostgreSQL is running")
        logger.error("2. Check connection parameters in .env")
        logger.error("3. Verify user has CREATE DATABASE privileges")
        logger.error("4. Check if pgvector extension is available")
        sys.exit(1)


if __name__ == "__main__":
    main()
