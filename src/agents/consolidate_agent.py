"""
consolidate_agent.py
====================
Service-layer consolidation: batch file memories, extract cross-file insights
via LLM, persist consolidations and assembled global context.
"""

from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.agents.ingest_agent import _ingest_chat_completion, _strip_json_fence
from src.config.repo_constants import (
    CONSOLIDATION_BATCH_SIZE,
    CONSOLIDATION_SCOPE_DEFAULT,
    CONSOLIDATION_SEVERITY_DEFAULT,
    CONSOLIDATION_TYPES as _CONSOLIDATION_TYPE_VALUES,
    CONTEXT_ASSEMBLY_USER_LEADIN,
    REPO_CONTEXT_INITIAL_VERSION,
)
from src.db import repo_context_db, repo_db, repo_memory_db
from src.generator import Generator
from src.utils.repo_errors import RepoNotFoundError

logger = logging.getLogger(__name__)

CONSOLIDATION_TYPES = list(_CONSOLIDATION_TYPE_VALUES)
"""Allowed consolidation type labels (from ``repo_constants``)."""

CONSOLIDATION_PROMPT = (
    "You are a senior software architect. Given a batch of per-file memory "
    "summaries with AST-extracted structural data (imports, exports, "
    "functions/classes) and cross-file reference edges, extract cross-file "
    "insights.\n\n"
    "Each input line is a JSON object with: file_path, summary, topics, "
    "entities, importance_score, imports, exports, functions_and_classes, "
    "reference_edges (list of {target_file, type}).\n\n"
    "For each insight return one JSON object with:\n"
    "- consolidation_type: one of: "
    + ", ".join(CONSOLIDATION_TYPES)
    + "\n"
    "- insight: concise cross-file finding (string) — be SPECIFIC with "
    "file paths and function names, not abstract\n"
    "- evidence: list of objects with keys \"file\" (repo-relative path), "
    "\"finding\" (string)\n"
    "- severity: one of info, warning, critical\n"
    "- scope: \"project-wide\" or \"module:X\" where X is a path prefix or "
    "module name\n"
    "- actionable_suggestion: string (may be empty)\n"
    "- file_responsibilities: object mapping file_path -> one-line "
    "responsibility description for each file in this batch\n\n"
    "Respond with a single JSON object only (no markdown fences): "
    '{"insights": [ ... ]}. Use empty array if none. Be specific and factual, '
    "always reference actual file paths and symbols."
)

CONTEXT_ASSEMBLY_PROMPT = (
    "You are a senior software architect. Given consolidation insights "
    "(cross-repo findings with evidence and file responsibilities), build "
    "one JSON object only (no markdown fences) with these keys:\n"
    "- architecture: object (high-level structure, layers, patterns)\n"
    "- tech_stack: object (languages, frameworks, databases, infra)\n"
    "- features: array of strings\n"
    "- api_surface: array of strings\n"
    "- future_scope: array of strings\n"
    "- security_findings: array of strings\n"
    "- tech_debt: array of strings\n"
    "- test_coverage: object\n"
    "- dependency_graph: object\n"
    "- key_files: array of strings (important file paths)\n"
    "- entry_points: array of objects {\"file\": string, \"role\": string} "
    "(main files, CLI scripts, API servers)\n"
    "- file_responsibility_map: object mapping file_path -> one-line role "
    "description\n"
    "- api_routes: array of objects {\"method\": string, \"path\": string, "
    "\"handler_file\": string, \"handler_function\": string}\n"
    "- data_flow: array of objects {\"from_file\": string, \"to_file\": "
    "string, \"mechanism\": string} (import, call, event)\n\n"
    "Ground every field in the provided insights. Be SPECIFIC — include "
    "actual file paths, function names, and route patterns. Use empty "
    "object/array where unknown."
)


def _ensure_generator(generator: Optional[Generator]) -> Generator:
    """Return a usable Generator, constructing one if omitted.

    Args:
        generator: Optional pre-built ``Generator`` instance.

    Returns:
        A ``Generator`` with valid API keys.

    Raises:
        ValueError: If no provider keys are available (from ``Generator``).
    """
    if generator is not None:
        return generator
    return Generator()


def _importance_value(row: Dict[str, Any]) -> float:
    """Numeric importance for sorting (missing scores sort last).

    Args:
        row: A ``repo_file_memories`` row dict.

    Returns:
        Importance as float, or ``0.0`` if absent.

    Raises:
        None.
    """
    score = row.get("importance_score")
    if score is None:
        return 0.0
    try:
        return float(score)
    except (TypeError, ValueError):
        return 0.0


