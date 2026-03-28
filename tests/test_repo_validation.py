"""
test_repo_validation.py
=======================
Unit tests for src/utils/repo_validation.py.

Covers happy-path and error cases for every public function.
"""

import os
import tempfile

import pytest

from src.utils.repo_validation import (
    is_blocked_command,
    is_sensitive_file,
    sanitize_file_path,
    validate_github_url,
    validate_repo_id,
    validate_session_id,
    validate_uuid,
)


# ── validate_github_url ─────────────────────────────────────────────────

class TestValidateGithubUrl:
    """Positive and negative cases for GitHub URL validation."""

    @pytest.mark.parametrize("url", [
        "https://github.com/user/repo",
        "https://github.com/user/repo.git",
        "https://github.com/user/repo/",
        "https://github.com/org-name/my-repo.git",
        "http://github.com/user/repo",
    ])
    def test_valid_urls(self, url):
        assert validate_github_url(url) is True

    @pytest.mark.parametrize("url", [
        "",
        "not-a-url",
        "https://gitlab.com/user/repo",
        "git@github.com:user/repo.git",
        "https://github.com/",
        "https://github.com/user",
        None,
    ])
    def test_invalid_urls(self, url):
        assert validate_github_url(url) is False


# ── validate_uuid / validate_repo_id / validate_session_id ──────────────

class TestValidateUuid:
    """UUID validation helpers."""

    def test_valid_uuid4(self):
        validate_uuid("550e8400-e29b-41d4-a716-446655440000")

    def test_invalid_uuid_raises(self):
        with pytest.raises(ValueError, match="Invalid ID"):
            validate_uuid("not-a-uuid")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            validate_uuid("")

    def test_validate_repo_id_delegates(self):
        with pytest.raises(ValueError, match="repo_id"):
            validate_repo_id("bad")

    def test_validate_session_id_delegates(self):
        with pytest.raises(ValueError, match="session_id"):
            validate_session_id("bad")

    def test_valid_repo_id_passes(self):
        validate_repo_id("550e8400-e29b-41d4-a716-446655440000")


# ── sanitize_file_path ──────────────────────────────────────────────────

class TestSanitizeFilePath:
    """Path-safety validation inside a worktree root."""

    def test_simple_relative_path(self):
        with tempfile.TemporaryDirectory() as root:
            result = sanitize_file_path("src/main.py", root)
            assert os.path.isabs(result)
            assert result.endswith("main.py")

    def test_traversal_blocked(self):
        with tempfile.TemporaryDirectory() as root:
            with pytest.raises(ValueError, match="traversal"):
                sanitize_file_path("../../etc/passwd", root)

    def test_dotgit_write_blocked(self):
        with tempfile.TemporaryDirectory() as root:
            with pytest.raises(ValueError, match=".git"):
                sanitize_file_path(".git/config", root)

    def test_nested_path_inside_root_ok(self):
        with tempfile.TemporaryDirectory() as root:
            result = sanitize_file_path("a/b/c/d.txt", root)
            assert result.endswith(os.path.join("a", "b", "c", "d.txt"))


# ── is_blocked_command ──────────────────────────────────────────────────

class TestIsBlockedCommand:
    """Command-safety validation."""

    def test_empty_string_not_blocked(self):
        assert is_blocked_command("") is False

    def test_sudo_is_blocked(self):
        assert is_blocked_command("sudo apt install curl") is True

    def test_destructive_command_blocked(self):
        assert is_blocked_command("rm -rf /") is True
        assert is_blocked_command("shutdown") is True

    def test_safe_command_not_blocked(self):
        assert is_blocked_command("ls -la") is False
        assert is_blocked_command("python --version") is False

    def test_case_insensitive(self):
        assert is_blocked_command("SUDO rm -rf /tmp") is True


# ── is_sensitive_file ───────────────────────────────────────────────────

class TestIsSensitiveFile:
    """Sensitive-file detection."""

    def test_env_file_is_sensitive(self):
        assert is_sensitive_file(".env") is True
        assert is_sensitive_file(".env.local") is True

    def test_pem_file_is_sensitive(self):
        assert is_sensitive_file("server.pem") is True

    def test_key_file_is_sensitive(self):
        assert is_sensitive_file("private.key") is True

    def test_regular_file_not_sensitive(self):
        assert is_sensitive_file("main.py") is False
        assert is_sensitive_file("README.md") is False

    def test_empty_not_sensitive(self):
        assert is_sensitive_file("") is False

    def test_credentials_file_is_sensitive(self):
        assert is_sensitive_file("credentials.json") is True
