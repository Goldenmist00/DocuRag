"""
test_repo_errors.py
===================
Unit tests for src/utils/repo_errors.py.

Ensures all custom exceptions have the correct inheritance chain
and the expected HTTP status codes.
"""

import pytest

from src.utils.repo_errors import (
    IndexingError,
    MergeConflictError,
    PathTraversalError,
    RepoAlreadyExistsError,
    RepoAnalyzerError,
    RepoCloneError,
    RepoNotFoundError,
    SessionLimitError,
    SessionNotFoundError,
    ToolExecutionError,
    WorktreeError,
)


class TestExceptionHierarchy:
    """All custom exceptions inherit from RepoAnalyzerError."""

    @pytest.mark.parametrize("exc_cls", [
        RepoNotFoundError,
        RepoAlreadyExistsError,
        RepoCloneError,
        IndexingError,
        SessionNotFoundError,
        SessionLimitError,
        WorktreeError,
        MergeConflictError,
        ToolExecutionError,
        PathTraversalError,
    ])
    def test_inherits_from_base(self, exc_cls):
        assert issubclass(exc_cls, RepoAnalyzerError)

    def test_path_traversal_inherits_from_tool_execution(self):
        assert issubclass(PathTraversalError, ToolExecutionError)


class TestStatusCodes:
    """Each exception maps to the correct HTTP status code."""

    _expected = {
        RepoAnalyzerError:      500,
        RepoNotFoundError:      404,
        RepoAlreadyExistsError: 409,
        RepoCloneError:         502,
        IndexingError:          500,
        SessionNotFoundError:   404,
        SessionLimitError:      429,
        WorktreeError:          500,
        MergeConflictError:     409,
        ToolExecutionError:     400,
        PathTraversalError:     403,
    }

    @pytest.mark.parametrize("exc_cls,code", list(_expected.items()),
                             ids=[c.__name__ for c in _expected])
    def test_status_code(self, exc_cls, code):
        assert exc_cls.status_code == code


class TestExceptionsAreRaisable:
    """Exceptions can be raised and caught with a message."""

    def test_raise_with_message(self):
        with pytest.raises(RepoNotFoundError, match="abc"):
            raise RepoNotFoundError("abc")

    def test_catch_as_base(self):
        with pytest.raises(RepoAnalyzerError):
            raise SessionLimitError("too many")
