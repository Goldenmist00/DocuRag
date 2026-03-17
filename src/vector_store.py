"""
vector_store.py
===============
Phase 2 — PostgreSQL + pgvector Vector Store

Responsibilities:
  1. Connect to PostgreSQL with pgvector extension
  2. Store document chunks with their embeddings
  3. Perform cosine similarity search
  4. Manage IVFFlat / HNSW indexes for fast retrieval
  5. Connection pooling, retry logic, and performance metrics

Usage:
    from src.vector_store import PgVectorStore

    vs = PgVectorStore(embedding_dim=768)
    vs.insert_chunks(chunks, embeddings)
    vs.create_index()
    results = vs.search(query_embedding, top_k=5)
    vs.close()
"""

import logging
import os
import time
from contextlib import contextmanager
from typing import Dict, Generator, List, Optional

import numpy as np
import psycopg2
from psycopg2 import pool
from psycopg2.extras import execute_values
from pgvector.psycopg2 import register_vector

logger = logging.getLogger(__name__)


class PgVectorStore:
    """
    PostgreSQL + pgvector vector store for RAG document retrieval.

    Features:
        - Thread-safe connection pooling
        - Exponential-backoff retry on transient failures
        - IVFFlat and HNSW index support
        - Upsert semantics (safe to re-run ingestion)
        - Performance timing on insert and search
    """

    # ------------------------------------------------------------------ #
    #  Construction                                                        #
    # ------------------------------------------------------------------ #

    def __init__(
        self,
        embedding_dim: int,
        host: str = "localhost",
        port: int = 5432,
        database: str = "rag_db",
        user: str = "postgres",
        password: Optional[str] = None,
        table_name: str = "document_chunks",
        min_connections: int = 1,
        max_connections: int = 10,
    ) -> None:
        """
        Initialise the vector store and verify the database connection.

        Args:
            embedding_dim:    Dimensionality of the embedding vectors.
                              Must match the model used (384 / 768 / 1024).
            host:             PostgreSQL host.
            port:             PostgreSQL port.
            database:         Database name.
            user:             Database user.
            password:         Database password.
            table_name:       Table that holds the document chunks.
            min_connections:  Minimum pool size.
            max_connections:  Maximum pool size.

        Raises:
            RuntimeError: If the connection pool cannot be created or the
                          pgvector extension is not installed.
        """
        self.embedding_dim = embedding_dim
        self.table_name = table_name

        # Prefer environment variables over constructor arguments
        resolved_password = os.environ.get("POSTGRES_PASSWORD", password)
        if not resolved_password:
            raise ValueError(
                "Database password is required. "
                "Set POSTGRES_PASSWORD in your .env file."
            )

        self._conn_params: Dict = {
            "host":     os.environ.get("POSTGRES_HOST",     host),
            "port":     int(os.environ.get("POSTGRES_PORT", port)),
            "database": os.environ.get("POSTGRES_DB",       database),
            "user":     os.environ.get("POSTGRES_USER",     user),
            "password": resolved_password,
        }

        try:
            self._pool = pool.ThreadedConnectionPool(
                min_connections,
                max_connections,
                **self._conn_params,
            )
            logger.info(
                "Connection pool created "
                f"(min={min_connections}, max={max_connections})"
            )
        except Exception as exc:
            raise RuntimeError(
                f"Failed to create connection pool: {exc}"
            ) from exc

        self._verify_connection()

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _verify_connection(self) -> None:
        """
        Confirm the database is reachable and pgvector is installed.

        Raises:
            RuntimeError: On connection failure or missing extension.
        """
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.execute(
                        "SELECT extversion FROM pg_extension "
                        "WHERE extname = 'vector'"
                    )
                    row = cur.fetchone()
                    if row is None:
                        raise RuntimeError(
                            "pgvector extension is not installed. "
                            "Run: CREATE EXTENSION vector;"
                        )
                    logger.info(
                        f"Connected to PostgreSQL — pgvector {row[0]}"
                    )
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f"Database connection failed: {exc}\n"
                "Troubleshooting:\n"
                "  1. Is PostgreSQL running?\n"
                "  2. Are the credentials in config.yaml / .env correct?\n"
                "  3. Has the schema been initialised? "
                "Run: python scripts/setup_postgres.py"
            ) from exc

    @contextmanager
    def _connection(self) -> Generator:
        """
        Yield a pooled connection with automatic commit / rollback and
        exponential-backoff retry on transient errors.

        Yields:
            psycopg2 connection with pgvector types registered.

        Raises:
            Exception: After all retry attempts are exhausted.
        """
        max_retries = 3
        delay = 1.0

        for attempt in range(max_retries):
            conn = None
            try:
                conn = self._pool.getconn()
                register_vector(conn)
                yield conn
                conn.commit()
                return
            except Exception as exc:
                if conn:
                    conn.rollback()
                if attempt < max_retries - 1:
                    logger.warning(
                        f"DB attempt {attempt + 1}/{max_retries} failed "
                        f"({exc}). Retrying in {delay:.1f}s…"
                    )
                    time.sleep(delay)
                    delay *= 2
                else:
                    logger.error("All DB retry attempts exhausted.")
                    raise
            finally:
                if conn:
                    self._pool.putconn(conn)

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def insert_chunks(
        self,
        chunks: List[Dict],
        embeddings: np.ndarray,
        batch_size: int = 100,
    ) -> int:
        """
        Upsert document chunks together with their embedding vectors.

        Chunks can be either ``Chunk`` dataclass instances or plain dicts
        (as loaded from a JSONL file).  The following keys / attributes
        are expected::

            chunk_id, text, section_id, chapter_id, section_title,
            page_num, chunk_index, char_count, word_count

        Args:
            chunks:     List of chunk objects or dicts.
            embeddings: Float32 array of shape ``(n, embedding_dim)``.
            batch_size: Rows per INSERT statement.

        Returns:
            Number of rows upserted.

        Raises:
            ValueError:   If ``len(chunks) != len(embeddings)``.
            RuntimeError: On database error.
        """
        if len(chunks) != len(embeddings):
            raise ValueError(
                f"Length mismatch: {len(chunks)} chunks vs "
                f"{len(embeddings)} embeddings."
            )

        logger.info(f"Upserting {len(chunks)} chunks → {self.table_name}")
        t0 = time.time()

        sql = f"""
            INSERT INTO {self.table_name} (
                chunk_id, text, embedding,
                section_id, chapter_id, section_title,
                page_num, chunk_index, char_count, word_count
            ) VALUES %s
            ON CONFLICT (chunk_id) DO UPDATE SET
                text       = EXCLUDED.text,
                embedding  = EXCLUDED.embedding,
                updated_at = CURRENT_TIMESTAMP
        """

        def _get(obj, attr: str, default=None):
            """Unified attribute / key access for dataclass or dict."""
            if isinstance(obj, dict):
                return obj.get(attr, default)
            return getattr(obj, attr, default)

        inserted = 0
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    for i in range(0, len(chunks), batch_size):
                        batch_c = chunks[i : i + batch_size]
                        batch_e = embeddings[i : i + batch_size]

                        rows = [
                            (
                                _get(c, "chunk_id"),
                                _get(c, "text"),
                                batch_e[j].tolist(),
                                _get(c, "section_id"),
                                _get(c, "chapter_id"),
                                _get(c, "section_title"),
                                _get(c, "page_num"),
                                _get(c, "chunk_index", 0),
                                _get(c, "char_count", 0),
                                _get(c, "word_count", 0),
                            )
                            for j, c in enumerate(batch_c)
                        ]

                        execute_values(cur, sql, rows)
                        inserted += len(batch_c)
                        logger.debug(f"  {inserted}/{len(chunks)} rows inserted")

            elapsed = time.time() - t0
            logger.info(
                f"✓ Upserted {inserted} chunks in {elapsed:.2f}s "
                f"({inserted / elapsed:.0f} rows/s)"
            )
            return inserted

        except Exception as exc:
            raise RuntimeError(
                f"insert_chunks failed after {inserted} rows: {exc}"
            ) from exc

    def create_index(
        self,
        index_type: str = "ivfflat",
        lists: int = 100,
        m: int = 16,
        ef_construction: int = 64,
    ) -> None:
        """
        Build a vector similarity index on the embedding column.

        For small datasets (<10 k rows) an index may not improve speed;
        for large datasets it is essential.

        Args:
            index_type:      ``"ivfflat"`` (default) or ``"hnsw"``.
            lists:           IVFFlat: number of inverted lists.
                             Rule of thumb: ``rows / 1000`` (min 10).
            m:               HNSW: max connections per layer.
            ef_construction: HNSW: size of the dynamic candidate list
                             during index construction.

        Raises:
            ValueError:   For unknown ``index_type``.
            RuntimeError: On database error.
        """
        logger.info(f"Building {index_type.upper()} index…")
        t0 = time.time()

        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    # Remove any stale index first
                    cur.execute(
                        "DROP INDEX IF EXISTS idx_chunks_embedding_ivfflat"
                    )
                    cur.execute(
                        "DROP INDEX IF EXISTS idx_chunks_embedding_hnsw"
                    )

                    if index_type == "ivfflat":
                        cur.execute(f"""
                            CREATE INDEX idx_chunks_embedding_ivfflat
                            ON {self.table_name}
                            USING ivfflat (embedding vector_cosine_ops)
                            WITH (lists = {lists})
                        """)
                    elif index_type == "hnsw":
                        cur.execute(f"""
                            CREATE INDEX idx_chunks_embedding_hnsw
                            ON {self.table_name}
                            USING hnsw (embedding vector_cosine_ops)
                            WITH (m = {m}, ef_construction = {ef_construction})
                        """)
                    else:
                        raise ValueError(
                            f"Unknown index_type '{index_type}'. "
                            "Choose 'ivfflat' or 'hnsw'."
                        )

            elapsed = time.time() - t0
            logger.info(
                f"✓ {index_type.upper()} index created in {elapsed:.2f}s"
            )

        except ValueError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f"create_index failed: {exc}"
            ) from exc

    def search(
        self,
        query_embedding: np.ndarray,
        top_k: int = 10,
        probes: int = 10,
    ) -> List[Dict]:
        """
        Retrieve the ``top_k`` most similar chunks via cosine similarity.

        Args:
            query_embedding: 1-D float array of shape ``(embedding_dim,)``.
            top_k:           Number of results to return.
            probes:          IVFFlat search probes (higher = more accurate,
                             slower).  Ignored when using HNSW.

        Returns:
            List of result dicts, each containing::

                chunk_id, text, section_id, chapter_id, section_title,
                page_num, chunk_index, char_count, word_count, score

            Sorted by ``score`` descending (most similar first).

        Raises:
            RuntimeError: On database error.
        """
        t0 = time.time()
        vec = query_embedding.tolist()

        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(f"SET ivfflat.probes = {probes}")

                    cur.execute(
                        f"""
                        SELECT
                            chunk_id,
                            text,
                            section_id,
                            chapter_id,
                            section_title,
                            page_num,
                            chunk_index,
                            char_count,
                            word_count,
                            1 - (embedding <=> %s::vector) AS score
                        FROM {self.table_name}
                        ORDER BY embedding <=> %s::vector
                        LIMIT %s
                        """,
                        (vec, vec, top_k),
                    )

                    results = [
                        {
                            "chunk_id":      row[0],
                            "text":          row[1],
                            "section_id":    row[2],
                            "chapter_id":    row[3],
                            "section_title": row[4],
                            "page_num":      row[5],
                            "chunk_index":   row[6],
                            "char_count":    row[7],
                            "word_count":    row[8],
                            "score":         float(row[9]),
                        }
                        for row in cur.fetchall()
                    ]

            elapsed = (time.time() - t0) * 1000
            logger.info(
                f"✓ Search returned {len(results)} results in {elapsed:.1f}ms"
            )
            return results

        except Exception as exc:
            raise RuntimeError(f"search failed: {exc}") from exc

    def get_stats(self) -> Dict:
        """
        Return summary statistics about the stored chunks.

        Returns:
            Dict with keys: ``total_chunks``, ``unique_sections``,
            ``unique_chapters``, ``unique_pages``, ``embedding_dim``,
            ``has_index``.
        """
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT COUNT(*) FROM {self.table_name}"
                    )
                    total = cur.fetchone()[0]

                    cur.execute(
                        f"SELECT COUNT(DISTINCT section_id) "
                        f"FROM {self.table_name}"
                    )
                    sections = cur.fetchone()[0]

                    cur.execute(
                        f"SELECT COUNT(DISTINCT chapter_id) "
                        f"FROM {self.table_name}"
                    )
                    chapters = cur.fetchone()[0]

                    cur.execute(
                        f"SELECT COUNT(DISTINCT page_num) "
                        f"FROM {self.table_name}"
                    )
                    pages = cur.fetchone()[0]

                    cur.execute(
                        """
                        SELECT COUNT(*) FROM pg_indexes
                        WHERE tablename = %s
                          AND indexname LIKE 'idx_chunks_embedding%%'
                        """,
                        (self.table_name,),
                    )
                    has_index = cur.fetchone()[0] > 0

            return {
                "total_chunks":    total,
                "unique_sections": sections,
                "unique_chapters": chapters,
                "unique_pages":    pages,
                "embedding_dim":   self.embedding_dim,
                "has_index":       has_index,
            }

        except Exception as exc:
            logger.error(f"get_stats failed: {exc}")
            return {
                "total_chunks":    0,
                "unique_sections": 0,
                "unique_chapters": 0,
                "unique_pages":    0,
                "embedding_dim":   self.embedding_dim,
                "has_index":       False,
                "error":           str(exc),
            }

    def clear(self) -> None:
        """
        Delete all rows from the chunks table.

        Warning:
            This is irreversible.  Re-run ingestion to repopulate.
        """
        logger.warning(f"Clearing all rows from '{self.table_name}'…")
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"TRUNCATE TABLE {self.table_name} RESTART IDENTITY"
                    )
            logger.info("✓ Table cleared.")
        except Exception as exc:
            raise RuntimeError(f"clear failed: {exc}") from exc

    def close(self) -> None:
        """Return all connections to the pool and shut it down."""
        if hasattr(self, "_pool"):
            self._pool.closeall()
            logger.info("Connection pool closed.")
