"""
repo_errors.py
==============
Custom exceptions for the repo analyzer feature.

Each exception carries an ``status_code`` attribute that the controller
layer maps to the appropriate HTTP response code.  All exceptions
inherit from :class:`RepoAnalyzerError` so callers can use a single
``except RepoAnalyzerError`` when they want a catch-all.
"""


class RepoAnalyzerError(Exception):
    """Base exception for all repo-analyzer errors.

    Attributes:
        status_code: HTTP status code the controller should return.
    """

    status_code: int = 500


class RepoNotFoundError(RepoAnalyzerError):
    """Repo does not exist in the database."""

    status_code = 404


class RepoAlreadyExistsError(RepoAnalyzerError):
    """A repo with this remote_url is already registered."""

    status_code = 409


class RepoCloneError(RepoAnalyzerError):
    """Git clone operation failed (network, auth, or disk error)."""

    status_code = 502


class IndexingError(RepoAnalyzerError):
    """File ingestion or consolidation failed."""

    status_code = 500


class SessionNotFoundError(RepoAnalyzerError):
    """Agent session does not exist."""

    status_code = 404


class SessionLimitError(RepoAnalyzerError):
    """Maximum concurrent sessions reached for this repository."""

    status_code = 429


class WorktreeError(RepoAnalyzerError):
    """Git worktree operation (create / remove / merge) failed."""

    status_code = 500


class MergeConflictError(RepoAnalyzerError):
    """Merge produced conflicts that require manual resolution."""

    status_code = 409


class ToolExecutionError(RepoAnalyzerError):
    """Agent tool call failed (path violation, timeout, blocked command)."""

    status_code = 400


class PathTraversalError(ToolExecutionError):
    """File path attempted to escape the worktree sandbox."""

    status_code = 403
