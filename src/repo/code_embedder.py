"""
code_embedder.py
================
Split source files into function-level chunks using Tree-sitter AST,
embed them with the existing ``Embedder`` (bge-m3, 1024d), and store
in ``repo_code_chunks`` (pgvector) for semantic code search.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from src.db import repo_code_chunk_db
from src.repo.ast_parser import ASTResult, parse_file

logger = logging.getLogger(__name__)

SLIDING_WINDOW_LINES = 100
SLIDING_WINDOW_OVERLAP = 20
MAX_CHUNK_CHARS = 6000


def _ast_to_chunks(
    file_path: str,
    content: str,
    ast_result: ASTResult,
    file_hash: str,
) -> List[Dict[str, Any]]:
    """Split a file into chunks using AST function/class boundaries.

    Each function or class body becomes its own chunk. Falls back to
    sliding-window chunking when AST parsing is unavailable.

    Args:
        file_path:  POSIX-normalized repo-relative path.
        content:    Full file text.
        ast_result: Parsed AST (may have ``parsed=False``).
        file_hash:  SHA-256 hex digest of the file.

    Returns:
        List of chunk dicts ready for embedding and storage.
    """
    chunks: List[Dict[str, Any]] = []

    if ast_result.parsed and (ast_result.functions or ast_result.classes):
        for func in ast_result.functions:
            body = func.body_text or ""
            if not body.strip():
                continue
            if len(body) > MAX_CHUNK_CHARS:
                body = body[:MAX_CHUNK_CHARS]
            header = f"# {file_path}::{func.name}\n"
            chunks.append({
                "file_path": file_path,
                "symbol_name": func.name,
                "chunk_type": "function",
                "start_line": func.start_line,
                "end_line": func.end_line,
                "content": header + body,
                "file_hash": file_hash,
            })

        for cls in ast_result.classes:
            lines = content.splitlines()
            start = max(0, cls.start_line - 1)
            end = min(len(lines), cls.end_line)
            body = "\n".join(lines[start:end])
            if len(body) > MAX_CHUNK_CHARS:
                body = body[:MAX_CHUNK_CHARS]
            header = f"# {file_path}::{cls.name}\n"
            chunks.append({
                "file_path": file_path,
                "symbol_name": cls.name,
                "chunk_type": "class",
                "start_line": cls.start_line,
                "end_line": cls.end_line,
                "content": header + body,
                "file_hash": file_hash,
            })
    else:
        chunks.extend(
            _sliding_window_chunks(file_path, content, file_hash)
        )

    return chunks


def _sliding_window_chunks(
    file_path: str,
    content: str,
    file_hash: str,
) -> List[Dict[str, Any]]:
    """Create overlapping line-based chunks for files without AST support.

    Args:
        file_path: Repo-relative path.
        content:   Full file text.
        file_hash: File hash for deduplication.

    Returns:
        List of chunk dicts.
    """
    lines = content.splitlines()
    chunks: List[Dict[str, Any]] = []
    step = SLIDING_WINDOW_LINES - SLIDING_WINDOW_OVERLAP

    for start in range(0, len(lines), step):
        end = min(start + SLIDING_WINDOW_LINES, len(lines))
        block = "\n".join(lines[start:end])
        if not block.strip():
            continue
        if len(block) > MAX_CHUNK_CHARS:
            block = block[:MAX_CHUNK_CHARS]
        header = f"# {file_path} lines {start + 1}-{end}\n"
        chunks.append({
            "file_path": file_path,
            "symbol_name": None,
            "chunk_type": "block",
            "start_line": start + 1,
            "end_line": end,
            "content": header + block,
            "file_hash": file_hash,
        })
        if end >= len(lines):
            break

    return chunks


def embed_repo_code(
    repo_id: str,
    repo_path: str,
    ast_results: Dict[str, ASTResult],
    file_contents: Dict[str, str],
    file_hashes: Dict[str, str],
) -> int:
    """Embed files into code chunks, skipping unchanged files.

    Checks existing chunk hashes in the database and only re-processes
    files whose hash has changed. Unchanged files keep their existing
    chunks and embeddings.

    Args:
        repo_id:       Repository UUID.
        repo_path:     Absolute path to the repo root.
        ast_results:   Map of file_path -> ASTResult.
        file_contents: Map of file_path -> file text content.
        file_hashes:   Map of file_path -> SHA-256 hash.

    Returns:
        Number of new chunks embedded and stored.
    """
    existing_hashes = repo_code_chunk_db.get_file_hashes(repo_id)

    changed_files = []
    for fp in file_contents:
        new_hash = file_hashes.get(fp, "")
        old_hash = existing_hashes.get(fp, "")
        if new_hash != old_hash:
            changed_files.append(fp)

    if changed_files:
        repo_code_chunk_db.delete_for_files(repo_id, changed_files)

    stale_files = [fp for fp in existing_hashes if fp not in file_contents]
    if stale_files:
        repo_code_chunk_db.delete_for_files(repo_id, stale_files)

    skipped = len(file_contents) - len(changed_files)
    if skipped > 0:
        logger.info("Embedding: skipped %d unchanged files", skipped)

    all_chunks: List[Dict[str, Any]] = []
    for fp in changed_files:
        content = file_contents[fp]
        ast = ast_results.get(fp, ASTResult())
        fh = file_hashes.get(fp, "")
        chunks = _ast_to_chunks(fp, content, ast, fh)
        all_chunks.extend(chunks)

    if not all_chunks:
        logger.info("No code chunks to embed for repo %s", repo_id)
        return 0

    logger.info("Embedding %d code chunks for repo %s", len(all_chunks), repo_id)

    try:
        from src.embedder import get_embedder
        embedder = get_embedder()
    except (ValueError, RuntimeError) as exc:
        logger.warning("Embedder init failed, storing chunks without embeddings: %s", exc)
        repo_code_chunk_db.insert_chunks(repo_id, all_chunks)
        return len(all_chunks)

    texts = [c["content"] for c in all_chunks]
    embeddings = embedder.embed_batch(texts, show_progress=False)

    for i, chunk in enumerate(all_chunks):
        chunk["embedding"] = embeddings[i].tolist()

    repo_code_chunk_db.insert_chunks(repo_id, all_chunks)
    logger.info("Stored %d embedded code chunks for repo %s", len(all_chunks), repo_id)
    return len(all_chunks)


def re_embed_files(
    repo_id: str,
    file_paths: List[str],
    file_contents: Dict[str, str],
    file_hashes: Dict[str, str],
    ast_results: Dict[str, ASTResult],
) -> int:
    """Incrementally re-embed only changed files.

    Deletes old chunks for the specified files, re-generates chunks
    from current content and AST, embeds, and stores.

    Args:
        repo_id:       Repository UUID.
        file_paths:    Files that changed.
        file_contents: Current content of those files.
        file_hashes:   Current hashes of those files.
        ast_results:   Current AST parse results.

    Returns:
        Number of new chunks embedded and stored.
    """
    repo_code_chunk_db.delete_for_files(repo_id, file_paths)

    all_chunks: List[Dict[str, Any]] = []
    for fp in file_paths:
        content = file_contents.get(fp, "")
        if not content:
            continue
        ast = ast_results.get(fp, ASTResult())
        fh = file_hashes.get(fp, "")
        chunks = _ast_to_chunks(fp, content, ast, fh)
        all_chunks.extend(chunks)

    if not all_chunks:
        return 0

    try:
        from src.embedder import get_embedder
        embedder = get_embedder()
        texts = [c["content"] for c in all_chunks]
        embeddings = embedder.embed_batch(texts, show_progress=False)
        for i, chunk in enumerate(all_chunks):
            chunk["embedding"] = embeddings[i].tolist()
    except (ValueError, RuntimeError) as exc:
        logger.warning("Embedder failed during re-embed: %s", exc)

    repo_code_chunk_db.insert_chunks(repo_id, all_chunks)
    return len(all_chunks)
