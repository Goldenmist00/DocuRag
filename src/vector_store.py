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

    vs = PgVectorStore(embedding_dim=4096)
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
            embedding_dim:    Dimensionality of the embedding vectors (4096 for nv-embed-v1).
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
            "sslmode":  os.environ.get("POSTGRES_SSLMODE",  "require"),
            "connect_timeout":     10,
            "keepalives":          1,
            "keepalives_idle":     30,
            "keepalives_interval": 10,
            "keepalives_count":    3,
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
        Confirm the database is reachable, pgvector is installed,
        and the chunks table exists (creates it if not).
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
            # Auto-create table if missing
            self._ensure_table()
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
        Yield a pooled connection with automatic commit / rollback.
        Replaces stale connections before yielding.
        Retry logic is handled at the call site via _with_retry().
        """
        conn = None
        try:
            conn = self._pool.getconn()
            if conn.closed:
                self._pool.putconn(conn, close=True)
                conn = self._pool.getconn()
            try:
                conn.isolation_level
            except psycopg2.OperationalError:
                logger.warning("Stale vector_store connection, replacing")
                self._pool.putconn(conn, close=True)
                conn = self._pool.getconn()
            register_vector(conn)
            yield conn
            conn.commit()
        except Exception:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            raise
        finally:
            if conn:
                self._pool.putconn(conn)

    def _with_retry(self, fn, *args, max_retries: int = 3, **kwargs):
        """Call fn(*args, **kwargs) with exponential-backoff retry."""
        delay = 1.0
        last_exc: Optional[Exception] = None
        for attempt in range(max_retries):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                last_exc = exc
                if attempt < max_retries - 1:
                    logger.warning(
                        "DB attempt %d/%d failed (%s). Retrying in %.1fs…",
                        attempt + 1, max_retries, exc, delay,
                    )
                    time.sleep(delay)
                    delay *= 2
        raise last_exc

    def _ensure_table(self) -> None:
        """
        Create the chunks table and pgvector extension if they don't exist.
        If the table exists but the embedding column has a different type
        (e.g. halfvec(4096) from a previous model), drop and recreate.
        """
        col_type = f"halfvec({self.embedding_dim})" if self.embedding_dim > 2000 else f"vector({self.embedding_dim})"
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                cur.execute("""
                    SELECT data_type, udt_name
                    FROM information_schema.columns
                    WHERE table_name = %s AND column_name = 'embedding'
                """, (self.table_name,))
                row = cur.fetchone()
                needs_recreate = False
                if row is not None:
                    cur.execute(f"""
                        SELECT pg_catalog.format_type(atttypid, atttypmod)
                        FROM pg_attribute
                        WHERE attrelid = %s::regclass AND attname = 'embedding'
                    """, (self.table_name,))
                    current_type = (cur.fetchone() or [None])[0]
                    if current_type and current_type != col_type:
                        logger.warning(
                            "Embedding column type mismatch: %s → %s.",
                            current_type, col_type,
                        )
                        needs_recreate = True

                    cur.execute("""
                        SELECT column_name FROM information_schema.columns
                        WHERE table_name = %s AND column_name IN ('notebook_id', 'source_id')
                    """, (self.table_name,))
                    existing_cols = {r[0] for r in cur.fetchall()}
                    if not {"notebook_id", "source_id"}.issubset(existing_cols):
                        logger.warning("Table missing notebook_id/source_id columns.")
                        needs_recreate = True

                if needs_recreate:
                    logger.warning("Dropping table %s to recreate.", self.table_name)
                    cur.execute(f"DROP TABLE IF EXISTS {self.table_name} CASCADE")

                cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.table_name} (
                        id            BIGSERIAL PRIMARY KEY,
                        chunk_id      TEXT        NOT NULL UNIQUE,
                        text          TEXT        NOT NULL,
                        embedding     {col_type},
                        notebook_id   TEXT,
                        source_id     TEXT,
                        section_id    TEXT,
                        chapter_id    TEXT,
                        section_title TEXT,
                        page_num      INTEGER,
                        chunk_index   INTEGER     DEFAULT 0,
                        char_count    INTEGER     DEFAULT 0,
                        word_count    INTEGER     DEFAULT 0,
                        created_at    TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                        updated_at    TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                    )
                """)

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
            def _do_insert():
                nonlocal inserted
                with self._connection() as conn:
                    with conn.cursor() as cur:
                        for i in range(0, len(chunks), batch_size):
                            batch_c = chunks[i : i + batch_size]
                            batch_e = embeddings[i : i + batch_size]

                            seen: dict = {}
                            for j, c in enumerate(batch_c):
                                seen[_get(c, "chunk_id")] = (c, batch_e[j])

                            rows = [
                                (
                                    _get(c, "chunk_id"),
                                    _get(c, "text"),
                                    emb.tolist(),
                                    _get(c, "section_id"),
                                    _get(c, "chapter_id"),
                                    _get(c, "section_title"),
                                    _get(c, "page_num"),
                                    _get(c, "chunk_index", 0),
                                    _get(c, "char_count", 0),
                                    _get(c, "word_count", 0),
                                )
                                for c, emb in seen.values()
                            ]

                            execute_values(cur, sql, rows)
                            inserted += len(batch_c)
                            logger.debug(f"  {inserted}/{len(chunks)} rows inserted")

            self._with_retry(_do_insert)

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
        index_type: str = "hnsw",
        lists: int = 100,
        m: int = 16,
        ef_construction: int = 64,
    ) -> None:
        """
        Build a vector similarity index on the embedding column.

        pgvector limits:
          - vector/halfvec IVFFlat: max 2000d
          - vector/halfvec HNSW:    max 4000d
        nv-embed-v1 is 4096d — above both limits.
        For >4000d we skip the ANN index; pgvector falls back to an exact
        sequential scan which is perfectly fast for ~3k rows.
        """
        # Hard limits in pgvector 0.8
        HNSW_MAX = 4000
        IVFFLAT_MAX = 2000

        if index_type == "hnsw" and self.embedding_dim > HNSW_MAX:
            logger.warning(
                "Skipping HNSW index: embedding_dim=%d exceeds pgvector limit of %d. "
                "Queries will use exact sequential scan (fine for <10k rows).",
                self.embedding_dim, HNSW_MAX,
            )
            return

        if index_type == "ivfflat" and self.embedding_dim > IVFFLAT_MAX:
            logger.warning(
                "Skipping IVFFlat index: embedding_dim=%d exceeds pgvector limit of %d. "
                "Queries will use exact sequential scan (fine for <10k rows).",
                self.embedding_dim, IVFFLAT_MAX,
            )
            return

        logger.info(f"Building {index_type.upper()} index (dim={self.embedding_dim})…")
        t0 = time.time()
        needs_halfvec = self.embedding_dim > 2000

        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("DROP INDEX IF EXISTS idx_chunks_embedding_ivfflat")
                    cur.execute("DROP INDEX IF EXISTS idx_chunks_embedding_hnsw")

                    if index_type == "hnsw":
                        ops = "halfvec_cosine_ops" if needs_halfvec else "vector_cosine_ops"
                        cur.execute(f"""
                            CREATE INDEX idx_chunks_embedding_hnsw
                            ON {self.table_name}
                            USING hnsw (embedding {ops})
                            WITH (m = {m}, ef_construction = {ef_construction})
                        """)
                    elif index_type == "ivfflat":
                        ops = "halfvec_cosine_ops" if needs_halfvec else "vector_cosine_ops"
                        cur.execute(f"""
                            CREATE INDEX idx_chunks_embedding_ivfflat
                            ON {self.table_name}
                            USING ivfflat (embedding {ops})
                            WITH (lists = {lists})
                        """)
                    else:
                        raise ValueError(
                            f"Unknown index_type '{index_type}'. "
                            "Choose 'hnsw' or 'ivfflat'."
                        )

            elapsed = time.time() - t0
            logger.info(f"✓ {index_type.upper()} index created in {elapsed:.2f}s")

        except ValueError:
            raise
        except Exception as exc:
            raise RuntimeError(f"create_index failed: {exc}") from exc

    def search(
        self,
        query_embedding: np.ndarray,
        top_k: int = 10,
        probes: int = 10,
        notebook_id: Optional[str] = None,
        source_id: Optional[str] = None,
    ) -> List[Dict]:
        """
        Retrieve the ``top_k`` most similar chunks via cosine similarity.

        Args:
            query_embedding: 1-D float array of shape ``(embedding_dim,)``.
            top_k:           Number of results to return.
            probes:          IVFFlat search probes (higher = more accurate,
                             slower).  Ignored when using HNSW.
            notebook_id:     If provided, restrict to this notebook's chunks.
            source_id:       If provided, restrict to this source's chunks.

        Returns:
            List of result dicts, each containing::

                chunk_id, text, section_id, chapter_id, section_title,
                page_num, chunk_index, char_count, word_count,
                source_id, score

            Sorted by ``score`` descending (most similar first).

        Raises:
            RuntimeError: On database error.
        """
        t0 = time.time()
        vec = query_embedding.tolist()
        needs_halfvec = self.embedding_dim > 2000

        conditions: list = []
        extra_params: list = []
        if notebook_id:
            conditions.append("notebook_id = %s")
            extra_params.append(notebook_id)
        if source_id:
            conditions.append("source_id = %s")
            extra_params.append(source_id)
        where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SET LOCAL statement_timeout = '45s'")
                    if needs_halfvec:
                        cur.execute(
                            f"""
                            SELECT
                                chunk_id, text, section_id, chapter_id,
                                section_title, page_num, chunk_index,
                                char_count, word_count, source_id,
                                1 - (embedding <=> %s::halfvec({self.embedding_dim})) AS score
                            FROM {self.table_name}
                            {where_clause}
                            ORDER BY embedding <=> %s::halfvec({self.embedding_dim})
                            LIMIT %s
                            """,
                            (vec, *extra_params, vec, top_k),
                        )
                    else:
                        cur.execute(f"SET ivfflat.probes = {probes}")
                        cur.execute(
                            f"""
                            SELECT
                                chunk_id, text, section_id, chapter_id,
                                section_title, page_num, chunk_index,
                                char_count, word_count, source_id,
                                1 - (embedding <=> %s::vector) AS score
                            FROM {self.table_name}
                            {where_clause}
                            ORDER BY embedding <=> %s::vector
                            LIMIT %s
                            """,
                            (vec, *extra_params, vec, top_k),
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
                            "source_id":     str(row[9]) if row[9] else None,
                            "score":         float(row[10]),
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

    def search_multi_source(
        self,
        query_embedding: np.ndarray,
        source_ids: List[str],
        per_source_k: int = 10,
        notebook_id: Optional[str] = None,
        probes: int = 10,
    ) -> Dict[str, List[Dict]]:
        """
        Retrieve top-k chunks per source in a single SQL round-trip.

        Uses ``ROW_NUMBER() OVER (PARTITION BY source_id ...)`` to fetch
        the best chunks for each source in one query, avoiding N separate
        queries when the notebook has N sources.

        Args:
            query_embedding: 1-D float array of shape ``(embedding_dim,)``.
            source_ids:      List of source UUIDs to search.
            per_source_k:    Max chunks to return per source.
            notebook_id:     If provided, restrict to this notebook.
            probes:          IVFFlat search probes.

        Returns:
            Dict mapping source_id → list of result dicts (same schema as
            ``search``), each list sorted by score descending.
        """
        if not source_ids:
            return {}

        t0 = time.time()
        vec = query_embedding.tolist()
        needs_halfvec = self.embedding_dim > 2000

        conditions: list = []
        extra_params: list = []

        placeholders = ",".join(["%s"] * len(source_ids))
        conditions.append(f"source_id IN ({placeholders})")
        extra_params.extend(source_ids)

        if notebook_id:
            conditions.append("notebook_id = %s")
            extra_params.append(notebook_id)

        where_clause = "WHERE " + " AND ".join(conditions)

        if needs_halfvec:
            score_expr = f"1 - (embedding <=> %s::halfvec({self.embedding_dim}))"
            order_expr = f"embedding <=> %s::halfvec({self.embedding_dim})"
        else:
            score_expr = "1 - (embedding <=> %s::vector)"
            order_expr = "embedding <=> %s::vector"

        sql = f"""
            SELECT * FROM (
                SELECT
                    chunk_id, text, section_id, chapter_id,
                    section_title, page_num, chunk_index,
                    char_count, word_count, source_id,
                    {score_expr} AS score,
                    ROW_NUMBER() OVER (
                        PARTITION BY source_id ORDER BY {order_expr}
                    ) AS rn
                FROM {self.table_name}
                {where_clause}
            ) ranked
            WHERE rn <= %s
            ORDER BY source_id, score DESC
        """

        params = (vec, vec, *extra_params, per_source_k)

        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SET LOCAL statement_timeout = '45s'")
                    if not needs_halfvec:
                        cur.execute(f"SET ivfflat.probes = {probes}")
                    cur.execute(sql, params)

                    by_source: Dict[str, List[Dict]] = {}
                    for row in cur.fetchall():
                        result = {
                            "chunk_id":      row[0],
                            "text":          row[1],
                            "section_id":    row[2],
                            "chapter_id":    row[3],
                            "section_title": row[4],
                            "page_num":      row[5],
                            "chunk_index":   row[6],
                            "char_count":    row[7],
                            "word_count":    row[8],
                            "source_id":     str(row[9]) if row[9] else None,
                            "score":         float(row[10]),
                        }
                        sid = result["source_id"] or ""
                        by_source.setdefault(sid, []).append(result)

            elapsed = (time.time() - t0) * 1000
            total_rows = sum(len(v) for v in by_source.values())
            logger.info(
                "✓ Multi-source search: %d results across %d sources in %.1fms",
                total_rows, len(by_source), elapsed,
            )
            return by_source

        except Exception as exc:
            raise RuntimeError(f"search_multi_source failed: {exc}") from exc

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
