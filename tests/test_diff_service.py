"""
test_diff_service.py
====================
Unit tests for src/git/diff_service.py.
"""

from src.git.diff_service import DiffStats, parse_diff


SAMPLE_DIFF = """diff --git a/src/main.py b/src/main.py
index 1234567..abcdefg 100644
--- a/src/main.py
+++ b/src/main.py
@@ -1,3 +1,5 @@
+import os
+
 def main():
-    print("old")
+    print("new")
     pass
diff --git a/README.md b/README.md
new file mode 100644
--- /dev/null
+++ b/README.md
@@ -0,0 +1,2 @@
+# My Project
+Description here
"""


class TestParseDiff:
    """Parse unified diff into structured objects."""

    def test_parses_two_files(self):
        files = parse_diff(SAMPLE_DIFF)
        assert len(files) == 2

    def test_first_file_is_modified(self):
        files = parse_diff(SAMPLE_DIFF)
        assert files[0].path == "src/main.py"
        assert files[0].status == "modified"

    def test_second_file_is_added(self):
        files = parse_diff(SAMPLE_DIFF)
        assert files[1].path == "README.md"
        assert files[1].status == "added"

    def test_hunks_contain_changes(self):
        files = parse_diff(SAMPLE_DIFF)
        main_py = files[0]
        assert len(main_py.hunks) >= 1
        hunk = main_py.hunks[0]
        assert any("import os" in line for line in hunk.added_lines)
        assert any("old" in line for line in hunk.removed_lines)

    def test_empty_diff(self):
        assert parse_diff("") == []
