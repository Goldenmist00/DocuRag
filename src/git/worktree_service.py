"""
worktree_service.py
===================
Service layer for Git worktree lifecycle management.

Uses ``subprocess`` rather than GitPython because GitPython's worktree
support is limited.  All configurable values come from
``src.config.repo_constants``.
"""

import json as _json
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests as _requests

from src.config.repo_constants import WORKTREES_DIR_SUFFIX

logger = logging.getLogger(__name__)


def _worktree_parent(repo_path: str) -> Path:
    """Return the directory that holds all worktrees for a repo.

    Args:
        repo_path: Absolute path to the main clone.

    Returns:
        Path to ``<repo_path><WORKTREES_DIR_SUFFIX>/``.
    """
    return Path(f"{repo_path}{WORKTREES_DIR_SUFFIX}")


def _slugify(text: str, max_len: int = 40) -> str:
    """Convert arbitrary text into a safe branch-name slug.

    Args:
        text:    Raw text (e.g. a task description).
        max_len: Maximum slug length.

    Returns:
        Lowercased, hyphen-separated, alphanumeric-only string.
    """
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len]


def create_worktree(
    repo_path: str,
    session_id: str,
    task_description: str,
) -> Dict[str, str]:
    """Create an isolated Git worktree for an agent session.

    Args:
        repo_path:        Absolute path to the main clone.
        session_id:       UUID of the agent session.
        task_description: Human-readable task (used to derive branch name).

    Returns:
        Dict with ``worktree_path``, ``branch_name``, and ``base_commit``.

    Raises:
        subprocess.CalledProcessError: If ``git worktree add`` fails.
    """
    slug = _slugify(task_description)
    branch = f"agent/{session_id[:8]}/{slug}"
    wt_dir = _worktree_parent(repo_path) / session_id
    wt_dir.parent.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        ["git", "worktree", "add", str(wt_dir), "-b", branch],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )

    base_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(wt_dir),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    logger.info(
        "Worktree created: branch=%s path=%s base=%s",
        branch, wt_dir, base_commit[:8],
    )
    return {
        "worktree_path": str(wt_dir),
        "branch_name": branch,
        "base_commit": base_commit,
    }


def list_worktrees(repo_path: str) -> List[Dict[str, str]]:
    """List all Git worktrees for a repository.

    Args:
        repo_path: Absolute path to the main clone.

    Returns:
        List of dicts with ``path`` and ``branch`` keys.
    """
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )

    worktrees: List[Dict[str, str]] = []
    current: Dict[str, str] = {}
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            if current:
                worktrees.append(current)
            current = {"path": line.split(" ", 1)[1]}
        elif line.startswith("branch "):
            current["branch"] = line.split(" ", 1)[1]
    if current:
        worktrees.append(current)
    return worktrees


def commit_changes(worktree_path: str, message: str) -> Optional[str]:
    """Stage all changes and create a commit in a worktree.

    Args:
        worktree_path: Absolute path to the worktree.
        message:       Commit message.

    Returns:
        The new commit SHA, or ``None`` if nothing to commit.

    Raises:
        subprocess.CalledProcessError: If git commands fail.
    """
    subprocess.run(
        ["git", "add", "-A"],
        cwd=worktree_path,
        check=True,
        capture_output=True,
    )

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
        check=True,
    )
    if not status.stdout.strip():
        logger.info("Nothing to commit in %s", worktree_path)
        return None

    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=worktree_path,
        check=True,
        capture_output=True,
        text=True,
    )

    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    logger.info("Committed %s in %s", sha[:8], worktree_path)
    return sha


