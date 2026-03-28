"""
test_git_service.py
===================
Unit tests for src/git/git_service.py.
"""

import os
import tempfile

import pytest

from src.git.git_service import (
    compute_file_hash,
    extract_repo_name,
    get_file_tree,
)


class TestExtractRepoName:
    """Derive repo name from GitHub URLs."""

    def test_simple_url(self):
        assert extract_repo_name("https://github.com/user/my-project") == "my-project"

    def test_url_with_dot_git(self):
        assert extract_repo_name("https://github.com/user/repo.git") == "repo"

    def test_url_with_trailing_slash(self):
        assert extract_repo_name("https://github.com/org/tool/") == "tool"


class TestComputeFileHash:
    """SHA-256 hashing of file contents."""

    def test_hash_deterministic(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("hello world")
            f.flush()
            path = f.name

        try:
            h1 = compute_file_hash(path)
            h2 = compute_file_hash(path)
            assert h1 == h2
            assert len(h1) == 64
        finally:
            os.unlink(path)

    def test_different_content_different_hash(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f1:
            f1.write("aaa")
            f1.flush()
            p1 = f1.name
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f2:
            f2.write("bbb")
            f2.flush()
            p2 = f2.name
        try:
            assert compute_file_hash(p1) != compute_file_hash(p2)
        finally:
            os.unlink(p1)
            os.unlink(p2)

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            compute_file_hash("/nonexistent/path/file.txt")


class TestGetFileTree:
    """File tree walk with filtering."""

    def test_skips_pycache(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "__pycache__"))
            with open(os.path.join(root, "__pycache__", "mod.pyc"), "w") as f:
                f.write("")
            with open(os.path.join(root, "main.py"), "w") as f:
                f.write("pass")

            files = get_file_tree(root)
            paths = [f["path"] for f in files]
            assert any("main.py" in p for p in paths)
            assert not any("__pycache__" in p for p in paths)

    def test_skips_binary_extensions(self):
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "image.png"), "w") as f:
                f.write("")
            with open(os.path.join(root, "code.py"), "w") as f:
                f.write("pass")

            files = get_file_tree(root)
            paths = [f["path"] for f in files]
            assert any("code.py" in p for p in paths)
            assert not any("image.png" in p for p in paths)
