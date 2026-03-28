"""
repo_processor.py
=================
Service layer for repository file walking and language detection.

Uses ``git ls-files`` as the primary file discovery mechanism so only
git-tracked files are indexed — automatically respecting ``.gitignore``
and excluding virtual environments, ``site-packages``, vendored deps,
and build artifacts.  Falls back to filtered ``os.walk`` when the repo
path is not a valid git repository.
"""

import logging
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from src.config.repo_constants import (
    EXTENSION_TO_LANGUAGE,
    MAX_FILE_SIZE_BYTES,
    SKIP_DIRS,
    SKIP_EXTENSIONS,
)

logger = logging.getLogger(__name__)

VENDORED_PATH_SEGMENTS: frozenset = frozenset({
    "site-packages", "node_modules", "_pytest", "dist-packages",
    ".egg-info", ".eggs", "__pypackages__", ".tox",
    "bower_components", "jspm_packages",
})
"""Path segments that indicate vendored / third-party code."""


def detect_language(file_path: str) -> Optional[str]:
    """Detect the programming language of a file by its extension.

    Args:
        file_path: Relative or absolute file path.

    Returns:
        Language name string, or ``None`` if unknown.
    """
    ext = os.path.splitext(file_path)[1].lower()
    return EXTENSION_TO_LANGUAGE.get(ext)


def _is_vendored_path(rel_path: str) -> bool:
    """Check whether a relative path passes through a vendored directory.

    Args:
        rel_path: Repo-relative path (forward or back slashes).

    Returns:
        ``True`` if any path segment matches ``VENDORED_PATH_SEGMENTS``.
    """
    normalized = rel_path.replace("\\", "/").lower()
    parts = normalized.split("/")
    for part in parts:
        if part in VENDORED_PATH_SEGMENTS:
            return True
        if part.endswith(".egg-info"):
            return True
    return False


def should_skip_file(abs_path: str, rel_path: Optional[str] = None) -> bool:
    """Decide whether a file should be excluded from indexing.

    A file is skipped when:
      - Its extension is in ``SKIP_EXTENSIONS``.
      - Its size exceeds ``MAX_FILE_SIZE_BYTES``.
      - It is not a regular file.
      - Its path passes through a vendored/third-party directory.

    Args:
        abs_path: Absolute path to the file.
        rel_path: Optional repo-relative path for vendored-path check.

    Returns:
        ``True`` if the file should be skipped.
    """
    if not os.path.isfile(abs_path):
        return True

    ext = os.path.splitext(abs_path)[1].lower()
    if ext in SKIP_EXTENSIONS:
        return True

    if rel_path and _is_vendored_path(rel_path):
        return True

    try:
        size = os.path.getsize(abs_path)
        if size > MAX_FILE_SIZE_BYTES:
            return True
    except OSError:
        return True

    return False


def _git_ls_files(repo_path: str) -> Optional[List[str]]:
    """Run ``git ls-files`` to get all tracked files in the repo.

    Args:
        repo_path: Absolute path to the repository root.

    Returns:
        List of repo-relative file paths, or ``None`` if the command
        fails (e.g. not a git repo).
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning("git ls-files failed (rc=%d): %s", result.returncode, result.stderr.strip())
            return None
        raw = result.stdout
        if not raw.strip():
            return []
        files = [f for f in raw.split("\0") if f.strip()]
        return files
    except FileNotFoundError:
        logger.warning("git not found on PATH — falling back to os.walk")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("git ls-files timed out — falling back to os.walk")
        return None
    except Exception as exc:
        logger.warning("git ls-files error: %s — falling back to os.walk", exc)
        return None


def walk_repo(repo_path: str) -> List[Dict[str, object]]:
    """Discover indexable files in a repository.

    Uses ``git ls-files`` as the primary mechanism so only git-tracked
    files are returned — this automatically excludes virtual environments,
    ``site-packages``, build artifacts, and anything in ``.gitignore``.

    Falls back to filtered ``os.walk`` if the path is not a valid git repo
    or ``git`` is not available.

    Args:
        repo_path: Absolute path to the repository root.

    Returns:
        List of dicts with ``path`` (relative), ``abs_path``, ``language``,
        and ``size_bytes`` keys.
    """
    root = Path(repo_path)

    git_files = _git_ls_files(repo_path)
    if git_files is not None:
        return _walk_from_git(root, git_files)

    logger.info("Falling back to os.walk for %s", repo_path)
    return _walk_from_filesystem(root)


def _walk_from_git(root: Path, git_files: List[str]) -> List[Dict[str, object]]:
    """Build the file list from ``git ls-files`` output.

    Applies extension, size, and vendored-path filters on top of the
    git-tracked file list.

    Args:
        root:      Repository root path.
        git_files: Repo-relative paths from ``git ls-files``.

    Returns:
        Filtered list of file metadata dicts.
    """
    results: List[Dict[str, object]] = []

    for rel_path in git_files:
        abs_path = str(root / rel_path)

        if should_skip_file(abs_path, rel_path=rel_path):
            continue

        lang = detect_language(rel_path)
        try:
            size = os.path.getsize(abs_path)
        except OSError:
            continue

        results.append({
            "path": rel_path,
            "abs_path": abs_path,
            "language": lang,
            "size_bytes": size,
        })

    logger.info("Walked %s (git): %d indexable files found", root, len(results))
    return results


def _walk_from_filesystem(root: Path) -> List[Dict[str, object]]:
    """Fallback file discovery using ``os.walk`` with directory filters.

    Args:
        root: Repository root path.

    Returns:
        Filtered list of file metadata dicts.
    """
    results: List[Dict[str, object]] = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        for fname in filenames:
            abs_path = os.path.join(dirpath, fname)
            rel_path = os.path.relpath(abs_path, root)

            if should_skip_file(abs_path, rel_path=rel_path):
                continue

            lang = detect_language(fname)
            size = os.path.getsize(abs_path)

            results.append({
                "path": rel_path,
                "abs_path": abs_path,
                "language": lang,
                "size_bytes": size,
            })

    logger.info("Walked %s (fs): %d indexable files found", root, len(results))
    return results
