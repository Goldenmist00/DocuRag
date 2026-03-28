"""
repo_file_service.py
====================
Service for reading raw file content from locally cloned repositories.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from src.db import repo_db
from src.utils.repo_errors import PathTraversalError, RepoNotFoundError

logger = logging.getLogger(__name__)

MAX_CONTENT_BYTES = 2 * 1024 * 1024


def read_file_content(repo_id: str, file_path: str) -> dict:
    """Read raw content of a single file from the local clone.

    Args:
        repo_id:   Repository UUID.
        file_path: Repo-relative path (forward-slash separated).

    Returns:
        Dict with ``path``, ``content``, ``size_bytes``, and ``truncated``.

    Raises:
        RepoNotFoundError: If the repo row doesn't exist.
        PathTraversalError: If the resolved path escapes the clone directory.
        FileNotFoundError: If the file doesn't exist on disk.
    """
    row = repo_db.find_by_id(repo_id)
    if row is None:
        raise RepoNotFoundError(f"Repository not found: {repo_id}")

    local_root = Path(row["local_path"]).resolve()
    sanitized = file_path.replace("\\", "/").lstrip("/")
    target = (local_root / sanitized).resolve()

    if not str(target).startswith(str(local_root)):
        raise PathTraversalError(f"Path escapes repository root: {file_path}")

    if not target.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    size = target.stat().st_size
    truncated = size > MAX_CONTENT_BYTES

    content = target.read_bytes()[:MAX_CONTENT_BYTES].decode(
        "utf-8", errors="replace"
    )

    return {
        "path": sanitized,
        "content": content,
        "size_bytes": size,
        "truncated": truncated,
    }
