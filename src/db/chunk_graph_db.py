"""
chunk_graph_db.py
=================
Database operations for the ``chunk_graph`` table.

Stores entity-based edges between document chunks so multi-hop
retrieval can follow relationships across non-contiguous pages.

Each edge connects two chunks that share a concept/entity,
with a relation type and optional weight.
"""

import logging
import time
from typing import Dict, List, Optional, Set

from psycopg2.extras import execute_values

from src.db.connection import get_connection

logger = logging.getLogger(__name__)

TABLE = "chunk_graph"


def ensure_table() -> None:
    """
    Create the chunk_graph table and its indexes if they do not exist.

    Raises:
        RuntimeError: If table creation fails.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {TABLE} (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    source_chunk_id TEXT NOT NULL,
                    target_chunk_id TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    entity TEXT,
                    weight FLOAT DEFAULT 1.0,
                    notebook_id UUID NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(source_chunk_id, target_chunk_id, relation_type)
                )
            """)
            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_chunk_graph_source
                ON {TABLE}(source_chunk_id)
            """)
            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_chunk_graph_target
                ON {TABLE}(target_chunk_id)
            """)
            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_chunk_graph_notebook
                ON {TABLE}(notebook_id)
            """)
            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_chunk_graph_entity
                ON {TABLE}(entity)
            """)
    logger.info("chunk_graph table ensured")


def insert_edges(edges: List[Dict]) -> int:
    """
    Batch-insert edges into the graph. Conflicts are silently skipped.

    Each edge dict must contain:
        source_chunk_id, target_chunk_id, relation_type,
        notebook_id, and optionally entity, weight.

    Args:
        edges: List of edge dicts.

    Returns:
        Number of edges inserted.
    """
    if not edges:
        return 0

    t0 = time.time()
    rows = [
        (
            e["source_chunk_id"],
            e["target_chunk_id"],
            e["relation_type"],
            e.get("entity", ""),
            e.get("weight", 1.0),
            e["notebook_id"],
        )
        for e in edges
    ]

    sql = f"""
        INSERT INTO {TABLE}
            (source_chunk_id, target_chunk_id, relation_type, entity, weight, notebook_id)
        VALUES %s
        ON CONFLICT (source_chunk_id, target_chunk_id, relation_type) DO NOTHING
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            execute_values(cur, sql, rows)
            inserted = cur.rowcount

    elapsed = time.time() - t0
    logger.info("Inserted %d graph edges in %.2fs", inserted, elapsed)
    return inserted


def get_neighbors(
    chunk_ids: List[str],
    notebook_id: Optional[str] = None,
    max_per_chunk: int = 5,
) -> List[Dict]:
    """
    Fetch graph neighbors for a set of chunk IDs (both directions).

    Args:
        chunk_ids:    Chunk IDs to find neighbors for.
        notebook_id:  If provided, restrict to this notebook.
        max_per_chunk: Max neighbors to return per input chunk.

    Returns:
        List of edge dicts with source_chunk_id, target_chunk_id,
        relation_type, entity, weight.
    """
    if not chunk_ids:
        return []

    placeholders = ",".join(["%s"] * len(chunk_ids))
    params: list = list(chunk_ids) + list(chunk_ids)

    where_notebook = ""
    if notebook_id:
        where_notebook = " AND notebook_id = %s"
        params.append(notebook_id)
        params.append(notebook_id)

    sql = f"""
        (
            SELECT source_chunk_id, target_chunk_id,
                   relation_type, entity, weight
            FROM {TABLE}
            WHERE source_chunk_id IN ({placeholders}){where_notebook}
            ORDER BY weight DESC
        )
        UNION
        (
            SELECT source_chunk_id, target_chunk_id,
                   relation_type, entity, weight
            FROM {TABLE}
            WHERE target_chunk_id IN ({placeholders}){where_notebook}
            ORDER BY weight DESC
        )
    """

    # Rebuild params for the UNION (each sub-query needs its own set)
    final_params: list = list(chunk_ids)
    if notebook_id:
        final_params.append(notebook_id)
    final_params.extend(chunk_ids)
    if notebook_id:
        final_params.append(notebook_id)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, final_params)
            rows = cur.fetchall()

    results = [
        {
            "source_chunk_id": r[0],
            "target_chunk_id": r[1],
            "relation_type": r[2],
            "entity": r[3],
            "weight": float(r[4]),
        }
        for r in rows
    ]

    logger.info(
        "Graph lookup: %d input chunks -> %d edges",
        len(chunk_ids), len(results),
    )
    return results


def get_by_entity(
    entity: str,
    notebook_id: Optional[str] = None,
) -> List[Dict]:
    """
    Find all edges involving a specific entity.

    Args:
        entity:      Entity string to search for (case-insensitive).
        notebook_id: If provided, restrict to this notebook.

    Returns:
        List of edge dicts.
    """
    params: list = [entity.lower()]
    where_nb = ""
    if notebook_id:
        where_nb = " AND notebook_id = %s"
        params.append(notebook_id)

    sql = f"""
        SELECT source_chunk_id, target_chunk_id,
               relation_type, entity, weight
        FROM {TABLE}
        WHERE LOWER(entity) = %s{where_nb}
        ORDER BY weight DESC
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

    return [
        {
            "source_chunk_id": r[0],
            "target_chunk_id": r[1],
            "relation_type": r[2],
            "entity": r[3],
            "weight": float(r[4]),
        }
        for r in rows
    ]


def delete_by_notebook(notebook_id: str) -> int:
    """
    Delete all graph edges for a notebook.

    Args:
        notebook_id: UUID string.

    Returns:
        Number of rows deleted.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {TABLE} WHERE notebook_id = %s",
                (notebook_id,),
            )
            count = cur.rowcount
    logger.info("Deleted %d graph edges for notebook %s", count, notebook_id)
    return count


def delete_by_source_chunks(chunk_ids: List[str]) -> int:
    """
    Delete all edges involving any of the given chunk IDs.

    Args:
        chunk_ids: List of chunk_id strings.

    Returns:
        Number of rows deleted.
    """
    if not chunk_ids:
        return 0

    placeholders = ",".join(["%s"] * len(chunk_ids))
    sql = f"""
        DELETE FROM {TABLE}
        WHERE source_chunk_id IN ({placeholders})
           OR target_chunk_id IN ({placeholders})
    """
    params = list(chunk_ids) + list(chunk_ids)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            count = cur.rowcount
    logger.info("Deleted %d graph edges for %d chunk IDs", count, len(chunk_ids))
    return count
