"""
repo_memory_db.py
=================
Database operations for the ``repo_file_memories`` table.

DB layer only: SQL and adapters, no business logic.
"""

import json  # noqa: F401 — required alongside ``Json`` for documented JSONB usage
import logging
from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2.extras import Json

from src.config.repo_constants import (
    CONSOLIDATION_STATUS_CONSOLIDATED,
    CONSOLIDATION_STATUS_PENDING,
    IDX_REPO_FILE_MEMORIES_ENTITIES_GIN,
    IDX_REPO_FILE_MEMORIES_REPO_CONSOLIDATION,
    IDX_REPO_FILE_MEMORIES_TOPICS_GIN,
    SQL_JSONB_EMPTY_ARRAY,
    TABLE_REPO_FILE_MEMORIES,
)
from src.db.connection import get_connection, retry_on_disconnect

logger = logging.getLogger(__name__)

TABLE = TABLE_REPO_FILE_MEMORIES


def ensure_table() -> None:
    """Create ``repo_file_memories`` and related indexes if missing.

    Args:
        None

    Returns:
        None

    Raises:
        psycopg2.Error: If DDL execution fails.
    """
    pending = CONSOLIDATION_STATUS_PENDING
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {TABLE} (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    repo_id UUID NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
                    file_path TEXT NOT NULL,
                    language TEXT,
                    file_hash TEXT,
                    file_size_bytes BIGINT,
                    summary TEXT,
                    purpose TEXT,
                    exports JSONB DEFAULT {SQL_JSONB_EMPTY_ARRAY},
                    imports JSONB DEFAULT {SQL_JSONB_EMPTY_ARRAY},
                    internal_dependencies JSONB DEFAULT {SQL_JSONB_EMPTY_ARRAY},
                    patterns_detected JSONB DEFAULT {SQL_JSONB_EMPTY_ARRAY},
                    todos_and_debt JSONB DEFAULT {SQL_JSONB_EMPTY_ARRAY},
                    entities JSONB DEFAULT {SQL_JSONB_EMPTY_ARRAY},
                    topics JSONB DEFAULT {SQL_JSONB_EMPTY_ARRAY},
                    functions_and_classes JSONB DEFAULT {SQL_JSONB_EMPTY_ARRAY},
                    complexity_assessment TEXT,
                    importance_score DOUBLE PRECISION,
                    consolidation_status TEXT DEFAULT %s,
                    ingested_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(repo_id, file_path)
                )
                """,
                (pending,),
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS {IDX_REPO_FILE_MEMORIES_TOPICS_GIN}
                ON {TABLE} USING GIN (topics)
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS {IDX_REPO_FILE_MEMORIES_ENTITIES_GIN}
                ON {TABLE} USING GIN (entities)
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS {IDX_REPO_FILE_MEMORIES_REPO_CONSOLIDATION}
                ON {TABLE}(repo_id, consolidation_status)
                """
            )
    logger.info("Table '%s' ensured", TABLE)