def _format_memory_batch_lines(
    rows: List[Dict[str, Any]],
    repo_id: Optional[str] = None,
) -> str:
    """Serialize batch rows for the consolidation user message.

    Includes AST-extracted imports, exports, functions/classes, and
    reference graph edges when available.

    Args:
        rows:    Pending memory rows for one batch.
        repo_id: Repository UUID for fetching reference edges.

    Returns:
        Newline-delimited JSON summaries for the LLM.

    Raises:
        None.
    """
    ref_edges_by_file: Dict[str, List[Dict[str, Any]]] = {}
    if repo_id:
        try:
            from src.db import repo_reference_db
            file_paths = [r.get("file_path", "") for r in rows if r.get("file_path")]
            all_deps = repo_reference_db.get_dependencies_batch(repo_id, file_paths)
            for fp, deps in all_deps.items():
                ref_edges_by_file[fp] = [
                    {"target_file": d["target_file"], "type": d["reference_type"]}
                    for d in deps[:10]
                ]
        except Exception:
            pass

    lines: List[str] = []
    for r in rows:
        fp = r.get("file_path", "")
        payload: Dict[str, Any] = {
            "file_path": fp,
            "summary": r.get("summary"),
            "topics": r.get("topics"),
            "entities": r.get("entities"),
            "importance_score": r.get("importance_score"),
            "imports": r.get("imports"),
            "exports": r.get("exports"),
            "functions_and_classes": r.get("functions_and_classes"),
        }
        edges = ref_edges_by_file.get(fp)
        if edges:
            payload["reference_edges"] = edges
        lines.append(json.dumps(payload, ensure_ascii=False))
    return "\n".join(lines)


def _paths_to_source_ids(
    evidence: List[Any],
    path_to_row: Dict[str, Dict[str, Any]],
) -> List[str]:
    """Map evidence file paths to memory UUID strings.

    Args:
        evidence: List of dict-like items with a ``file`` path.
        path_to_row: Map normalized file path -> memory row.

    Returns:
        Distinct string UUIDs for rows referenced by evidence.

    Raises:
        None.
    """
    out: List[str] = []
    seen: set = set()
    for item in evidence or []:
        if not isinstance(item, dict):
            continue
        fp = item.get("file")
        if not fp:
            continue
        row = path_to_row.get(str(fp))
        if not row:
            continue
        mid = str(row.get("id", ""))
        if mid and mid not in seen:
            seen.add(mid)
            out.append(mid)
    return out


def _parse_insights_payload(raw: str) -> List[Dict[str, Any]]:
    """Parse consolidation LLM output into insight dicts.

    Args:
        raw: Raw assistant text (possibly JSON-fenced).

    Returns:
        List of insight dicts; empty if parsing fails.

    Raises:
        None.
    """
    try:
        inner = _strip_json_fence(raw)
        data = json.loads(inner)
        items = data.get("insights")
        if isinstance(items, list):
            return [x for x in items if isinstance(x, dict)]
    except (json.JSONDecodeError, TypeError, AttributeError) as exc:
        logger.warning("Consolidation JSON parse failed: %s", exc)
    return []


def _parse_context_payload(raw: str) -> Optional[Dict[str, Any]]:
    """Parse global context JSON from the LLM.

    Args:
        raw: Raw assistant text (possibly JSON-fenced).

    Returns:
        Context dict with expected keys, or ``None`` if invalid.

    Raises:
        None.
    """
    keys = (
        "architecture",
        "tech_stack",
        "features",
        "api_surface",
        "future_scope",
        "security_findings",
        "tech_debt",
        "test_coverage",
        "dependency_graph",
        "key_files",
        "entry_points",
        "file_responsibility_map",
        "api_routes",
        "data_flow",
    )
    try:
        inner = _strip_json_fence(raw)
        data = json.loads(inner)
        if not isinstance(data, dict):
            return None
        return {k: data.get(k) for k in keys}
    except (json.JSONDecodeError, TypeError, AttributeError) as exc:
        logger.warning("Context assembly JSON parse failed: %s", exc)
        return None


def _empty_context_template() -> Dict[str, Any]:
    """Default structured context when no LLM output is available.

    Args:
        None

    Returns:
        Dict with all ``repo_context`` JSONB keys set to empty containers.

    Raises:
        None.
    """
    return {
        "architecture": {},
        "tech_stack": {},
        "features": [],
        "api_surface": [],
        "future_scope": [],
        "security_findings": [],
        "tech_debt": [],
        "test_coverage": {},
        "dependency_graph": {},
        "key_files": [],
        "entry_points": [],
        "file_responsibility_map": {},
        "api_routes": [],
        "data_flow": [],
    }


