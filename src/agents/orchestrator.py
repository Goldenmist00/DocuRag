"""
orchestrator.py
===============
Central async coordinator for repo registration, indexing, consolidation,
and coding-agent sessions.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.agents import consolidate_agent, ingest_agent
from src.agents.coding_agent import CodingAgent
from src.config.repo_constants import (
    DEFAULT_GIT_BRANCH,
    DEFAULT_REPOS_DIR,
    MAX_CONCURRENT_SESSIONS,
    MSG_ORCHESTRATOR_AGENT_RESTARTED,
    MSG_ORCHESTRATOR_CONSOLIDATION_STARTED,
    MSG_ORCHESTRATOR_INVALID_GITHUB_URL,
    MSG_ORCHESTRATOR_MERGE_CONFLICT_TEMPLATE,
    MSG_ORCHESTRATOR_REPO_ALREADY_REGISTERED_TEMPLATE,
    MSG_ORCHESTRATOR_REPO_NOT_READY,
    MSG_ORCHESTRATOR_REINDEX_STARTED,
    MSG_ORCHESTRATOR_SESSION_LIMIT_TEMPLATE,
    MSG_ORCHESTRATOR_SESSION_NO_WORKTREE,
    MSG_ORCHESTRATOR_WORKTREE_NOT_FOUND,
    REPO_INDEXING_STATUS_CONSOLIDATING,
    REPO_INDEXING_STATUS_FAILED,
    REPO_INDEXING_STATUS_INDEXING,
    REPO_INDEXING_STATUS_READY,
    SESSION_STATUS_CANCELLED,
    SESSION_STATUS_RUNNING,
    WORKTREE_STATUS_MERGED,
)
from src.db import repo_context_db, repo_db, repo_memory_db, session_db
from src.git import diff_service, git_service, worktree_service
from src.generator import Generator
from src.utils.repo_errors import (
    MergeConflictError,
    RepoAlreadyExistsError,
    RepoAnalyzerError,
    RepoNotFoundError,
    SessionLimitError,
    SessionNotFoundError,
)
from src.utils.repo_validation import validate_github_url

logger = logging.getLogger(__name__)

_background_pool = ThreadPoolExecutor(
    max_workers=MAX_CONCURRENT_SESSIONS,
    thread_name_prefix="agent",
)

_active_agent_tasks: Dict[str, asyncio.Task] = {}
"""Maps session_id -> running asyncio.Task for active agent sessions."""


def _repos_root_path() -> Path:
    """Resolve the absolute directory where clones are stored.

    Args:
        None

    Returns:
        Path to the repos root (from ``REPOS_DIR`` or default).

    Raises:
        None
    """
    return Path(os.getenv("REPOS_DIR", DEFAULT_REPOS_DIR)).resolve()


def _hash_auth_token(token: Optional[str]) -> Optional[str]:
    """Hash a PAT for storage in ``repos.auth_token_hash``.

    Args:
        token: Raw token, or ``None``.

    Returns:
        Hex digest string, or ``None`` when *token* is absent.

    Raises:
        None
    """
    if not token:
        return None
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _require_repo(repo_id: str) -> Dict[str, Any]:
    """Load a repo row or raise :class:`RepoNotFoundError`.

    Args:
        repo_id: Repository UUID string.

    Returns:
        Repo row dict.

    Raises:
        RepoNotFoundError: When no row exists.
    """
    row = repo_db.find_by_id(repo_id)
    if row is None:
        raise RepoNotFoundError(f"Repository not found: {repo_id}")
    return row


def _require_session(session_id: str) -> Dict[str, Any]:
    """Load an agent session row or raise :class:`SessionNotFoundError`.

    Args:
        session_id: Session UUID string.

    Returns:
        Session row dict.

    Raises:
        SessionNotFoundError: When no row exists.
    """
    row = session_db.find_by_id(session_id)
    if row is None:
        raise SessionNotFoundError(f"Session not found: {session_id}")
    return row


def _log_background_failure(fut: asyncio.Future) -> None:
    """Log exceptions from fire-and-forget executor futures.

    Args:
        fut: Completed asyncio Future from ``run_in_executor``.

    Returns:
        None

    Raises:
        None
    """
    if fut.cancelled():
        logger.warning("Background task was cancelled")
        return
    exc = fut.exception()
    if exc is not None:
        logger.exception("Background task failed", exc_info=exc)


def _serialize_file_diff(fd: diff_service.FileDiff) -> Dict[str, Any]:
    """Convert a :class:`FileDiff` into a JSON-friendly dict.

    Args:
        fd: Parsed file diff.

    Returns:
        Serializable dict with path, status, hunks, and raw diff text.

    Raises:
        None
    """
    hunks: List[Dict[str, Any]] = []
    for h in fd.hunks:
        hunks.append(
            {
                "header": h.header,
                "added_lines": list(h.added_lines),
                "removed_lines": list(h.removed_lines),
            }
        )
    return {
        "path": fd.path,
        "status": fd.status,
        "hunks": hunks,
        "diff": fd.diff,
    }


def _clone_and_index(repo_id: str, remote_url: str, auth_token: Optional[str]) -> None:
    """Clone, ingest, consolidate, and mark the repo ready (thread target).

    Args:
        repo_id:     Repository UUID.
        remote_url:  GitHub HTTPS URL.
        auth_token:  Optional PAT for private clones.

    Returns:
        None

    Raises:
        None: Errors are recorded on the repo row as ``failed``.
    """
    row = repo_db.find_by_id(repo_id)
    local_path = row["local_path"] if row else str(_repos_root_path() / repo_id)
    try:
        repo_db.update_progress(repo_id, "cloning", 0, 1, "Cloning repository…")
        git_service.clone_repo(remote_url, repo_id, auth_token)
        repo_db.update_progress(repo_id, "cloning", 1, 1, "Clone complete")
        repo_db.update_status(repo_id, REPO_INDEXING_STATUS_INDEXING, None)
        generator = Generator()
        repo_memory_db.ensure_table()
        ingest_agent.ingest_repo(repo_id, local_path, generator)
        repo_db.update_status(repo_id, REPO_INDEXING_STATUS_CONSOLIDATING, None)
        consolidate_agent.consolidate_repo(repo_id, generator)
        repo_db.mark_indexed(repo_id)
    except Exception as exc:
        logger.exception("clone/index pipeline failed for %s", repo_id)
        repo_db.update_status(repo_id, REPO_INDEXING_STATUS_FAILED, str(exc))


def _reindex_sync(repo_id: str) -> None:
    """Re-run ingestion and consolidation for an existing clone (thread target).

    After ingestion completes, consolidation is also run so the global
    repo_context is kept up to date.

    Args:
        repo_id: Repository UUID.

    Returns:
        None

    Raises:
        None: Failures are reflected via ``ingest_repo`` / ``repo_db`` status.
    """
    row = _require_repo(repo_id)
    generator = Generator()
    ingest_agent.ingest_repo(repo_id, row["local_path"], generator, force=True)
    try:
        repo_db.update_status(repo_id, REPO_INDEXING_STATUS_CONSOLIDATING, None)
        consolidate_agent.consolidate_repo(repo_id, generator)
        repo_db.mark_indexed(repo_id)
    except Exception as exc:
        logger.warning("Post-reindex consolidation failed: %s", exc)


def _consolidate_sync(repo_id: str) -> None:
    """Re-run consolidation for a repo (thread target).

    Args:
        repo_id: Repository UUID.

    Returns:
        None

    Raises:
        RepoNotFoundError: When the repo row is missing.
    """
    _require_repo(repo_id)
    try:
        repo_db.update_status(repo_id, REPO_INDEXING_STATUS_CONSOLIDATING, None)
        generator = Generator()
        consolidate_agent.consolidate_repo(repo_id, generator)
        repo_db.mark_indexed(repo_id)
    except Exception as exc:
        logger.exception("Consolidation failed for %s", repo_id)
        repo_db.update_status(repo_id, REPO_INDEXING_STATUS_FAILED, str(exc))


async def register_repo(
    remote_url: str,
    auth_token: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate URL, register the repo, and start clone/index in the background.

    Args:
        remote_url:  GitHub HTTPS clone URL.
        auth_token:  Optional PAT (hashed at rest).
        user_id:     Authenticated user email (for multi-tenancy).

    Returns:
        New repo dict including ``indexing_status``.

    Raises:
        ValueError: If *remote_url* is not a valid GitHub HTTPS URL.
        RepoAlreadyExistsError: If *remote_url* is already registered.
    """
    if not validate_github_url(remote_url):
        raise ValueError(MSG_ORCHESTRATOR_INVALID_GITHUB_URL)
    if repo_db.find_by_remote_url(remote_url, user_id=user_id) is not None:
        raise RepoAlreadyExistsError(
            MSG_ORCHESTRATOR_REPO_ALREADY_REGISTERED_TEMPLATE.format(
                remote_url=remote_url,
            ),
        )
    name = git_service.extract_repo_name(remote_url)
    new_id = str(uuid.uuid4())
    local_path = str(_repos_root_path() / new_id)
    token_hash = _hash_auth_token(auth_token)
    row = repo_db.insert(
        name,
        remote_url,
        local_path,
        auth_token_hash=token_hash,
        repo_id=new_id,
        user_id=user_id,
    )
    loop = asyncio.get_running_loop()
    fut = loop.run_in_executor(
        _background_pool,
        functools.partial(_clone_and_index, new_id, remote_url, auth_token),
    )
    fut.add_done_callback(_log_background_failure)
    out = dict(row)
    out["status"] = out.get("indexing_status")
    return out