def upsert(
    repo_id: str,
    file_path: str,
    file_hash: str,
    language: Optional[str],
    file_size_bytes: Optional[int],
    memory_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Insert or update a file memory row on ``(repo_id, file_path)``.

    Args:
        repo_id:          Repository UUID.
        file_path:        Path of the file within the repo.
        file_hash:        Content hash for the file.
        language:         Detected language label (optional).
        file_size_bytes:  File size (optional).
        memory_data:      Keys such as summary, purpose, exports, imports,
            internal_dependencies, patterns_detected, todos_and_debt,
            entities, topics, functions_and_classes, complexity_assessment,
            importance_score, consolidation_status.

    Returns:
        Dict of the inserted or updated row (all columns).

    Raises:
        psycopg2.Error: If the statement fails.
    """
    default_status = memory_data.get(
        "consolidation_status", CONSOLIDATION_STATUS_PENDING
    )
    summary = memory_data.get("summary")
    purpose = memory_data.get("purpose")
    exports = memory_data.get("exports")
    imports = memory_data.get("imports")
    internal_dependencies = memory_data.get("internal_dependencies")
    patterns_detected = memory_data.get("patterns_detected")
    todos_and_debt = memory_data.get("todos_and_debt")
    entities = memory_data.get("entities")
    topics = memory_data.get("topics")
    functions_and_classes = memory_data.get("functions_and_classes")
    complexity_assessment = memory_data.get("complexity_assessment")
    importance_score = memory_data.get("importance_score")

    def _jb(value: Any, empty: Any) -> Json:
        return Json(value if value is not None else empty)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {TABLE} (
                    repo_id, file_path, file_hash, language, file_size_bytes,
                    summary, purpose, exports, imports, internal_dependencies,
                    patterns_detected, todos_and_debt, entities, topics,
                    functions_and_classes, complexity_assessment, importance_score,
                    consolidation_status, ingested_at, updated_at
                )
                VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, NOW(), NOW()
                )
                ON CONFLICT (repo_id, file_path) DO UPDATE SET
                    file_hash = EXCLUDED.file_hash,
                    language = EXCLUDED.language,
                    file_size_bytes = EXCLUDED.file_size_bytes,
                    summary = EXCLUDED.summary,
                    purpose = EXCLUDED.purpose,
                    exports = EXCLUDED.exports,
                    imports = EXCLUDED.imports,
                    internal_dependencies = EXCLUDED.internal_dependencies,
                    patterns_detected = EXCLUDED.patterns_detected,
                    todos_and_debt = EXCLUDED.todos_and_debt,
                    entities = EXCLUDED.entities,
                    topics = EXCLUDED.topics,
                    functions_and_classes = EXCLUDED.functions_and_classes,
                    complexity_assessment = EXCLUDED.complexity_assessment,
                    importance_score = EXCLUDED.importance_score,
                    consolidation_status = EXCLUDED.consolidation_status,
                    ingested_at = NOW(),
                    updated_at = NOW()
                RETURNING *
                """,
                (
                    repo_id,
                    file_path,
                    file_hash,
                    language,
                    file_size_bytes,
                    summary,
                    purpose,
                    _jb(exports, []),
                    _jb(imports, []),
                    _jb(internal_dependencies, []),
                    _jb(patterns_detected, []),
                    _jb(todos_and_debt, []),
                    _jb(entities, []),
                    _jb(topics, []),
                    _jb(functions_and_classes, []),
                    complexity_assessment,
                    importance_score,
                    default_status,
                ),
            )
            row = cur.fetchone()
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))


@retry_on_disconnect
def find_by_repo_and_path(repo_id: str, file_path: str) -> Optional[Dict[str, Any]]:
    """Return one file memory by repo and path.

    Args:
        repo_id:   Repository UUID.
        file_path: Path of the file within the repo.

    Returns:
        Row as dict, or ``None`` if not found.

    Raises:
        psycopg2.Error: If the query fails.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT * FROM {TABLE}
                WHERE repo_id = %s AND file_path = %s
                """,
                (repo_id, file_path),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))


@retry_on_disconnect
def get_path_hash_map(repo_id: str) -> Dict[str, str]:
    """Return a ``{file_path: file_hash}`` map for all memories in a repo.

    Used by the ingest queue builder to decide which files have changed
    in a single DB round-trip instead of one query per file.

    Args:
        repo_id: Repository UUID.

    Returns:
        Dict mapping ``file_path`` to ``file_hash`` (may be ``None``).

    Raises:
        psycopg2.Error: If the query fails.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT file_path, file_hash
                FROM {TABLE}
                WHERE repo_id = %s
                """,
                (repo_id,),
            )
            return {row[0]: row[1] for row in cur.fetchall()}


@retry_on_disconnect
def list_by_repo(repo_id: str) -> List[Dict[str, Any]]:
    """List all file memories for a repository.

    Args:
        repo_id: Repository UUID.

    Returns:
        List of full row dicts ordered by ``file_path``.

    Raises:
        psycopg2.Error: If the query fails.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT * FROM {TABLE}
                WHERE repo_id = %s
                ORDER BY file_path
                """,
                (repo_id,),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


@retry_on_disconnect
def list_summaries(repo_id: str) -> List[Dict[str, Any]]:
    """Return lightweight rows for listing (path, language, summary, score).

    Args:
        repo_id: Repository UUID.

    Returns:
        List of dicts with keys ``path``, ``language``, ``summary``,
        ``importance_score``.

    Raises:
        psycopg2.Error: If the query fails.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    file_path AS path,
                    language,
                    summary,
                    importance_score
                FROM {TABLE}
                WHERE repo_id = %s
                ORDER BY file_path
                """,
                (repo_id,),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


