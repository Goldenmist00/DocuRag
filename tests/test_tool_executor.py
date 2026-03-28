"""
test_tool_executor.py
=====================
Unit tests for src/agents/tool_executor.py.

Covers tool execution, path safety, and command blocking.
"""

import os
import tempfile

import pytest

from src.agents.tool_executor import ToolExecutor, ToolResult


@pytest.fixture
def worktree():
    """Create a temporary worktree directory with sample files."""
    with tempfile.TemporaryDirectory() as root:
        os.makedirs(os.path.join(root, "src"))
        with open(os.path.join(root, "src", "main.py"), "w") as f:
            f.write("def hello():\n    return 'world'\n")
        with open(os.path.join(root, "README.md"), "w") as f:
            f.write("# Test Project\n")
        yield root


class TestReadFile:
    """read_file tool execution."""

    def test_read_existing_file(self, worktree):
        executor = ToolExecutor(worktree)
        result = executor.execute("read_file", {"path": "src/main.py"})
        assert result.success is True
        assert "hello" in result.output

    def test_read_missing_file(self, worktree):
        executor = ToolExecutor(worktree)
        result = executor.execute("read_file", {"path": "nonexistent.py"})
        assert result.success is False


class TestWriteFile:
    """write_file tool execution."""

    def test_write_new_file(self, worktree):
        executor = ToolExecutor(worktree)
        result = executor.execute("write_file", {
            "path": "new_file.py",
            "content": "x = 1\n",
        })
        assert result.success is True
        assert os.path.exists(os.path.join(worktree, "new_file.py"))

    def test_block_sensitive_file(self, worktree):
        executor = ToolExecutor(worktree)
        result = executor.execute("write_file", {
            "path": ".env",
            "content": "SECRET=123",
        })
        assert result.success is False


class TestEditFile:
    """edit_file tool execution."""

    def test_successful_edit(self, worktree):
        executor = ToolExecutor(worktree)
        result = executor.execute("edit_file", {
            "path": "src/main.py",
            "old_text": "return 'world'",
            "new_text": "return 'earth'",
        })
        assert result.success is True
        with open(os.path.join(worktree, "src", "main.py")) as f:
            assert "earth" in f.read()

    def test_edit_not_found(self, worktree):
        executor = ToolExecutor(worktree)
        result = executor.execute("edit_file", {
            "path": "src/main.py",
            "old_text": "NONEXISTENT TEXT",
            "new_text": "replacement",
        })
        assert result.success is False


class TestListDirectory:
    """list_directory tool execution."""

    def test_list_root(self, worktree):
        executor = ToolExecutor(worktree)
        result = executor.execute("list_directory", {"path": "."})
        assert result.success is True
        assert "src" in result.output
        assert "README.md" in result.output


class TestRunCommand:
    """run_command tool execution."""

    def test_safe_command(self, worktree):
        executor = ToolExecutor(worktree)
        result = executor.execute("run_command", {"command": "echo hello"})
        assert result.success is True
        assert "hello" in result.output

    def test_blocked_sudo(self, worktree):
        executor = ToolExecutor(worktree)
        result = executor.execute("run_command", {"command": "sudo rm -rf /"})
        assert result.success is False


class TestPathTraversal:
    """Sandbox escape prevention."""

    def test_dotdot_blocked_on_read(self, worktree):
        executor = ToolExecutor(worktree)
        result = executor.execute("read_file", {"path": "../../etc/passwd"})
        assert result.success is False

    def test_dotgit_blocked_on_write(self, worktree):
        executor = ToolExecutor(worktree)
        result = executor.execute("write_file", {
            "path": ".git/config",
            "content": "bad",
        })
        assert result.success is False


class TestDoneTool:
    """done tool execution."""

    def test_done_returns_summary(self, worktree):
        executor = ToolExecutor(worktree)
        result = executor.execute("done", {"summary": "All changes made"})
        assert result.success is True
        assert "All changes made" in result.output
