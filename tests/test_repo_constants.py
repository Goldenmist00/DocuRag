"""
test_repo_constants.py
======================
Unit tests for src/config/repo_constants.py.

Verifies that all constants are present, correctly typed, and hold
sensible values.
"""

import pytest

from src.config.repo_constants import (
    BLOCKED_COMMANDS,
    CONSOLIDATION_BATCH_SIZE,
    CONTEXT_COMPACTION_THRESHOLD,
    DEFAULT_REPOS_DIR,
    EXTENSION_TO_LANGUAGE,
    LLM_SEMAPHORE_LIMIT,
    MAX_AGENT_TURNS,
    MAX_CONCURRENT_INGEST_WORKERS,
    MAX_CONCURRENT_SESSIONS,
    MAX_FILE_SIZE_BYTES,
    MAX_TOOL_OUTPUT_BYTES,
    MIN_MEMORIES_FOR_QUERY_MATCH,
    SENSITIVE_FILE_PATTERNS,
    SKIP_DIRS,
    SKIP_EXTENSIONS,
    TOOL_TIMEOUT_SECONDS,
    WORKTREES_DIR_SUFFIX,
)


class TestFileFilteringConstants:
    """SKIP_DIRS, SKIP_EXTENSIONS, SENSITIVE_FILE_PATTERNS."""

    def test_skip_dirs_is_frozenset(self):
        assert isinstance(SKIP_DIRS, frozenset)

    def test_skip_dirs_contains_common_entries(self):
        for d in (".git", "node_modules", "__pycache__", ".venv"):
            assert d in SKIP_DIRS

    def test_skip_extensions_is_frozenset(self):
        assert isinstance(SKIP_EXTENSIONS, frozenset)

    def test_skip_extensions_contains_binary_types(self):
        for ext in (".pyc", ".exe", ".png", ".zip"):
            assert ext in SKIP_EXTENSIONS

    def test_sensitive_file_patterns_is_frozenset(self):
        assert isinstance(SENSITIVE_FILE_PATTERNS, frozenset)

    def test_sensitive_patterns_cover_env_and_keys(self):
        assert ".env" in SENSITIVE_FILE_PATTERNS
        assert ".pem" in SENSITIVE_FILE_PATTERNS
        assert ".key" in SENSITIVE_FILE_PATTERNS


class TestNumericLimits:
    """Numeric constants have correct types and sensible ranges."""

    def test_max_file_size_is_positive_int(self):
        assert isinstance(MAX_FILE_SIZE_BYTES, int)
        assert MAX_FILE_SIZE_BYTES > 0

    def test_concurrency_limits_positive(self):
        assert MAX_CONCURRENT_INGEST_WORKERS >= 1
        assert MAX_CONCURRENT_SESSIONS >= 1
        assert LLM_SEMAPHORE_LIMIT >= 1

    def test_agent_limits_positive(self):
        assert MAX_AGENT_TURNS >= 1
        assert TOOL_TIMEOUT_SECONDS >= 1
        assert MAX_TOOL_OUTPUT_BYTES >= 1

    def test_consolidation_batch_size_positive(self):
        assert CONSOLIDATION_BATCH_SIZE >= 1

    def test_min_memories_positive(self):
        assert MIN_MEMORIES_FOR_QUERY_MATCH >= 1

    def test_compaction_threshold_in_range(self):
        assert 0.0 < CONTEXT_COMPACTION_THRESHOLD < 1.0


class TestBlockedCommands:
    """BLOCKED_COMMANDS set."""

    def test_is_frozenset(self):
        assert isinstance(BLOCKED_COMMANDS, frozenset)

    def test_contains_destructive_entries(self):
        assert "rm -rf /" in BLOCKED_COMMANDS
        assert "shutdown" in BLOCKED_COMMANDS


class TestLanguageMap:
    """EXTENSION_TO_LANGUAGE mapping."""

    def test_is_dict(self):
        assert isinstance(EXTENSION_TO_LANGUAGE, dict)

    def test_common_extensions_present(self):
        assert EXTENSION_TO_LANGUAGE[".py"] == "Python"
        assert EXTENSION_TO_LANGUAGE[".ts"] == "TypeScript"
        assert EXTENSION_TO_LANGUAGE[".js"] == "JavaScript"

    def test_all_keys_start_with_dot(self):
        for key in EXTENSION_TO_LANGUAGE:
            assert key.startswith("."), f"{key} does not start with '.'"


class TestStorageDefaults:
    """DEFAULT_REPOS_DIR, WORKTREES_DIR_SUFFIX."""

    def test_repos_dir_is_string(self):
        assert isinstance(DEFAULT_REPOS_DIR, str)
        assert len(DEFAULT_REPOS_DIR) > 0

    def test_worktrees_suffix_is_string(self):
        assert isinstance(WORKTREES_DIR_SUFFIX, str)
        assert len(WORKTREES_DIR_SUFFIX) > 0