@retry_on_disconnect
def search_by_topics(repo_id: str, topics: List[str]) -> List[Dict[str, Any]]:
    """Find memories whose ``topics`` JSONB contains all given strings.

    Args:
        repo_id: Repository UUID.
        topics:  Topic strings that must all appear in the stored JSON array
            (containment via ``@>``).

    Returns:
        Matching full rows.

    Raises:
        psycopg2.Error: If the query fails.
    """
    if not topics:
        return []
    containment = Json(topics)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT * FROM {TABLE}
                WHERE repo_id = %s
                  AND topics @> %s
                ORDER BY file_path
                """,
                (repo_id, containment),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


@retry_on_disconnect
def search_by_entities(repo_id: str, entities: List[str]) -> List[Dict[str, Any]]:
    """Find memories whose ``entities`` JSONB contains all given strings.

    Args:
        repo_id:  Repository UUID.
        entities: Entity strings that must all appear in the stored JSON array.

    Returns:
        Matching full rows.

    Raises:
        psycopg2.Error: If the query fails.
    """
    if not entities:
        return []
    containment = Json(entities)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT * FROM {TABLE}
                WHERE repo_id = %s
                  AND entities @> %s
                ORDER BY file_path
                """,
                (repo_id, containment),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


@retry_on_disconnect
def search_by_text(repo_id: str, search_text: str) -> List[Dict[str, Any]]:
    """Search ``summary`` and ``purpose`` with case-insensitive substring match.

    Args:
        repo_id:     Repository UUID.
        search_text: Substring to match (ILIKE).

    Returns:
        Matching full rows.

    Raises:
        psycopg2.Error: If the query fails.
    """
    if not search_text:
        return []
    pattern = f"%{search_text}%"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT * FROM {TABLE}
                WHERE repo_id = %s
                  AND (
                      summary ILIKE %s
                      OR purpose ILIKE %s
                  )
                ORDER BY file_path
                """,
                (repo_id, pattern, pattern),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


@retry_on_disconnect
def list_pending_consolidation(repo_id: str) -> List[Dict[str, Any]]:
    """Return memories with ``consolidation_status`` pending.

    Args:
        repo_id: Repository UUID.

    Returns:
        Full rows awaiting consolidation.

    Raises:
        psycopg2.Error: If the query fails.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT * FROM {TABLE}
                WHERE repo_id = %s
                  AND consolidation_status = %s
                ORDER BY file_path
                """,
                (repo_id, CONSOLIDATION_STATUS_PENDING),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


@retry_on_disconnect
def mark_consolidated(memory_ids: List[str]) -> None:
    """Set ``consolidation_status`` to consolidated for given memory IDs.

    Args:
        memory_ids: Primary key UUIDs of ``repo_file_memories`` rows.

    Returns:
        None

    Raises:
        psycopg2.Error: If the update fails.
    """
    if not memory_ids:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {TABLE}
                SET consolidation_status = %s,
                    updated_at = NOW()
                WHERE id = ANY(%s::uuid[])
                """,
                (CONSOLIDATION_STATUS_CONSOLIDATED, memory_ids),
            )


def delete_by_repo(repo_id: str) -> None:
    """Delete all file memories for a repository.

    Args:
        repo_id: Repository UUID.

    Returns:
        None

    Raises:
        psycopg2.Error: If the delete fails.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {TABLE} WHERE repo_id = %s", (repo_id,))


@retry_on_disconnect
def delete_stale_files(repo_id: str, current_paths: List[str]) -> None:
    """Remove memories whose ``file_path`` is not in ``current_paths``.

    Args:
        repo_id:       Repository UUID.
        current_paths: Paths that still exist; all other rows for the repo
            are deleted. An empty list deletes every memory for the repo.

    Returns:
        None

    Raises:
        psycopg2.Error: If the delete fails.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                DELETE FROM {TABLE}
                WHERE repo_id = %s
                  AND NOT (file_path = ANY(%s::text[]))
                """,
                (repo_id, current_paths),
            )