def get_diff(worktree_path: str, base_branch: str = "main") -> str:
    """Get the unified diff combining committed branch changes and uncommitted work.

    Collects committed inter-branch diff (if any) and uncommitted working-tree
    changes separately, then concatenates them so the caller always sees the
    full picture — even when the agent leaves changes unstaged.

    Args:
        worktree_path: Absolute path to the worktree.
        base_branch:   Branch to diff against.

    Returns:
        Unified diff string (may be empty if no changes).
    """
    parts: list[str] = []

    for diff_spec in (f"{base_branch}...HEAD", f"{base_branch}..HEAD"):
        result = subprocess.run(
            ["git", "diff", diff_spec],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode == 0 and (result.stdout or "").strip():
            parts.append(result.stdout)
            break
        logger.debug("git diff %s empty or failed (rc=%d)", diff_spec, result.returncode)

    uncommitted = subprocess.run(
        ["git", "diff", "HEAD"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if uncommitted.returncode == 0 and (uncommitted.stdout or "").strip():
        parts.append(uncommitted.stdout)

    if parts:
        return "\n".join(parts)

    logger.warning("No committed or uncommitted changes found in %s", worktree_path)
    return ""


def merge_to_branch(
    repo_path: str,
    worktree_branch: str,
    target_branch: str = "main",
) -> Dict[str, object]:
    """Merge a worktree branch into the target branch.

    Args:
        repo_path:       Absolute path to the main clone.
        worktree_branch: Branch name created for the worktree.
        target_branch:   Branch to merge into.

    Returns:
        Dict with ``merged`` (bool), ``commit_hash``, and ``conflicts``.
    """
    subprocess.run(
        ["git", "checkout", target_branch],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    result = subprocess.run(
        ["git", "merge", worktree_branch, "--no-edit"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        conflict_files = _extract_conflict_files(result.stderr + result.stdout)
        subprocess.run(
            ["git", "merge", "--abort"],
            cwd=repo_path,
            capture_output=True,
        )
        logger.warning(
            "Merge conflict: %s -> %s, files=%s",
            worktree_branch, target_branch, conflict_files,
        )
        return {
            "merged": False,
            "commit_hash": None,
            "conflicts": conflict_files,
        }

    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    logger.info("Merged %s -> %s (%s)", worktree_branch, target_branch, sha[:8])
    return {"merged": True, "commit_hash": sha, "conflicts": []}


def _extract_conflict_files(output: str) -> List[str]:
    """Parse git merge output to find conflicting file paths.

    Args:
        output: Combined stdout/stderr from a failed ``git merge``.

    Returns:
        List of file path strings.
    """
    files: List[str] = []
    for line in output.splitlines():
        if "CONFLICT" in line and "Merge conflict in" in line:
            parts = line.split("Merge conflict in")
            if len(parts) > 1:
                files.append(parts[1].strip())
    return files


def cleanup_worktree(
    repo_path: str,
    session_id: str,
    delete_branch: bool = True,
) -> None:
    """Remove a worktree and optionally delete its branch.

    Args:
        repo_path:     Absolute path to the main clone.
        session_id:    UUID of the agent session.
        delete_branch: Whether to also delete the local branch.
    """
    wt_dir = _worktree_parent(repo_path) / session_id

    if wt_dir.exists():
        subprocess.run(
            ["git", "worktree", "remove", str(wt_dir), "--force"],
            cwd=repo_path,
            capture_output=True,
        )
        if wt_dir.exists():
            shutil.rmtree(str(wt_dir), ignore_errors=True)
        logger.info("Worktree removed: %s", wt_dir)

    if delete_branch:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        branches = [
            l.split(" ", 1)[1]
            for l in result.stdout.splitlines()
            if l.startswith("branch ")
        ]
        for b in _find_session_branches(repo_path, session_id):
            full_ref = f"refs/heads/{b}"
            if full_ref not in branches:
                subprocess.run(
                    ["git", "branch", "-D", b],
                    cwd=repo_path,
                    capture_output=True,
                )
                logger.info("Deleted branch: %s", b)


CHECKPOINT_PREFIX = "[checkpoint:"


def create_checkpoint(worktree_path: str, step: int) -> Optional[str]:
    """Stage all changes and create a checkpoint commit.

    Args:
        worktree_path: Absolute path to the worktree.
        step:          Step number for the checkpoint label.

    Returns:
        Commit SHA, or ``None`` if nothing to commit.
    """
    return commit_changes(worktree_path, f"{CHECKPOINT_PREFIX}step-{step}]")


def list_checkpoints(worktree_path: str) -> List[Dict[str, Any]]:
    """List checkpoint commits in reverse chronological order.

    Args:
        worktree_path: Absolute path to the worktree.

    Returns:
        List of dicts with ``sha``, ``step``, ``message``, and ``timestamp``.
    """
    result = subprocess.run(
        ["git", "log", "--oneline", "--format=%H|%s|%aI",
         "--fixed-strings", f"--grep={CHECKPOINT_PREFIX}"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    checkpoints: List[Dict[str, Any]] = []
    if result.returncode != 0 or not (result.stdout or "").strip():
        return checkpoints
    for line in result.stdout.strip().splitlines():
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue
        sha, msg, ts = parts
        step = -1
        if CHECKPOINT_PREFIX in msg:
            try:
                inner = msg.split(CHECKPOINT_PREFIX)[1].rstrip("]")
                step = int(inner.replace("step-", ""))
            except (IndexError, ValueError):
                pass
        checkpoints.append({"sha": sha, "step": step, "message": msg, "timestamp": ts})
    return checkpoints


def restore_checkpoint(worktree_path: str, sha: str) -> str:
    """Hard-reset the worktree to a specific checkpoint commit.

    Args:
        worktree_path: Absolute path to the worktree.
        sha:           Commit SHA to reset to.

    Returns:
        The SHA that was restored to.

    Raises:
        subprocess.CalledProcessError: If git reset fails.
    """
    subprocess.run(
        ["git", "reset", "--hard", sha],
        cwd=worktree_path,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    logger.info("Restored worktree %s to checkpoint %s", worktree_path, sha[:8])
    return sha


def revert_all_changes(worktree_path: str) -> int:
    """Discard all uncommitted changes in the worktree.

    Args:
        worktree_path: Absolute path to the worktree.

    Returns:
        Number of files that were reverted.
    """
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    file_count = len([l for l in (status.stdout or "").splitlines() if l.strip()])
    subprocess.run(
        ["git", "checkout", "."],
        cwd=worktree_path,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "clean", "-fd"],
        cwd=worktree_path,
        capture_output=True,
        check=True,
    )
    logger.info("Reverted %d files in %s", file_count, worktree_path)
    return file_count


def _find_session_branches(repo_path: str, session_id: str) -> List[str]:
    """Find branches that belong to a session by its ID prefix.

    Args:
        repo_path:  Absolute path to the main clone.
        session_id: UUID of the agent session.

    Returns:
        List of matching branch names.
    """
    result = subprocess.run(
        ["git", "branch", "--list", f"agent/{session_id[:8]}/*"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    return [
        b.strip().lstrip("* ")
        for b in result.stdout.splitlines()
        if b.strip()
    ]


# ---------------------------------------------------------------------------
# Push & Pull-request helpers
# ---------------------------------------------------------------------------


def _extract_github_info(repo_path: str) -> Dict[str, Optional[str]]:
    """Extract owner, repo name, and optional auth token from the origin URL.

    Parses ``git remote get-url origin`` to derive:

    - ``owner``: GitHub user/org
    - ``repo``:  Repository name
    - ``token``: PAT embedded in the URL (``https://TOKEN@github.com/...``),
      or ``None`` for unauthenticated clones.

    Args:
        repo_path: Absolute path to any checkout (main clone or worktree).

    Returns:
        Dict with ``owner``, ``repo``, and nullable ``token``.

    Raises:
        RuntimeError: If the remote URL format is unrecognised.
    """
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )
    url = result.stdout.strip()
    parsed = urlparse(url)

    token: Optional[str] = None
    if parsed.username and not parsed.password:
        token = parsed.username
    elif parsed.password:
        token = parsed.password

    path = parsed.path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    parts = path.split("/")
    if len(parts) < 2:
        raise RuntimeError(f"Cannot parse owner/repo from remote URL: {url}")

    return {"owner": parts[0], "repo": parts[1], "token": token}


def _get_oauth_token() -> Optional[str]:
    """Return the stored GitHub OAuth token, or ``None``.

    Returns:
        Access token string or ``None``.
    """
    from src.db import github_db
    return github_db.get_token()


def push_branch(repo_path: str, branch_name: str) -> Dict[str, Any]:
    """Push a local branch to the remote origin.

    Uses the stored OAuth token to authenticate, bypassing any
    OS-level credential managers (e.g. Windows Credential Manager)
    by setting ``credential.helper=`` for the push command.

    Args:
        repo_path:   Absolute path to the repo or worktree.
        branch_name: Name of the branch to push.

    Returns:
        Dict with ``pushed`` (bool) and ``branch``.

    Raises:
        RuntimeError: If ``git push`` fails and the branch does
            not already exist on the remote.
    """
    info = _extract_github_info(repo_path)
    original_url = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=repo_path, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    ).stdout.strip()

    token = info.get("token")
    authed_url = None
    if not token:
        token = _get_oauth_token()
        if token and info.get("owner") and info.get("repo"):
            authed_url = (
                f"https://x-access-token:{token}@github.com/"
                f"{info['owner']}/{info['repo']}.git"
            )
            subprocess.run(
                ["git", "remote", "set-url", "origin", authed_url],
                cwd=repo_path, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
            )

    try:
        cmd = [
            "git",
            "-c", "credential.helper=",
            "push", "-u", "origin", branch_name,
        ]
        result = subprocess.run(
            cmd, cwd=repo_path,
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        stderr = result.stderr.strip()
        if result.returncode != 0:
            up_to_date = "everything up-to-date" in stderr.lower()
            already_exists = "already exists" in stderr.lower()
            if up_to_date or already_exists:
                logger.info("Branch %s already up-to-date on remote", branch_name)
            else:
                raise RuntimeError(f"git push failed: {stderr}")
    finally:
        if authed_url:
            subprocess.run(
                ["git", "remote", "set-url", "origin", original_url],
                cwd=repo_path, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
            )

    logger.info("Pushed branch %s from %s", branch_name, repo_path)
    return {"pushed": True, "branch": branch_name}


def _branch_exists_on_remote(repo_path: str, branch_name: str) -> bool:
    """Check whether a branch already exists on the remote.

    Args:
        repo_path:   Absolute path to the repo or worktree.
        branch_name: Branch name to check.

    Returns:
        True if the branch exists on ``origin``.
    """
    result = subprocess.run(
        ["git", "ls-remote", "--heads", "origin", branch_name],
        cwd=repo_path, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    return branch_name in result.stdout


def create_github_pr(
    repo_path: str,
    head_branch: str,
    base_branch: str,
    title: str,
    body: str,
) -> Dict[str, Any]:
    """Push the branch and open a GitHub pull request via the REST API.

    If the push fails but the branch already exists on the remote,
    the PR creation proceeds anyway.  Uses the stored OAuth token
    for both the push and the API call.

    Args:
        repo_path:   Absolute path to the repo or worktree.
        head_branch: Branch containing changes (the one being pushed).
        base_branch: Target branch for the PR (e.g. ``"main"``).
        title:       PR title.
        body:        PR description (Markdown).

    Returns:
        Dict with ``pr_url``, ``pr_number``, ``branch``, ``base_branch``.

    Raises:
        RuntimeError: On push failure (when branch is not on remote)
            or GitHub API errors.
    """
    try:
        push_branch(repo_path, head_branch)
    except RuntimeError as push_err:
        if _branch_exists_on_remote(repo_path, head_branch):
            logger.warning(
                "Push failed but branch %s exists on remote — continuing to PR: %s",
                head_branch, push_err,
            )
        else:
            raise

    info = _extract_github_info(repo_path)
    api_url = f"https://api.github.com/repos/{info['owner']}/{info['repo']}/pulls"

    headers: Dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
    }
    token = info.get("token") or _get_oauth_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    payload = {
        "title": title,
        "body": body,
        "head": head_branch,
        "base": base_branch,
    }

    resp = _requests.post(api_url, headers=headers, json=payload, timeout=30)

    if resp.status_code not in (200, 201):
        detail = resp.text[:500]
        raise RuntimeError(
            f"GitHub API error ({resp.status_code}): {detail}"
        )

    data = resp.json()
    logger.info(
        "PR #%s created: %s -> %s (%s)",
        data["number"], head_branch, base_branch, data["html_url"],
    )
    return {
        "pr_url": data["html_url"],
        "pr_number": data["number"],
        "branch": head_branch,
        "base_branch": base_branch,
    }
