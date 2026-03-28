"""
git_service.py
==============
Service layer for core Git operations (clone, pull, file tree, hashing).

Uses GitPython for repository management and the standard library for
file-system operations.  All configurable values are imported from
``src.config.repo_constants``.
"""

import hashlib
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

import git

from src.config.repo_constants import (
    DEFAULT_REPOS_DIR,
    SKIP_DIRS,
    SKIP_EXTENSIONS,
)

logger = logging.getLogger(__name__)


def _repos_root() -> Path:
    """Return the absolute path to the repos storage directory.

    Returns:
        Path object for the repos root.
    """
    return Path(os.getenv("REPOS_DIR", DEFAULT_REPOS_DIR)).resolve()


def _rewrite_url_with_token(remote_url: str, token: str) -> str:
    """Inject a GitHub PAT into an HTTPS clone URL.

    Args:
        remote_url: Original ``https://github.com/...`` URL.
        token:      GitHub personal access token.

    Returns:
        URL with embedded token for authenticated cloning.
    """
    parsed = urlparse(remote_url)
    return f"{parsed.scheme}://{token}@{parsed.netloc}{parsed.path}"


def extract_repo_name(remote_url: str) -> str:
    """Derive a human-readable repo name from its GitHub URL.

    Args:
        remote_url: GitHub HTTPS clone URL.

    Returns:
        Repository name (e.g. ``"my-project"``).
    """
    path = urlparse(remote_url).path.rstrip("/")
    name = path.split("/")[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name


def clone_repo(
    remote_url: str,
    repo_id: str,
    auth_token: Optional[str] = None,
) -> str:
    """Clone a GitHub repository to local disk.

    Args:
        remote_url: HTTPS clone URL.
        repo_id:    UUID used as the local directory name.
        auth_token: Optional PAT for private repos.

    Returns:
        Absolute path to the cloned repository.

    Raises:
        git.GitCommandError: If the clone operation fails.
    """
    dest = _repos_root() / repo_id
    dest.mkdir(parents=True, exist_ok=True)

    url = (
        _rewrite_url_with_token(remote_url, auth_token)
        if auth_token
        else remote_url
    )

    logger.info("Cloning %s -> %s", remote_url, dest)
    git.Repo.clone_from(url, str(dest))
    logger.info("Clone complete: %s", dest)
    return str(dest)


def pull_latest(repo_path: str, branch: Optional[str] = None) -> None:
    """Fetch and pull the latest changes from origin.

    Args:
        repo_path: Absolute path to the local repo.
        branch:    Branch to pull (defaults to the repo's active branch).

    Raises:
        git.GitCommandError: On network or merge errors.
    """
    repo = git.Repo(repo_path)
    target = branch or repo.active_branch.name
    logger.info("Pulling latest on %s (branch=%s)", repo_path, target)
    repo.remotes.origin.pull(target)


def list_branches(repo_path: str) -> List[str]:
    """Return the names of all local branches.

    Args:
        repo_path: Absolute path to the local repo.

    Returns:
        List of branch name strings.
    """
    repo = git.Repo(repo_path)
    return [b.name for b in repo.branches]


def get_current_commit(repo_path: str) -> str:
    """Return the full SHA of HEAD.

    Args:
        repo_path: Absolute path to the local repo.

    Returns:
        40-character hex SHA string.
    """
    repo = git.Repo(repo_path)
    return repo.head.commit.hexsha


def get_file_tree(repo_path: str) -> List[Dict[str, str]]:
    """Walk the repository and return all indexable files.

    Skips directories in ``SKIP_DIRS`` and files with extensions in
    ``SKIP_EXTENSIONS``.

    Args:
        repo_path: Absolute path to the local repo.

    Returns:
        List of dicts with ``path`` (relative) and ``abs_path`` keys.
    """
    root = Path(repo_path)
    results: List[Dict[str, str]] = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames if d not in SKIP_DIRS
        ]
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext in SKIP_EXTENSIONS:
                continue
            abs_path = os.path.join(dirpath, fname)
            rel_path = os.path.relpath(abs_path, root)
            results.append({"path": rel_path, "abs_path": abs_path})

    return results


def compute_file_hash(file_path: str) -> str:
    """Compute the SHA-256 hash of a file's contents.

    Args:
        file_path: Absolute path to the file.

    Returns:
        Hex-encoded SHA-256 digest.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
