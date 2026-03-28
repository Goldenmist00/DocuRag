"""
reference_graph.py
==================
Build and query cross-file reference graphs from AST-extracted data.

Resolves import paths to actual repository files, creates typed edges
(import, call, inheritance) and persists them via ``repo_reference_db``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Set

from src.db import repo_reference_db
from src.repo.ast_parser import ASTResult

logger = logging.getLogger(__name__)


def _normalize_import_to_file(
    module_path: str,
    source_file: str,
    repo_files: Set[str],
) -> Optional[str]:
    """Attempt to resolve an import module string to a repo file path.

    Tries several resolution strategies:
      1. Direct match (e.g. ``src.utils.logger`` -> ``src/utils/logger.py``)
      2. Relative path from source (e.g. ``./utils`` -> ``src/utils.py``)
      3. Index file (e.g. ``src/utils`` -> ``src/utils/index.ts``)

    Args:
        module_path: Raw import module string from AST.
        source_file: POSIX-normalized path of the importing file.
        repo_files:  Set of all known file paths in the repo.

    Returns:
        Resolved repo file path, or ``None`` if unresolvable.
    """
    cleaned = module_path.strip().strip("'\"")

    if cleaned.startswith("."):
        source_dir = str(PurePosixPath(source_file).parent)
        if cleaned.startswith("./"):
            cleaned = cleaned[2:]
        elif cleaned.startswith("../"):
            source_dir = str(PurePosixPath(source_dir).parent)
            cleaned = cleaned[3:]
        elif cleaned == ".":
            cleaned = "__init__"
        candidate_base = f"{source_dir}/{cleaned}" if source_dir != "." else cleaned
    else:
        candidate_base = cleaned.replace(".", "/")

    extensions = [".py", ".ts", ".tsx", ".js", ".jsx", ".java", ".go", ".rs", ""]
    index_files = ["__init__.py", "index.ts", "index.tsx", "index.js", "index.jsx"]

    for ext in extensions:
        candidate = candidate_base + ext
        if candidate in repo_files:
            return candidate

    for idx in index_files:
        candidate = f"{candidate_base}/{idx}"
        if candidate in repo_files:
            return candidate

    return None


def build_reference_graph(
    repo_id: str,
    ast_results: Dict[str, ASTResult],
    repo_files: Set[str],
) -> int:
    """Build cross-file reference edges from parsed AST results.

    Processes import statements and call sites from each file's AST
    to create typed edges in the ``repo_references`` table.

    Args:
        repo_id:     Repository UUID.
        ast_results: Mapping of file_path -> ASTResult from parsing.
        repo_files:  Set of all known file paths in the repository.

    Returns:
        Total number of edges inserted.
    """
    all_edges: List[Dict[str, Any]] = []

    for source_file, ast_result in ast_results.items():
        if not ast_result.parsed:
            continue

        for imp in ast_result.imports:
            target = _normalize_import_to_file(
                imp.module, source_file, repo_files,
            )
            if target and target != source_file:
                for sym in (imp.symbols or [""]):
                    all_edges.append({
                        "source_file": source_file,
                        "target_file": target,
                        "reference_type": "import",
                        "source_symbol": sym or None,
                        "target_symbol": None,
                        "line_number": imp.start_line,
                    })

        for cs in ast_result.call_sites:
            if "." in cs.callee:
                parts = cs.callee.rsplit(".", 1)
                module_part = parts[0]
                target = _normalize_import_to_file(
                    module_part, source_file, repo_files,
                )
                if target and target != source_file:
                    all_edges.append({
                        "source_file": source_file,
                        "target_file": target,
                        "reference_type": "call",
                        "source_symbol": cs.caller or None,
                        "target_symbol": parts[1],
                        "line_number": cs.line,
                    })

    if all_edges:
        count = repo_reference_db.upsert_references(repo_id, all_edges)
        logger.info(
            "Reference graph: %d edges for repo %s", count, repo_id,
        )
        return count
    return 0


def query_references(repo_id: str, file_path: str) -> Dict[str, Any]:
    """Query both directions of the reference graph for a file.

    Args:
        repo_id:   Repository UUID.
        file_path: POSIX-normalized file path.

    Returns:
        Dict with ``imported_by`` (files that import this file) and
        ``depends_on`` (files this file imports).
    """
    importers = repo_reference_db.get_importers(repo_id, file_path)
    dependencies = repo_reference_db.get_dependencies(repo_id, file_path)
    return {
        "file": file_path,
        "imported_by": [
            {
                "file": e["source_file"],
                "type": e["reference_type"],
                "symbol": e.get("source_symbol"),
            }
            for e in importers
        ],
        "depends_on": [
            {
                "file": e["target_file"],
                "type": e["reference_type"],
                "symbol": e.get("target_symbol"),
            }
            for e in dependencies
        ],
    }


def build_reference_graph_for_files(
    repo_id: str,
    file_paths: List[str],
    ast_results: Dict[str, ASTResult],
    repo_files: Set[str],
) -> int:
    """Incrementally rebuild reference edges for a subset of files.

    Deletes existing edges for the given source files, then rebuilds
    only those edges. Used for post-agent incremental refresh.

    Args:
        repo_id:     Repository UUID.
        file_paths:  Files to rebuild edges for.
        ast_results: AST parse results for at least the given files.
        repo_files:  Complete set of repo file paths.

    Returns:
        Number of new edges inserted.
    """
    repo_reference_db.delete_for_files(repo_id, file_paths)
    filtered = {fp: ast_results[fp] for fp in file_paths if fp in ast_results}
    return build_reference_graph(repo_id, filtered, repo_files)
