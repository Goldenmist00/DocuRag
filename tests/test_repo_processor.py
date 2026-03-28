"""
test_repo_processor.py
======================
Unit tests for src/repo/repo_processor.py.
"""

import os
import tempfile

import pytest

from src.repo.repo_processor import detect_language, should_skip_file, walk_repo


class TestDetectLanguage:
    """File extension to language mapping."""

    def test_python_file(self):
        assert detect_language("main.py") == "Python"

    def test_typescript_file(self):
        assert detect_language("app.tsx") == "TypeScript"

    def test_unknown_extension(self):
        assert detect_language("data.xyz") is None

    def test_case_insensitive_extension(self):
        assert detect_language("script.PY") == "Python"


class TestShouldSkipFile:
    """File filtering logic."""

    def test_binary_extension_skipped(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            path = f.name
        try:
            assert should_skip_file(path) is True
        finally:
            os.unlink(path)

    def test_normal_py_not_skipped(self):
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write("x = 1")
            path = f.name
        try:
            assert should_skip_file(path) is False
        finally:
            os.unlink(path)

    def test_nonexistent_file_skipped(self):
        assert should_skip_file("/nonexistent/path.py") is True


class TestWalkRepo:
    """Repository file walking."""

    def test_discovers_py_files(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "src"))
            with open(os.path.join(root, "src", "app.py"), "w") as f:
                f.write("pass")
            with open(os.path.join(root, "README.md"), "w") as f:
                f.write("# Hi")

            results = walk_repo(root)
            paths = [r["path"] for r in results]
            assert any("app.py" in p for p in paths)
            assert any("README.md" in p for p in paths)

    def test_skips_node_modules(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "node_modules", "pkg"))
            with open(os.path.join(root, "node_modules", "pkg", "index.js"), "w") as f:
                f.write("module.exports = {}")
            with open(os.path.join(root, "index.js"), "w") as f:
                f.write("console.log('hi')")

            results = walk_repo(root)
            paths = [r["path"] for r in results]
            assert not any("node_modules" in p for p in paths)
            assert any("index.js" in p for p in paths)

    def test_returns_language_and_size(self):
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "app.ts"), "w") as f:
                f.write("const x = 1;")

            results = walk_repo(root)
            assert len(results) >= 1
            item = results[0]
            assert item["language"] == "TypeScript"
            assert item["size_bytes"] > 0