def _schedule_done_callback(fut: asyncio.Future) -> None:
    """Attach standard logging to an executor future.

    Args:
        fut: Future returned by ``run_in_executor``.

    Returns:
        None

    Raises:
        None
    """
    fut.add_done_callback(_log_background_failure)


async def trigger_reindex(repo_id: str) -> Dict[str, Any]:
    """Verify the repo exists and schedule a full re-ingest pass.

    Args:
        repo_id: Repository UUID.

    Returns:
        Status dict acknowledging the background job.

    Raises:
        RepoNotFoundError: When the repo does not exist.
    """
    _require_repo(repo_id)
    loop = asyncio.get_running_loop()
    fut = loop.run_in_executor(
        _background_pool,
        functools.partial(_reindex_sync, repo_id),
    )
    _schedule_done_callback(fut)
    return {
        "repo_id": repo_id,
        "indexing_status": REPO_INDEXING_STATUS_INDEXING,
        "message": MSG_ORCHESTRATOR_REINDEX_STARTED,
    }


async def trigger_consolidation(repo_id: str) -> Dict[str, Any]:
    """Verify the repo exists and schedule consolidation.

    Args:
        repo_id: Repository UUID.

    Returns:
        Status dict acknowledging the background job.

    Raises:
        RepoNotFoundError: When the repo does not exist.
    """
    _require_repo(repo_id)
    loop = asyncio.get_running_loop()
    fut = loop.run_in_executor(
        _background_pool,
        functools.partial(_consolidate_sync, repo_id),
    )
    _schedule_done_callback(fut)
    return {
        "repo_id": repo_id,
        "indexing_status": REPO_INDEXING_STATUS_CONSOLIDATING,
        "message": MSG_ORCHESTRATOR_CONSOLIDATION_STARTED,
    }


