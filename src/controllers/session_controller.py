"""
session_controller.py
=====================
HTTP request/response handlers for ``/repos/{repo_id}/sessions/*`` endpoints.

Controller layer only — delegates all business logic to the orchestrator
and coding agent services.
"""

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException
from starlette.responses import StreamingResponse

from src.controllers.repo_schemas import (
    CommitRequest,
    MergeRequest,
    PullRequestRequest,
    RerunRequest,
    RestoreRequest,
    SessionCreate,
    SessionMessageRequest,
)
from src.utils.repo_errors import RepoAnalyzerError
from src.utils.repo_validation import validate_repo_id, validate_session_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/repos/{repo_id}/sessions", tags=["sessions"])


@router.post("", status_code=202)
async def create_session(repo_id: str, body: SessionCreate):
    """Create a new coding-agent session with its own worktree.

    Args:
        repo_id: UUID of the repo.
        body:    ``SessionCreate`` with ``task``.

    Returns:
        Session dict with ``id``, ``status``, ``worktree_branch``.

    Raises:
        HTTPException: 429 if session limit reached.
    """
    from src.agents.orchestrator import create_agent_session

    try:
        validate_repo_id(repo_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        return await create_agent_session(repo_id, body.task, notebook_id=body.notebook_id)
    except RepoAnalyzerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.get("")
async def list_sessions(repo_id: str):
    """List all agent sessions for a repository.

    Args:
        repo_id: UUID of the repo.

    Returns:
        List of session summary dicts.
    """
    from src.db import session_db

    try:
        validate_repo_id(repo_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return session_db.list_by_repo(repo_id)


@router.get("/{session_id}")
async def get_session(repo_id: str, session_id: str):
    """Get detailed status of a single agent session.

    Args:
        repo_id:    UUID of the repo.
        session_id: UUID of the session.

    Returns:
        Full session dict.

    Raises:
        HTTPException: 404 if not found.
    """
    from src.db import session_db

    try:
        validate_repo_id(repo_id)
        validate_session_id(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    row = session_db.find_by_id(session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return row


@router.get("/{session_id}/stream")
async def stream_session_events(repo_id: str, session_id: str):
    """Stream real-time agent events via Server-Sent Events.

    Events include ``thinking``, ``tool_start``, ``tool_result``,
    ``lint_error``, ``ask_user``, ``done``, and ``error``.
    A ``heartbeat`` is sent every 15 seconds to keep the connection alive.

    Args:
        repo_id:    UUID of the repo.
        session_id: UUID of the session.

    Returns:
        ``text/event-stream`` response.
    """
    from src.agents.event_bus import get_or_create_queue

    try:
        validate_repo_id(repo_id)
        validate_session_id(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    queue = get_or_create_queue(session_id)
    terminal_events = frozenset({"done", "error", "ask_user"})

    async def _event_generator():
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15.0)
                yield f"data: {json.dumps(event, default=str)}\n\n"
                if event.get("type") in terminal_events:
                    break
            except asyncio.TimeoutError:
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{session_id}/message", status_code=202)
async def send_message(repo_id: str, session_id: str, body: SessionMessageRequest):
    """Send a follow-up message to a running or completed session.

    Args:
        repo_id:    UUID of the repo.
        session_id: UUID of the session.
        body:       ``SessionMessageRequest`` with ``message``.

    Returns:
        Status acknowledgement.
    """
    from src.agents.orchestrator import resume_session

    try:
        validate_repo_id(repo_id)
        validate_session_id(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        return await resume_session(session_id, body.message)
    except RepoAnalyzerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.post("/{session_id}/stop")
async def stop_session(repo_id: str, session_id: str):
    """Stop a running agent session.

    Args:
        repo_id:    UUID of the repo.
        session_id: UUID of the session.

    Returns:
        Status dict with ``session_id``, ``status``, ``message``.

    Raises:
        HTTPException: 400 if session is not running, 404 if not found.
    """
    from src.agents.orchestrator import stop_session as _stop_session

    try:
        validate_repo_id(repo_id)
        validate_session_id(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        return await _stop_session(session_id)
    except RepoAnalyzerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.get("/{session_id}/diff")
async def get_session_diff(repo_id: str, session_id: str):
    """Get the structured diff of changes made by an agent session.

    Args:
        repo_id:    UUID of the repo.
        session_id: UUID of the session.

    Returns:
        Diff response with files, insertions, deletions, and summary.

    Raises:
        HTTPException: 404 if not found.
    """
    from src.agents.orchestrator import get_session_diff as _get_diff

    try:
        validate_repo_id(repo_id)
        validate_session_id(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        return await _get_diff(session_id)
    except RepoAnalyzerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.post("/{session_id}/commit")
async def commit_session(repo_id: str, session_id: str, body: CommitRequest):
    """Commit the agent's uncommitted changes in the session worktree.

    Args:
        repo_id:    UUID of the repo.
        session_id: UUID of the session.
        body:       ``CommitRequest`` with ``message`` and optional ``new_branch``.

    Returns:
        Dict with ``commit_hash`` and ``branch``.

    Raises:
        HTTPException: 404 if session not found, 400 on git errors.
    """
    from src.agents.orchestrator import commit_session_changes

    try:
        validate_repo_id(repo_id)
        validate_session_id(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        return await commit_session_changes(
            session_id, body.message, new_branch=body.new_branch,
        )
    except RepoAnalyzerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.post("/{session_id}/merge")
async def merge_session(repo_id: str, session_id: str, body: MergeRequest):
    """Merge the agent session's worktree branch into the target branch.

    Args:
        repo_id:    UUID of the repo.
        session_id: UUID of the session.
        body:       ``MergeRequest`` with ``target_branch``.

    Returns:
        Merge result with ``merged``, ``commit_hash``, ``conflicts``.
    """
    from src.agents.orchestrator import merge_session as _merge

    try:
        validate_repo_id(repo_id)
        validate_session_id(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        return await _merge(session_id, body.target_branch)
    except RepoAnalyzerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.post("/{session_id}/pull-request")
async def create_pull_request(repo_id: str, session_id: str, body: PullRequestRequest):
    """Push the session branch and open a GitHub pull request.

    Args:
        repo_id:    UUID of the repo.
        session_id: UUID of the session.
        body:       ``PullRequestRequest`` with ``title``, ``body``, ``target_branch``.

    Returns:
        Dict with ``pr_url``, ``pr_number``, ``branch``, ``base_branch``.

    Raises:
        HTTPException: 400 on push/API failure, 404 if session not found.
    """
    from src.agents.orchestrator import create_session_pr

    try:
        validate_repo_id(repo_id)
        validate_session_id(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        return await create_session_pr(
            session_id, body.title, body.body, body.target_branch,
        )
    except RepoAnalyzerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.post("/{session_id}/revert")
async def revert_session(repo_id: str, session_id: str):
    """Discard all uncommitted changes in the session worktree.

    Args:
        repo_id:    UUID of the repo.
        session_id: UUID of the session.

    Returns:
        Dict with ``reverted`` flag and ``files_reverted`` count.

    Raises:
        HTTPException: 404 if session not found.
    """
    from src.agents.orchestrator import revert_session_changes

    try:
        validate_repo_id(repo_id)
        validate_session_id(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        return await revert_session_changes(session_id)
    except RepoAnalyzerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.get("/{session_id}/checkpoints")
async def list_checkpoints(repo_id: str, session_id: str):
    """List checkpoint commits for a session.

    Args:
        repo_id:    UUID of the repo.
        session_id: UUID of the session.

    Returns:
        Dict with ``checkpoints`` list.

    Raises:
        HTTPException: 404 if session not found.
    """
    from src.agents.orchestrator import get_session_checkpoints

    try:
        validate_repo_id(repo_id)
        validate_session_id(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        return await get_session_checkpoints(session_id)
    except RepoAnalyzerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.post("/{session_id}/restore")
async def restore_checkpoint(repo_id: str, session_id: str, body: RestoreRequest):
    """Restore the session worktree to a specific checkpoint.

    Args:
        repo_id:    UUID of the repo.
        session_id: UUID of the session.
        body:       ``RestoreRequest`` with ``step``.

    Returns:
        Dict with ``restored_to_step`` and ``sha``.

    Raises:
        HTTPException: 404 if checkpoint not found.
    """
    from src.agents.orchestrator import restore_session_checkpoint

    try:
        validate_repo_id(repo_id)
        validate_session_id(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        return await restore_session_checkpoint(session_id, body.step)
    except RepoAnalyzerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.post("/{session_id}/rerun")
async def rerun_step(repo_id: str, session_id: str, body: RerunRequest):
    """Re-run a specific tool call step with optional argument overrides.

    Args:
        repo_id:    UUID of the repo.
        session_id: UUID of the session.
        body:       ``RerunRequest`` with ``step`` and optional ``modified_args``.

    Returns:
        Status acknowledgement.

    Raises:
        HTTPException: 400 if step index out of range.
    """
    from src.agents.orchestrator import rerun_session_step

    try:
        validate_repo_id(repo_id)
        validate_session_id(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        return await rerun_session_step(session_id, body.step, body.modified_args)
    except RepoAnalyzerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.delete("/{session_id}", status_code=204)
async def cancel_session(repo_id: str, session_id: str):
    """Cancel a session and clean up its worktree.

    Args:
        repo_id:    UUID of the repo.
        session_id: UUID of the session.

    Raises:
        HTTPException: 404 if not found.
    """
    from src.agents.orchestrator import cancel_session as _cancel

    try:
        validate_repo_id(repo_id)
        validate_session_id(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        await _cancel(session_id)
    except RepoAnalyzerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
