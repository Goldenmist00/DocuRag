"""
repo_context_db.py
===================
Database operations for ``repo_context`` and ``repo_consolidations``.

DB layer only: SQL and adapters, no business logic.
"""

import json  # noqa: F401 — required for JSONB payloads alongside ``Json`` adapter
import logging
from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2.extras import Json

from src.config.repo_constants import (
    CONSOLIDATION_SCOPE_DEFAULT,
    CONSOLIDATION_SEVERITY_DEFAULT,
    IDX_REPO_CONSOLIDATIONS_REPO_ID,
    IDX_REPO_CONSOLIDATIONS_REPO_TYPE,
    REPO_CONTEXT_INITIAL_VERSION,
    SQL_JSONB_EMPTY_ARRAY,
    SQL_JSONB_EMPTY_OBJECT,
    TABLE_REPO_CONSOLIDATIONS,
    TABLE_REPO_CONTEXT,
)
from src.db.connection import get_connection

logger = logging.getLogger(__name__)

TABLE_CONTEXT = TABLE_REPO_CONTEXT
TABLE_CONSOLIDATIONS = TABLE_REPO_CONSOLIDATIONS


def ensure_table() -> None:
    """Create ``repo_context`` and ``repo_consolidations`` if missing.

    Args:
        None

    Returns:
        None

    Raises:
        psycopg2.Error: If DDL execution fails.
    """
    sev = CONSOLIDATION_SEVERITY_DEFAULT
    scp = CONSOLIDATION_SCOPE_DEFAULT
    v0 = REPO_CONTEXT_INITIAL_VERSION
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {TABLE_CONTEXT} (
                    repo_id UUID PRIMARY KEY REFERENCES repos(id) ON DELETE CASCADE,
                    architecture JSONB DEFAULT {SQL_JSONB_EMPTY_OBJECT},
                    tech_stack JSONB DEFAULT {SQL_JSONB_EMPTY_OBJECT},
                    features JSONB DEFAULT {SQL_JSONB_EMPTY_ARRAY},
                    api_surface JSONB DEFAULT {SQL_JSONB_EMPTY_ARRAY},
                    future_scope JSONB DEFAULT {SQL_JSONB_EMPTY_ARRAY},
                    security_findings JSONB DEFAULT {SQL_JSONB_EMPTY_ARRAY},
                    tech_debt JSONB DEFAULT {SQL_JSONB_EMPTY_ARRAY},
                    test_coverage JSONB DEFAULT {SQL_JSONB_EMPTY_OBJECT},
                    dependency_graph JSONB DEFAULT {SQL_JSONB_EMPTY_OBJECT},
                    key_files JSONB DEFAULT {SQL_JSONB_EMPTY_ARRAY},
                    entry_points JSONB DEFAULT {SQL_JSONB_EMPTY_ARRAY},
                    file_responsibility_map JSONB DEFAULT {SQL_JSONB_EMPTY_OBJECT},
                    api_routes JSONB DEFAULT {SQL_JSONB_EMPTY_ARRAY},
                    data_flow JSONB DEFAULT {SQL_JSONB_EMPTY_ARRAY},
                    last_consolidated_at TIMESTAMPTZ,
                    version INT DEFAULT {v0},
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            for col_name, col_default in [
                ("entry_points", SQL_JSONB_EMPTY_ARRAY),
                ("file_responsibility_map", SQL_JSONB_EMPTY_OBJECT),
                ("api_routes", SQL_JSONB_EMPTY_ARRAY),
                ("data_flow", SQL_JSONB_EMPTY_ARRAY),
            ]:
                try:
                    cur.execute(
                        f"ALTER TABLE {TABLE_CONTEXT} ADD COLUMN IF NOT EXISTS "
                        f"{col_name} JSONB DEFAULT {col_default}"
                    )
                except Exception:
                    pass
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {TABLE_CONSOLIDATIONS} (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    repo_id UUID NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
                    consolidation_type TEXT NOT NULL,
                    insight TEXT NOT NULL,
                    evidence JSONB DEFAULT {SQL_JSONB_EMPTY_ARRAY},
                    severity TEXT DEFAULT %s,
                    scope TEXT DEFAULT %s,
                    actionable_suggestion TEXT,
                    source_memory_ids JSONB DEFAULT {SQL_JSONB_EMPTY_ARRAY},
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """,
                (sev, scp),
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS {IDX_REPO_CONSOLIDATIONS_REPO_ID}
                ON {TABLE_CONSOLIDATIONS}(repo_id)
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS {IDX_REPO_CONSOLIDATIONS_REPO_TYPE}
                ON {TABLE_CONSOLIDATIONS}(repo_id, consolidation_type)
                """
            )
    logger.info("Tables '%s', '%s' ensured", TABLE_CONTEXT, TABLE_CONSOLIDATIONS)


def upsert_context(repo_id: str, context_data: Dict[str, Any]) -> Dict[str, Any]:
    """Insert or update the single ``repo_context`` row for a repo.

    Args:
        repo_id:      Repository UUID (primary key).
        context_data: Optional keys: architecture, tech_stack, features,
            api_surface, future_scope, security_findings, tech_debt,
            test_coverage, dependency_graph, key_files,
            last_consolidated_at, version.

    Returns:
        The row after insert or update (all columns).

    Raises:
        psycopg2.Error: If the statement fails.
    """

    def _jb(value: Any, empty: Any) -> Json:
        return Json(value if value is not None else empty)

    architecture = context_data.get("architecture")
    tech_stack = context_data.get("tech_stack")
    features = context_data.get("features")
    api_surface = context_data.get("api_surface")
    future_scope = context_data.get("future_scope")
    security_findings = context_data.get("security_findings")
    tech_debt = context_data.get("tech_debt")
    test_coverage = context_data.get("test_coverage")
    dependency_graph = context_data.get("dependency_graph")
    key_files = context_data.get("key_files")
    entry_points = context_data.get("entry_points")
    file_responsibility_map = context_data.get("file_responsibility_map")
    api_routes = context_data.get("api_routes")
    data_flow = context_data.get("data_flow")
    last_consolidated_at = context_data.get("last_consolidated_at")
    version = context_data.get("version")
    if version is None:
        version = REPO_CONTEXT_INITIAL_VERSION

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {TABLE_CONTEXT} (
                    repo_id, architecture, tech_stack, features, api_surface,
                    future_scope, security_findings, tech_debt, test_coverage,
                    dependency_graph, key_files,
                    entry_points, file_responsibility_map, api_routes, data_flow,
                    last_consolidated_at, version,
                    updated_at
                )
                VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s,
                    %s, %s, %s, %s,
                    %s, %s,
                    NOW()
                )
                ON CONFLICT (repo_id) DO UPDATE SET
                    architecture = EXCLUDED.architecture,
                    tech_stack = EXCLUDED.tech_stack,
                    features = EXCLUDED.features,
                    api_surface = EXCLUDED.api_surface,
                    future_scope = EXCLUDED.future_scope,
                    security_findings = EXCLUDED.security_findings,
                    tech_debt = EXCLUDED.tech_debt,
                    test_coverage = EXCLUDED.test_coverage,
                    dependency_graph = EXCLUDED.dependency_graph,
                    key_files = EXCLUDED.key_files,
                    entry_points = EXCLUDED.entry_points,
                    file_responsibility_map = EXCLUDED.file_responsibility_map,
                    api_routes = EXCLUDED.api_routes,
                    data_flow = EXCLUDED.data_flow,
                    last_consolidated_at = EXCLUDED.last_consolidated_at,
                    version = EXCLUDED.version,
                    updated_at = NOW()
                RETURNING *
                """,
                (
                    repo_id,
                    _jb(architecture, {}),
                    _jb(tech_stack, {}),
                    _jb(features, []),
                    _jb(api_surface, []),
                    _jb(future_scope, []),
                    _jb(security_findings, []),
                    _jb(tech_debt, []),
                    _jb(test_coverage, {}),
                    _jb(dependency_graph, {}),
                    _jb(key_files, []),
                    _jb(entry_points, []),
                    _jb(file_responsibility_map, {}),
                    _jb(api_routes, []),
                    _jb(data_flow, []),
                    last_consolidated_at,
                    version,
                ),
            )
            row = cur.fetchone()
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))


def find_by_repo_id(repo_id: str) -> Optional[Dict[str, Any]]:
    """Load ``repo_context`` by repository UUID.

    Args:
        repo_id: Repository UUID.

    Returns:
        Row dict or ``None``.

    Raises:
        psycopg2.Error: If the query fails.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT * FROM {TABLE_CONTEXT} WHERE repo_id = %s",
                (repo_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))