def _post_agent_refresh(repo_id: str, worktree_path: str, base_commit: Optional[str]) -> None:
    """Detect files changed by the agent and incrementally re-ingest them.

    Runs ``git diff --name-only`` against the base commit to find changed
    files, re-ingests only those files, rebuilds their reference edges,
    and re-embeds their code chunks.

    Args:
        repo_id:        Repository UUID.
        worktree_path:  Absolute path to the worktree.
        base_commit:    SHA of the commit before agent started.

    Returns:
        None
    """
    import subprocess as _sp

    if not base_commit:
        logger.debug("No base_commit for post-agent refresh — skipping")
        return

    try:
        result = _sp.run(
            ["git", "diff", "--name-only", f"{base_commit}..HEAD"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            logger.warning("Post-agent git diff failed: %s", result.stderr)
            return

        changed = [f.strip() for f in result.stdout.strip().splitlines() if f.strip()]
        if not changed:
            logger.debug("No files changed by agent — skipping refresh")
            return

        logger.info("Post-agent refresh: %d changed files", len(changed))

        gen = Generator()
        ingest_result = ingest_agent.ingest_files(
            repo_id, changed, worktree_path, gen,
        )
        ast_results = ingest_result.get("ast_results", {})
        file_contents = ingest_result.get("file_contents", {})
        file_hashes = ingest_result.get("file_hashes", {})

        if ast_results:
            try:
                from src.repo.reference_graph import build_reference_graph_for_files
                from src.repo.repo_processor import walk_repo

                repo_row = repo_db.find_by_id(repo_id)
                main_path = repo_row["local_path"] if repo_row else worktree_path
                all_files = {
                    Path(f["path"]).as_posix()
                    for f in walk_repo(main_path)
                }
                build_reference_graph_for_files(
                    repo_id, changed, ast_results, all_files,
                )
            except Exception as exc:
                logger.warning("Post-agent reference graph update failed: %s", exc)

            try:
                from src.repo.code_embedder import re_embed_files
                re_embed_files(
                    repo_id, changed, file_contents, file_hashes, ast_results,
                )
            except Exception as exc:
                logger.warning("Post-agent re-embed failed: %s", exc)

        try:
            consolidate_agent.consolidate_repo(repo_id, gen)
            logger.info("Post-agent consolidation completed")
        except Exception as exc:
            logger.warning("Post-agent consolidation failed: %s", exc)

        logger.info("Post-agent refresh completed for %d files", len(changed))

    except Exception as exc:
        logger.warning("Post-agent refresh failed: %s", exc)


async def _run_agent_session(
    session_id: str,
    worktree_path: str,
    repo_context: Dict[str, Any],
    task: str,
    seed_messages: Optional[List[Dict[str, Any]]] = None,
    repo_id: Optional[str] = None,
) -> None:
    """Drive one :class:`CodingAgent` run and persist terminal status.

    After successful completion, triggers incremental re-ingestion
    of files changed by the agent.

    Args:
        session_id:    Session UUID.
        worktree_path: Absolute worktree path.
        repo_context:  Context snapshot dict.
        task:          Task description.
        seed_messages: Optional conversation seed (resume).
        repo_id:       Repository UUID for RAG queries (optional).

    Returns:
        None

    Raises:
        None: Failures mark the session ``failed``.
    """
    session_db.update_session_status(session_id, SESSION_STATUS_RUNNING)

    base_commit = None
    try:
        import subprocess as _sp
        bc_result = _sp.run(
            ["git", "rev-parse", "HEAD"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if bc_result.returncode == 0:
            base_commit = bc_result.stdout.strip()
    except Exception:
        pass

    try:
        agent = CodingAgent(
            session_id,
            worktree_path,
            repo_context,
            task,
            seed_messages=seed_messages,
            repo_id=repo_id,
        )
        result = await agent.run()

        if result.completed and repo_id:
            try:
                await asyncio.to_thread(
                    _post_agent_refresh, repo_id, worktree_path, base_commit,
                )
            except Exception as exc:
                logger.warning("Post-agent refresh failed: %s", exc)

    except asyncio.CancelledError:
        logger.info("Agent session %s stopped by user", session_id)
        session_db.update_session_status(session_id, SESSION_STATUS_CANCELLED)
        from src.agents import event_bus

        await event_bus.emit(session_id, "stopped", {"reason": "User stopped the session"})
        event_bus.remove_queue(session_id)
    except Exception as exc:
        logger.exception("Agent session %s crashed", session_id)
        session_db.mark_session_failed(session_id, str(exc))
    finally:
        _active_agent_tasks.pop(session_id, None)


def _load_notebook_context(notebook_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a notebook's exported context for injection into an agent session.

    Args:
        notebook_id: UUID of the source notebook.

    Returns:
        Context dict with ``title``, ``sources``, ``conversation_history``,
        or ``None`` if the notebook cannot be loaded.
    """
    try:
        from src.db import notebook_db, source_db

        nb = notebook_db.get_notebook(notebook_id)
        if nb is None:
            logger.warning("Notebook %s not found for context import", notebook_id)
            return None

        sources_raw = source_db.list_sources(notebook_id)
        sources_summary = [
            {"name": s.get("name", ""), "source_type": s.get("source_type", "")}
            for s in sources_raw
        ]
        history = notebook_db.get_conversation_history(notebook_id)

        return {
            "notebook_id": nb["id"],
            "title": nb["title"],
            "sources": sources_summary,
            "conversation_history": history,
        }
    except Exception:
        logger.warning("Failed to load notebook context for %s", notebook_id, exc_info=True)
        return None


def _build_notebook_seed(
    nb_ctx: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Convert imported notebook context into seed messages for the coding agent.

    Args:
        nb_ctx: Notebook context dict from ``_load_notebook_context``.

    Returns:
        List of ``{role, content}`` message dicts to seed the agent conversation.
    """
    import json

    parts = [
        f"## Imported planning context from notebook: \"{nb_ctx.get('title', 'Untitled')}\"",
        "",
    ]

    sources = nb_ctx.get("sources") or []
    if sources:
        parts.append("### Reference sources used during planning:")
        for s in sources:
            parts.append(f"- {s.get('name', 'unknown')} ({s.get('source_type', '')})")
        parts.append("")

    history = nb_ctx.get("conversation_history") or []
    if history:
        parts.append("### Planning conversation:")
        for msg in history:
            role_label = "User" if msg.get("role") == "user" else "AI"
            parts.append(f"**{role_label}:** {msg.get('content', '')}")
            parts.append("")

    parts.append(
        "Use the above planning context to understand the requirements, "
        "decisions, and architecture discussed. Implement accordingly."
    )

    return [{"role": "system", "content": "\n".join(parts)}]


async def create_agent_session(
    repo_id: str,
    task: str,
    notebook_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a worktree, session row, and background coding agent.

    Args:
        repo_id:     Target repository UUID.
        task:        User task text.
        notebook_id: Optional notebook UUID whose planning context
                     will be imported as seed context for the agent.

    Returns:
        Session dict plus ``worktree_branch``.

    Raises:
        RepoNotFoundError: If the repo is missing.
        RepoAnalyzerError: If the repo is not ``ready``.
        SessionLimitError: If too many sessions are active.
    """
    repo = _require_repo(repo_id)
    if repo.get("indexing_status") != REPO_INDEXING_STATUS_READY:
        raise RepoAnalyzerError(MSG_ORCHESTRATOR_REPO_NOT_READY)
    running = session_db.list_running_sessions(repo_id)
    if len(running) >= MAX_CONCURRENT_SESSIONS:
        raise SessionLimitError(
            MSG_ORCHESTRATOR_SESSION_LIMIT_TEMPLATE.format(
                max_sessions=MAX_CONCURRENT_SESSIONS,
            ),
        )
    session_id = str(uuid.uuid4())
    wt = worktree_service.create_worktree(repo["local_path"], session_id, task)
    wt_row = session_db.insert_worktree(
        repo_id,
        wt["branch_name"],
        wt["worktree_path"],
        wt.get("base_commit"),
    )
    ctx_row = repo_context_db.find_by_repo_id(repo_id)
    ctx: Dict[str, Any] = dict(ctx_row) if ctx_row else {}

    seed_messages: Optional[List[Dict[str, Any]]] = None
    if notebook_id:
        nb_ctx = _load_notebook_context(notebook_id)
        if nb_ctx:
            ctx["notebook_context"] = nb_ctx
            seed_messages = _build_notebook_seed(nb_ctx)

    sess = session_db.insert_session(
        repo_id,
        wt_row["id"],
        task,
        ctx,
        session_id=session_id,
    )
    agent_task = asyncio.create_task(
        _run_agent_session(
            session_id, wt["worktree_path"], ctx, task,
            seed_messages=seed_messages, repo_id=repo_id,
        ),
    )
    _active_agent_tasks[session_id] = agent_task
    out = dict(sess)
    out["worktree_branch"] = wt["branch_name"]
    out["status"] = out.get("status")
    return out


async def resume_session(session_id: str, message: str) -> Dict[str, Any]:
    """Append a user message and restart the agent loop.

    Args:
        session_id: Target session UUID.
        message:    Follow-up user text.

    Returns:
        Status dict with ``session_id`` and ``status``.

    Raises:
        SessionNotFoundError: If the session does not exist.
    """
    row = _require_session(session_id)
    hist = list(row.get("conversation_history") or [])
    hist.append({"role": "user", "content": message})
    session_db.update_conversation_history(session_id, hist)
    wt_id = row.get("worktree_id")
    if wt_id is None:
        raise SessionNotFoundError(MSG_ORCHESTRATOR_SESSION_NO_WORKTREE)
    wt = session_db.find_worktree_by_id(str(wt_id))
    if wt is None:
        raise SessionNotFoundError(MSG_ORCHESTRATOR_WORKTREE_NOT_FOUND)
    ctx = row.get("context_snapshot")
    if not isinstance(ctx, dict):
        ctx = {}
    task = row.get("task_description") or ""
    r_id = str(row["repo_id"]) if row.get("repo_id") else None
    agent_task = asyncio.create_task(
        _run_agent_session(
            session_id,
            wt["worktree_path"],
            ctx,
            task,
            seed_messages=hist,
            repo_id=r_id,
        ),
    )
    _active_agent_tasks[session_id] = agent_task
    return {
        "session_id": session_id,
        "status": SESSION_STATUS_RUNNING,
        "message": MSG_ORCHESTRATOR_AGENT_RESTARTED,
    }


async def stop_session(session_id: str) -> Dict[str, Any]:
    """Cancel a running agent session.

    If the asyncio task reference is available (same server lifecycle),
    the task is cancelled directly.  Otherwise (e.g. after a server
    restart), the session status is updated in the database.

    Args:
        session_id: Target session UUID.

    Returns:
        Dict with ``session_id``, ``status``, and ``message``.

    Raises:
        SessionNotFoundError: If the session does not exist.
        RepoAnalyzerError: If the session is already finished.
    """
    row = _require_session(session_id)
    current_status = row.get("status", "")
    active_statuses = {SESSION_STATUS_RUNNING, "pending", "awaiting_input"}

    task = _active_agent_tasks.get(session_id)
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    elif current_status in active_statuses:
        session_db.update_session_status(session_id, SESSION_STATUS_CANCELLED)
        from src.agents import event_bus

        await event_bus.emit(
            session_id, "stopped", {"reason": "User stopped the session"},
        )
        event_bus.remove_queue(session_id)
    else:
        raise RepoAnalyzerError("Session is not currently running")

    _active_agent_tasks.pop(session_id, None)
    return {
        "session_id": session_id,
        "status": SESSION_STATUS_CANCELLED,
        "message": "Agent session stopped",
    }


async def get_session_diff(session_id: str) -> Dict[str, Any]:
    """Return a structured diff for the session worktree vs the default branch.

    Args:
        session_id: Session UUID.

    Returns:
        Dict with ``files``, ``stats``, and ``session_id``.

    Raises:
        SessionNotFoundError: If session or worktree is missing.
    """
    row = _require_session(session_id)
    wt_id = row.get("worktree_id")
    if wt_id is None:
        raise SessionNotFoundError(MSG_ORCHESTRATOR_SESSION_NO_WORKTREE)
    wt = session_db.find_worktree_by_id(str(wt_id))
    if wt is None:
        raise SessionNotFoundError(MSG_ORCHESTRATOR_WORKTREE_NOT_FOUND)
    repo = _require_repo(str(row["repo_id"]))
    base = repo.get("default_branch") or DEFAULT_GIT_BRANCH
    path = wt["worktree_path"]

    def _sync_diff() -> tuple[str, List[diff_service.FileDiff], diff_service.DiffStats]:
        raw = worktree_service.get_diff(path, base)
        files = diff_service.parse_diff(raw)
        stats = diff_service.get_diff_stats(path, base)
        return raw, files, stats

    raw, files, stats = await asyncio.to_thread(_sync_diff)
    return {
        "session_id": session_id,
        "base_branch": base,
        "files": [_serialize_file_diff(f) for f in files],
        "stats": {
            "files_changed": stats.files_changed,
            "insertions": stats.insertions,
            "deletions": stats.deletions,
        },
        "raw_diff": raw,
    }


def _squash_checkpoints_if_any(worktree_path: str, message: str) -> Optional[str]:
    """Squash checkpoint commits into a single commit with *message*.

    When the agent creates checkpoints during editing, all changes get
    committed incrementally.  At final-commit time ``commit_changes``
    returns ``None`` because there is nothing new to stage.  This helper
    finds the first checkpoint commit, does a soft reset back to its
    parent, then re-commits everything under the user-supplied *message*.

    Args:
        worktree_path: Absolute path to the git worktree.
        message:       Commit message for the squashed commit.

    Returns:
        New commit SHA, or ``None`` if there are no checkpoint commits.
    """
    import subprocess as _sp

    from src.git.worktree_service import CHECKPOINT_PREFIX

    logger.info(
        "Squash: looking for checkpoint commits in %s (prefix=%r)",
        worktree_path, CHECKPOINT_PREFIX,
    )

    log_result = _sp.run(
        ["git", "log", "--format=%H|%s", "--fixed-strings",
         f"--grep={CHECKPOINT_PREFIX}"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    logger.info(
        "Squash: git log rc=%d stdout_lines=%d stderr=%r",
        log_result.returncode,
        len((log_result.stdout or "").strip().splitlines()),
        (log_result.stderr or "").strip()[:200],
    )
    if log_result.returncode != 0 or not (log_result.stdout or "").strip():
        return None

    lines = log_result.stdout.strip().splitlines()
    if not lines:
        return None

    oldest_checkpoint_sha = lines[-1].split("|", 1)[0].strip()
    logger.info(
        "Squash: found %d checkpoint(s), oldest=%s",
        len(lines), oldest_checkpoint_sha[:8],
    )

    parent_result = _sp.run(
        ["git", "rev-parse", f"{oldest_checkpoint_sha}^"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if parent_result.returncode != 0:
        logger.warning(
            "Squash: cannot find parent of %s: %s",
            oldest_checkpoint_sha[:8], parent_result.stderr,
        )
        return None
    parent_sha = parent_result.stdout.strip()
    logger.info("Squash: resetting to parent %s", parent_sha[:8])

    reset_result = _sp.run(
        ["git", "reset", "--soft", parent_sha],
        cwd=worktree_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if reset_result.returncode != 0:
        logger.warning("Squash: reset failed: %s", reset_result.stderr)
        return None

    _sp.run(
        ["git", "add", "-A"],
        cwd=worktree_path,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )

    commit_result = _sp.run(
        ["git", "commit", "-m", message],
        cwd=worktree_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if commit_result.returncode != 0:
        logger.warning("Squash: commit failed: %s", commit_result.stderr)
        return None

    sha_result = _sp.run(
        ["git", "rev-parse", "HEAD"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    sha = sha_result.stdout.strip() if sha_result.returncode == 0 else None
    if sha:
        logger.info("Squashed %d checkpoints into %s", len(lines), sha[:8])
    return sha


async def commit_session_changes(
    session_id: str,
    message: str,
    new_branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Commit the agent's uncommitted changes in the session worktree.

    Optionally creates a new branch before committing so the user can
    keep the worktree branch clean or organize commits on a named branch.

    Args:
        session_id: Session UUID.
        message:    Commit message.
        new_branch: If provided, create and switch to this branch first.

    Returns:
        Dict with ``commit_hash``, ``branch``, and ``session_id``.

    Raises:
        SessionNotFoundError: If session or worktree is missing.
        RepoAnalyzerError:    If commit fails.
    """
    import subprocess as _sp

    row = _require_session(session_id)
    wt_id = row.get("worktree_id")
    if wt_id is None:
        raise SessionNotFoundError(MSG_ORCHESTRATOR_SESSION_NO_WORKTREE)
    wt = session_db.find_worktree_by_id(str(wt_id))
    if wt is None:
        raise SessionNotFoundError(MSG_ORCHESTRATOR_WORKTREE_NOT_FOUND)
    path = wt["worktree_path"]

    def _sync_commit() -> Dict[str, Any]:
        if new_branch:
            _sp.run(
                ["git", "checkout", "-b", new_branch],
                cwd=path,
                capture_output=True,
                text=True,
                check=True,
            )

        sha = worktree_service.commit_changes(path, message)
        if sha is None:
            sha = _squash_checkpoints_if_any(path, message)
        if sha is None:
            raise RepoAnalyzerError("Nothing to commit — no changes detected", 400)

        branch_result = _sp.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=path,
            capture_output=True,
            text=True,
        )
        branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "unknown"
        return {"session_id": session_id, "commit_hash": sha, "branch": branch}

    try:
        return await asyncio.to_thread(_sync_commit)
    except _sp.CalledProcessError as exc:
        raise RepoAnalyzerError(f"Git error: {exc.stderr or exc}", 400)


async def merge_session(session_id: str, target_branch: str) -> Dict[str, Any]:
    """Merge the session branch into *target_branch* and schedule reindex.

    Args:
        session_id:    Session UUID.
        target_branch: Branch name in the main clone to merge into.

    Returns:
        Merge result dict from :func:`worktree_service.merge_to_branch`.

    Raises:
        SessionNotFoundError: If session or worktree is missing.
        MergeConflictError:   If Git reports merge conflicts.
    """
    row = _require_session(session_id)
    wt_id = row.get("worktree_id")
    if wt_id is None:
        raise SessionNotFoundError(MSG_ORCHESTRATOR_SESSION_NO_WORKTREE)
    wt = session_db.find_worktree_by_id(str(wt_id))
    if wt is None:
        raise SessionNotFoundError(MSG_ORCHESTRATOR_WORKTREE_NOT_FOUND)
    repo = _require_repo(str(row["repo_id"]))

    def _merge() -> Dict[str, Any]:
        return worktree_service.merge_to_branch(
            repo["local_path"],
            wt["branch_name"],
            target_branch,
        )

    result = await asyncio.to_thread(_merge)
    if not result.get("merged"):
        raise MergeConflictError(
            MSG_ORCHESTRATOR_MERGE_CONFLICT_TEMPLATE.format(
                conflicts=result.get("conflicts"),
            ),
        )
    session_db.update_worktree_status(str(wt_id), WORKTREE_STATUS_MERGED)
    await trigger_reindex(str(row["repo_id"]))
    return dict(result)


async def create_session_pr(
    session_id: str,
    title: str,
    body: str,
    target_branch: str = "main",
) -> Dict[str, Any]:
    """Push the session branch and open a GitHub pull request.

    Args:
        session_id:    Session UUID.
        title:         PR title.
        body:          PR description (Markdown).
        target_branch: Base branch for the PR.

    Returns:
        Dict with ``pr_url``, ``pr_number``, ``branch``, ``base_branch``.

    Raises:
        SessionNotFoundError: If session or worktree is missing.
        RepoAnalyzerError:    If push or GitHub API call fails.
    """
    row = _require_session(session_id)
    wt_id = row.get("worktree_id")
    if wt_id is None:
        raise SessionNotFoundError(MSG_ORCHESTRATOR_SESSION_NO_WORKTREE)
    wt = session_db.find_worktree_by_id(str(wt_id))
    if wt is None:
        raise SessionNotFoundError(MSG_ORCHESTRATOR_WORKTREE_NOT_FOUND)

    wt_path = wt["worktree_path"]
    branch = wt["branch_name"]

    def _create_pr() -> Dict[str, Any]:
        return worktree_service.create_github_pr(
            wt_path, branch, target_branch, title, body,
        )

    try:
        return await asyncio.to_thread(_create_pr)
    except RuntimeError as exc:
        raise RepoAnalyzerError(str(exc), 400)


async def revert_session_changes(session_id: str) -> Dict[str, Any]:
    """Discard all uncommitted changes in the session worktree.

    Args:
        session_id: Session UUID.

    Returns:
        Dict with ``reverted`` flag and ``files_reverted`` count.

    Raises:
        SessionNotFoundError: If session or worktree is missing.
    """
    row = _require_session(session_id)
    wt_id = row.get("worktree_id")
    if wt_id is None:
        raise SessionNotFoundError(MSG_ORCHESTRATOR_SESSION_NO_WORKTREE)
    wt = session_db.find_worktree_by_id(str(wt_id))
    if wt is None:
        raise SessionNotFoundError(MSG_ORCHESTRATOR_WORKTREE_NOT_FOUND)
    path = wt["worktree_path"]
    count = await asyncio.to_thread(worktree_service.revert_all_changes, path)
    return {"session_id": session_id, "reverted": True, "files_reverted": count}


async def get_session_checkpoints(session_id: str) -> Dict[str, Any]:
    """List checkpoint commits in the session worktree.

    Args:
        session_id: Session UUID.

    Returns:
        Dict with ``checkpoints`` list.

    Raises:
        SessionNotFoundError: If session or worktree is missing.
    """
    row = _require_session(session_id)
    wt_id = row.get("worktree_id")
    if wt_id is None:
        raise SessionNotFoundError(MSG_ORCHESTRATOR_SESSION_NO_WORKTREE)
    wt = session_db.find_worktree_by_id(str(wt_id))
    if wt is None:
        raise SessionNotFoundError(MSG_ORCHESTRATOR_WORKTREE_NOT_FOUND)
    path = wt["worktree_path"]
    cps = await asyncio.to_thread(worktree_service.list_checkpoints, path)
    return {"session_id": session_id, "checkpoints": cps}


async def restore_session_checkpoint(session_id: str, step: int) -> Dict[str, Any]:
    """Restore the session worktree to a specific checkpoint step.

    Args:
        session_id: Session UUID.
        step:       Checkpoint step number to restore.

    Returns:
        Dict with ``restored_to_step`` and ``sha``.

    Raises:
        SessionNotFoundError: If session or worktree is missing.
        RepoAnalyzerError:    If the checkpoint is not found.
    """
    row = _require_session(session_id)
    wt_id = row.get("worktree_id")
    if wt_id is None:
        raise SessionNotFoundError(MSG_ORCHESTRATOR_SESSION_NO_WORKTREE)
    wt = session_db.find_worktree_by_id(str(wt_id))
    if wt is None:
        raise SessionNotFoundError(MSG_ORCHESTRATOR_WORKTREE_NOT_FOUND)
    path = wt["worktree_path"]

    cps = await asyncio.to_thread(worktree_service.list_checkpoints, path)
    target = next((c for c in cps if c["step"] == step), None)
    if target is None:
        raise RepoAnalyzerError(f"Checkpoint step {step} not found", 404)

    sha = await asyncio.to_thread(worktree_service.restore_checkpoint, path, target["sha"])
    return {"session_id": session_id, "restored_to_step": step, "sha": sha}


async def rerun_session_step(
    session_id: str,
    step: int,
    modified_args: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Re-run a specific tool call step by sending a structured follow-up.

    Args:
        session_id:    Session UUID.
        step:          Index into the agent_log to re-run.
        modified_args: Optional overrides for the tool arguments.

    Returns:
        Status dict from ``resume_session``.

    Raises:
        SessionNotFoundError: If session does not exist.
        RepoAnalyzerError:    If the step index is out of range.
    """
    row = _require_session(session_id)
    log = row.get("agent_log") or []
    if step < 0 or step >= len(log):
        raise RepoAnalyzerError(f"Step {step} out of range (0..{len(log) - 1})", 400)

    entry = log[step]
    tool = entry.get("tool", "unknown")
    args = modified_args if modified_args else entry.get("arguments", {})

    import json as _json
    args_text = _json.dumps(args, indent=2, ensure_ascii=False)
    message = (
        f"[RERUN] Re-run the failed step: {tool}\n"
        f"Arguments:\n{args_text}\n\n"
        f"Use these exact arguments and fix any issues that caused the previous failure."
    )
    return await resume_session(session_id, message)


async def cancel_session(session_id: str) -> None:
    """Remove the worktree and mark the session cancelled.

    Args:
        session_id: Session UUID.

    Returns:
        None

    Raises:
        SessionNotFoundError: If the session does not exist.
    """
    row = _require_session(session_id)
    repo = _require_repo(str(row["repo_id"]))
    await asyncio.to_thread(
        worktree_service.cleanup_worktree,
        repo["local_path"],
        session_id,
    )
    session_db.update_session_status(session_id, SESSION_STATUS_CANCELLED)
