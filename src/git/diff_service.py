"""
diff_service.py
===============
Service layer for parsing Git diffs and detecting conflicts.

Provides structured diff objects from raw unified-diff text and
utilities for conflict detection between branches.
"""

import logging
import subprocess
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class DiffHunk:
    """A single hunk within a file diff.

    Attributes:
        header:       Hunk header line (e.g. ``@@ -1,5 +1,7 @@``).
        added_lines:  Lines added in this hunk.
        removed_lines: Lines removed in this hunk.
    """

    header: str = ""
    added_lines: List[str] = field(default_factory=list)
    removed_lines: List[str] = field(default_factory=list)


@dataclass
class FileDiff:
    """Structured representation of changes to a single file.

    Attributes:
        path:   Relative file path.
        status: ``modified``, ``added``, or ``deleted``.
        hunks:  List of diff hunks.
        diff:   Raw unified diff text for this file.
    """

    path: str
    status: str = "modified"
    hunks: List[DiffHunk] = field(default_factory=list)
    diff: str = ""


@dataclass
class DiffStats:
    """High-level statistics for a set of file changes.

    Attributes:
        files_changed: Number of files modified, added, or deleted.
        insertions:    Total lines added.
        deletions:     Total lines removed.
    """

    files_changed: int = 0
    insertions: int = 0
    deletions: int = 0


def parse_diff(raw_diff: str) -> List[FileDiff]:
    """Parse a unified diff string into structured ``FileDiff`` objects.

    Args:
        raw_diff: Output of ``git diff``.

    Returns:
        List of ``FileDiff`` instances, one per changed file.
    """
    files: List[FileDiff] = []
    current_file: Optional[FileDiff] = None
    current_hunk: Optional[DiffHunk] = None

    for line in raw_diff.splitlines():
        if line.startswith("diff --git"):
            if current_hunk and current_file:
                current_file.hunks.append(current_hunk)
            if current_file:
                files.append(current_file)
            path = _extract_path_from_diff_header(line)
            current_file = FileDiff(path=path)
            current_hunk = None

        elif line.startswith("new file"):
            if current_file:
                current_file.status = "added"

        elif line.startswith("deleted file"):
            if current_file:
                current_file.status = "deleted"

        elif line.startswith("@@"):
            if current_hunk and current_file:
                current_file.hunks.append(current_hunk)
            current_hunk = DiffHunk(header=line)

        elif current_hunk is not None:
            if line.startswith("+") and not line.startswith("+++"):
                current_hunk.added_lines.append(line[1:])
            elif line.startswith("-") and not line.startswith("---"):
                current_hunk.removed_lines.append(line[1:])

    if current_hunk and current_file:
        current_file.hunks.append(current_hunk)
    if current_file:
        files.append(current_file)

    for f in files:
        f.diff = _rebuild_file_diff(f, raw_diff)

    return files


def _extract_path_from_diff_header(header_line: str) -> str:
    """Extract the file path from a ``diff --git a/... b/...`` line.

    Args:
        header_line: The ``diff --git`` line.

    Returns:
        Relative file path string.
    """
    parts = header_line.split(" b/")
    if len(parts) >= 2:
        return parts[-1]
    return header_line.split()[-1]


def _rebuild_file_diff(file_diff: FileDiff, full_diff: str) -> str:
    """Extract the raw diff text for a single file from the full diff.

    Args:
        file_diff: The ``FileDiff`` to extract text for.
        full_diff: Complete ``git diff`` output.

    Returns:
        Subset of ``full_diff`` belonging to this file.
    """
    lines = full_diff.splitlines()
    start = None
    end = None
    for i, line in enumerate(lines):
        if line.startswith("diff --git") and file_diff.path in line:
            start = i
        elif start is not None and i > start and line.startswith("diff --git"):
            end = i
            break
    if start is not None:
        return "\n".join(lines[start:end])
    return ""


def get_changed_files(worktree_path: str) -> List[Dict[str, str]]:
    """List files that have been modified, added, or deleted.

    Args:
        worktree_path: Absolute path to the worktree.

    Returns:
        List of dicts with ``path`` and ``status`` keys.
    """
    result = subprocess.run(
        ["git", "diff", "--name-status", "HEAD"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )

    status_map = {"M": "modified", "A": "added", "D": "deleted"}
    files: List[Dict[str, str]] = []
    for line in result.stdout.strip().splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        if len(parts) == 2:
            code, path = parts
            files.append({
                "path": path,
                "status": status_map.get(code[0], "modified"),
            })
    return files


def _parse_stat_summary(stdout: str) -> DiffStats:
    """Parse the summary line from ``git diff --stat`` output.

    Args:
        stdout: Full ``git diff --stat`` output.

    Returns:
        Populated ``DiffStats``.
    """
    stats = DiffStats()
    for line in stdout.strip().splitlines():
        if "file" in line and "changed" in line:
            parts = line.split(",")
            for part in parts:
                part = part.strip()
                if "file" in part:
                    stats.files_changed = int(part.split()[0])
                elif "insertion" in part:
                    stats.insertions = int(part.split()[0])
                elif "deletion" in part:
                    stats.deletions = int(part.split()[0])
    return stats


def get_diff_stats(worktree_path: str, base_branch: str = "main") -> DiffStats:
    """Compute high-level diff statistics combining committed and uncommitted changes.

    Args:
        worktree_path: Absolute path to the worktree.
        base_branch:   Branch to compare against.

    Returns:
        ``DiffStats`` with file, insertion, and deletion counts.
    """
    committed = DiffStats()
    for diff_spec in (f"{base_branch}...HEAD", f"{base_branch}..HEAD"):
        result = subprocess.run(
            ["git", "diff", "--stat", diff_spec],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode == 0 and (result.stdout or "").strip():
            committed = _parse_stat_summary(result.stdout)
            break
        logger.debug("git diff --stat %s empty or failed (rc=%d)", diff_spec, result.returncode)

    uncommitted = DiffStats()
    result = subprocess.run(
        ["git", "diff", "--stat", "HEAD"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode == 0 and (result.stdout or "").strip():
        uncommitted = _parse_stat_summary(result.stdout)

    return DiffStats(
        files_changed=committed.files_changed + uncommitted.files_changed,
        insertions=committed.insertions + uncommitted.insertions,
        deletions=committed.deletions + uncommitted.deletions,
    )


def detect_conflicts(
    branch_a: str,
    branch_b: str,
    repo_path: str,
) -> List[str]:
    """Detect merge conflicts between two branches without actually merging.

    Uses ``git merge-tree`` to simulate the merge in memory.

    Args:
        branch_a:  First branch name.
        branch_b:  Second branch name.
        repo_path: Absolute path to the repository.

    Returns:
        List of conflicting file paths (empty if no conflicts).
    """
    base_result = subprocess.run(
        ["git", "merge-base", branch_a, branch_b],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    if base_result.returncode != 0:
        logger.warning("No merge base found for %s and %s", branch_a, branch_b)
        return []

    base_sha = base_result.stdout.strip()
    result = subprocess.run(
        ["git", "merge-tree", base_sha, branch_a, branch_b],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )

    conflicts: List[str] = []
    for line in result.stdout.splitlines():
        if line.startswith("changed in both"):
            parts = line.split()
            if parts:
                conflicts.append(parts[-1])
    return conflicts