def insert_consolidation(
    repo_id: str,
    consolidation_type: str,
    insight: str,
    evidence: Optional[List[Any]] = None,
    severity: Optional[str] = None,
    scope: Optional[str] = None,
    actionable_suggestion: Optional[str] = None,
    source_memory_ids: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """Insert one ``repo_consolidations`` row and return it.

    Args:
        repo_id:               Owning repository UUID.
        consolidation_type:    Category label for the insight.
        insight:               Main consolidation text.
        evidence:              Optional JSON-serializable list (default empty).
        severity:              Optional severity (default from constants).
        scope:                   Optional scope (default from constants).
        actionable_suggestion: Optional follow-up text.
        source_memory_ids:     Optional list of contributing memory UUIDs.

    Returns:
        New row as dict (all columns).

    Raises:
        psycopg2.Error: If the insert fails.
    """
    ev = evidence if evidence is not None else []
    sev = severity if severity is not None else CONSOLIDATION_SEVERITY_DEFAULT
    scp = scope if scope is not None else CONSOLIDATION_SCOPE_DEFAULT
    src = source_memory_ids if source_memory_ids is not None else []
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {TABLE_CONSOLIDATIONS} (
                    repo_id, consolidation_type, insight, evidence,
                    severity, scope, actionable_suggestion, source_memory_ids
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    repo_id,
                    consolidation_type,
                    insight,
                    Json(ev),
                    sev,
                    scp,
                    actionable_suggestion,
                    Json(src),
                ),
            )
            row = cur.fetchone()
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))


