"""
repo_validation.py
==================
Shared validation helpers for the repo analyzer feature.

Every function is stateless, side-effect free, and raises a clear
exception on invalid input.  Used across controllers, services, and
the tool executor to avoid duplicating validation logic.
"""

import logging
import os
import re
import uuid
from pathlib import Path

from src.config.repo_constants import BLOCKED_COMMANDS, SENSITIVE_FILE_PATTERNS

logger = logging.getLogger(__name__)

_GITHUB_URL_RE = re.compile(
    r"^https?://github\.com/[\w.\-]+/[\w.\-]+(\.git)?/?$",
    re.IGNORECASE,
)


def validate_github_url(url: str) -> bool:
    """Check whether *url* looks like a valid GitHub HTTPS repository URL.

    Args:
        url: The URL string to validate.

    Returns:
        ``True`` if valid, ``False`` otherwise.
    """
    if not url or not isinstance(url, str):
        return False
    return bool(_GITHUB_URL_RE.match(url.strip()))


def validate_uuid(value: str, label: str = "ID") -> None:
    """Raise ``ValueError`` if *value* is not a valid UUID-4 string.

    Args:
        value: The string to check.
        label: Human-readable field name for the error message.

    Raises:
        ValueError: When *value* cannot be parsed as a UUID.
    """
    try:
        uuid.UUID(str(value), version=4)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid {label}: {value!r}") from exc


def validate_repo_id(repo_id: str) -> None:
    """Validate that *repo_id* is a well-formed UUID.

    Args:
        repo_id: Repository identifier.

    Raises:
        ValueError: If the string is not a valid UUID-4.
    """
    validate_uuid(repo_id, label="repo_id")


def validate_session_id(session_id: str) -> None:
    """Validate that *session_id* is a well-formed UUID.

    Args:
        session_id: Agent session identifier.

    Raises:
        ValueError: If the string is not a valid UUID-4.
    """
    validate_uuid(session_id, label="session_id")


def sanitize_file_path(path: str, worktree_root: str) -> str:
    """Resolve *path* relative to *worktree_root* and ensure it stays inside.

    Args:
        path:           Relative or absolute file path requested by the agent.
        worktree_root:  Absolute path to the worktree directory.

    Returns:
        The resolved absolute path as a string.

    Raises:
        ValueError: If the resolved path escapes the worktree root or
                    targets the ``.git`` directory.
    """
    root = Path(worktree_root).resolve()
    resolved = (root / path).resolve()

    if not str(resolved).startswith(str(root)):
        raise ValueError(
            f"Path traversal blocked: {path!r} resolves outside worktree"
        )

    rel = resolved.relative_to(root)
    if rel.parts and rel.parts[0] == ".git":
        raise ValueError(
            f"Writes to .git directory are forbidden: {path!r}"
        )

    return str(resolved)


def is_blocked_command(command: str) -> bool:
    """Return ``True`` if *command* matches the block list or contains sudo.

    Args:
        command: Shell command string.

    Returns:
        ``True`` when the command must not be executed.
    """
    if not command:
        return False
    cmd_lower = command.strip().lower()
    if "sudo" in cmd_lower.split():
        return True
    return any(blocked in cmd_lower for blocked in BLOCKED_COMMANDS)


def is_sensitive_file(filename: str) -> bool:
    """Return ``True`` if *filename* matches a sensitive-file pattern.

    Args:
        filename: Basename or relative path to check.

    Returns:
        ``True`` when the file should be protected from agent writes.
    """
    if not filename:
        return False
    name_lower = os.path.basename(filename).lower()
    return any(pattern in name_lower for pattern in SENSITIVE_FILE_PATTERNS)