def _persist_assembled_context(repo_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Set version and timestamp, upsert ``repo_context``, return stored fields.

    Args:
        repo_id: Repository UUID.
        body:    Context fields (mutated with ``version`` and timestamp).

    Returns:
        Copy of the payload passed to ``upsert_context``.

    Raises:
        None.
    """
    ver = _next_context_version(repo_id)
    body["version"] = ver
    body["last_consolidated_at"] = datetime.now(timezone.utc)
    repo_context_db.upsert_context(repo_id, body)
    return dict(body)


def _next_context_version(repo_id: str) -> int:
    """Compute the version number for the next context upsert.

    Args:
        repo_id: Repository UUID.

    Returns:
        Monotonic version (initial or previous + 1).

    Raises:
        None.
    """
    existing = repo_context_db.find_by_repo_id(repo_id)
    if not existing:
        return REPO_CONTEXT_INITIAL_VERSION
    prev = existing.get("version")
    try:
        return int(prev) + 1 if prev is not None else REPO_CONTEXT_INITIAL_VERSION
    except (TypeError, ValueError):
        return REPO_CONTEXT_INITIAL_VERSION


def _format_consolidations_text(rows: List[Dict[str, Any]]) -> str:
    """Turn consolidation rows into readable text for context assembly.

    Args:
        rows: Rows from ``list_consolidations``.

    Returns:
        Plain-text block for the LLM user message.

    Raises:
        None.
    """
    parts: List[str] = []
    for r in rows:
        parts.append(
            json.dumps(
                {
                    "type": r.get("consolidation_type"),
                    "insight": r.get("insight"),
                    "evidence": r.get("evidence"),
                    "severity": r.get("severity"),
                    "scope": r.get("scope"),
                    "actionable_suggestion": r.get("actionable_suggestion"),
                },
                ensure_ascii=False,
            )
        )
    return "\n".join(parts)


def _call_consolidation_llm(
    user_body: str,
    gen: Generator,
) -> str:
    """Run one consolidation completion.

    Args:
        user_body: Batch payload text for the user message.
        gen:       ``Generator`` instance (keys validated).

    Returns:
        Raw assistant string.

    Raises:
        RuntimeError: If the LLM call fails.
    """
    messages = [
        {"role": "system", "content": CONSOLIDATION_PROMPT},
        {"role": "user", "content": user_body},
    ]
    return _ingest_chat_completion(messages, gen)


def _call_context_llm(insights_text: str, gen: Generator) -> str:
    """Run global context assembly completion.

    Args:
        insights_text: Serialized consolidation insights.
        gen:             ``Generator`` instance.

    Returns:
        Raw assistant JSON string.

    Raises:
        RuntimeError: If the LLM call fails.
    """
    user_msg = CONTEXT_ASSEMBLY_USER_LEADIN + insights_text
    messages = [
        {"role": "system", "content": CONTEXT_ASSEMBLY_PROMPT},
        {"role": "user", "content": user_msg},
    ]
    return _ingest_chat_completion(messages, gen)


def _store_batch_insights(
    repo_id: str,
    batch_rows: List[Dict[str, Any]],
    insights: List[Dict[str, Any]],
) -> int:
    """Persist parsed insights and return count stored.

    Args:
        repo_id:     Repository UUID.
        batch_rows:  Memory rows in this batch.
        insights:    Parsed insight dicts from the LLM.

    Returns:
        Number of rows inserted into ``repo_consolidations``.

    Raises:
        None.
    """
    path_map = {str(r.get("file_path")): r for r in batch_rows if r.get("file_path")}
    stored = 0
    for ins in insights:
        ctype = ins.get("consolidation_type")
        if ctype not in CONSOLIDATION_TYPES:
            ctype = CONSOLIDATION_TYPES[0]
        evidence = ins.get("evidence")
        if not isinstance(evidence, list):
            evidence = []
        src_ids = _paths_to_source_ids(evidence, path_map)
        try:
            repo_context_db.insert_consolidation(
                repo_id,
                str(ctype),
                str(ins.get("insight") or ""),
                evidence=evidence,
                severity=str(ins.get("severity") or CONSOLIDATION_SEVERITY_DEFAULT),
                scope=str(ins.get("scope") or CONSOLIDATION_SCOPE_DEFAULT),
                actionable_suggestion=(
                    str(ins.get("actionable_suggestion"))
                    if ins.get("actionable_suggestion") is not None
                    else None
                ),
                source_memory_ids=src_ids,
            )
            stored += 1
        except Exception as exc:
            logger.warning("insert_consolidation failed: %s", exc)
    return stored


def _assemble_global_context(repo_id: str, generator: Optional[Generator] = None) -> Dict[str, Any]:
    """Load consolidations, assemble structured context via LLM, upsert DB row.

    Args:
        repo_id:   Repository UUID.
        generator: Optional ``Generator``; one is created if omitted.

    Returns:
        Parsed context fields dict (may be partial on LLM/parse failure).

    Raises:
        RepoNotFoundError: If the repository does not exist.
        ValueError: If API keys are missing when ``generator`` is omitted.
        RuntimeError: If the LLM call fails.
    """
    if repo_db.find_by_id(repo_id) is None:
        raise RepoNotFoundError(f"Repository not found: {repo_id}")
    gen = _ensure_generator(generator)
    text = _format_consolidations_text(repo_context_db.list_consolidations(repo_id))
    if not text.strip():
        return _persist_assembled_context(repo_id, _empty_context_template())
    raw = _call_context_llm(text, gen)
    parsed = _parse_context_payload(raw) or _empty_context_template()
    return _persist_assembled_context(repo_id, parsed)


def consolidate_repo(repo_id: str, generator: Optional[Generator] = None) -> Dict[str, Any]:
    """Process pending memories in batches, persist insights, assemble context.

    Args:
        repo_id:   Repository UUID.
        generator: Optional ``Generator`` for LLM calls.

    Returns:
        Stats dict: ``batches_processed``, ``insights_stored``,
        ``memories_marked_consolidated``, ``context``.

    Raises:
        RepoNotFoundError: If the repository does not exist.
        ValueError: If API keys are missing when ``generator`` is omitted.
        RuntimeError: If a required LLM call fails.
    """
    if repo_db.find_by_id(repo_id) is None:
        raise RepoNotFoundError(f"Repository not found: {repo_id}")
    repo_memory_db.ensure_table()
    repo_context_db.ensure_table()
    gen = _ensure_generator(generator)
    repo_db.update_progress(repo_id, "consolidating", 0, 1, "Loading pending memories…")
    pending = repo_memory_db.list_pending_consolidation(repo_id)
    pending.sort(key=_importance_value, reverse=True)
    batch_size = CONSOLIDATION_BATCH_SIZE
    total_insights = 0
    batches_done = 0
    marked_ids: List[str] = []
    total_batches = max(1, (len(pending) + batch_size - 1) // batch_size)

    chunks = [pending[i : i + batch_size] for i in range(0, len(pending), batch_size)]
    progress_lock = threading.Lock()

    def _process_batch(
        batch_idx: int, chunk: List[Dict[str, Any]],
    ) -> Tuple[int, List[str]]:
        """Process a single consolidation batch (LLM call + persist)."""
        user_body = _format_memory_batch_lines(chunk, repo_id=repo_id)
        raw = _call_consolidation_llm(user_body, gen)
        insights = _parse_insights_payload(raw)
        n_insights = _store_batch_insights(repo_id, chunk, insights)
        ids = [str(r["id"]) for r in chunk if r.get("id")]
        if ids:
            repo_memory_db.mark_consolidated(ids)
        return n_insights, ids

    max_workers = min(3, len(chunks))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_process_batch, idx, chunk): idx
            for idx, chunk in enumerate(chunks)
        }
        for fut in as_completed(futures):
            try:
                n_insights, ids = fut.result()
                with progress_lock:
                    total_insights += n_insights
                    marked_ids.extend(ids)
                    batches_done += 1
                    repo_db.update_progress(
                        repo_id, "consolidating", batches_done, total_batches + 1,
                        f"Analyzed batch {batches_done}/{total_batches}",
                    )
            except Exception:
                logger.exception("Consolidation batch failed")
    repo_db.update_progress(
        repo_id, "consolidating", total_batches, total_batches + 1,
        "Assembling global context…",
    )
    ctx = _assemble_global_context(repo_id, gen)
    repo_db.update_progress(
        repo_id, "consolidating", total_batches + 1, total_batches + 1,
        "Consolidation complete",
    )
    return {
        "batches_processed": batches_done,
        "insights_stored": total_insights,
        "memories_marked_consolidated": len(marked_ids),
        "context": ctx,
    }