def list_consolidations(
    repo_id: str,
    consolidation_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List consolidation rows for a repo, optionally filtered by type.

    Args:
        repo_id:             Repository UUID.
        consolidation_type: If set, filter to this type; else all types.

    Returns:
        Rows ordered by ``created_at`` descending.

    Raises:
        psycopg2.Error: If the query fails.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            if consolidation_type is None:
                cur.execute(
                    f"""
                    SELECT * FROM {TABLE_CONSOLIDATIONS}
                    WHERE repo_id = %s
                    ORDER BY created_at DESC
                    """,
                    (repo_id,),
                )
            else:
                cur.execute(
                    f"""
                    SELECT * FROM {TABLE_CONSOLIDATIONS}
                    WHERE repo_id = %s
                      AND consolidation_type = %s
                    ORDER BY created_at DESC
                    """,
                    (repo_id, consolidation_type),
                )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def delete_consolidations_by_repo(repo_id: str) -> None:
    """Delete all consolidation rows for a repository.

    Args:
        repo_id: Repository UUID.

    Returns:
        None

    Raises:
        psycopg2.Error: If the delete fails.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {TABLE_CONSOLIDATIONS} WHERE repo_id = %s",
                (repo_id,),
            )


def delete_context_by_repo(repo_id: str) -> None:
    """Delete the ``repo_context`` row for a repository.

    Args:
        repo_id: Repository UUID.

    Returns:
        None

    Raises:
        psycopg2.Error: If the delete fails.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {TABLE_CONTEXT} WHERE repo_id = %s",
                (repo_id,),
            )
