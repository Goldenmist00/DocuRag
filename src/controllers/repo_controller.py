"""
repo_controller.py
==================
HTTP request/response handlers for ``/repos/*`` endpoints.

This is the controller layer: it parses the request, calls ONE service
method, and returns the response.  **No business logic lives here.**
"""

import logging
from fastapi import APIRouter, Depends, HTTPException

from src.controllers.repo_schemas import (
    ErrorResponse,
    RepoCreate,
    RepoQueryRequest,
)
from src.utils.auth import require_current_user
from src.utils.repo_errors import RepoAnalyzerError
from src.utils.repo_validation import validate_repo_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/repos", tags=["repos"])


@router.post("", status_code=202, responses={409: {"model": ErrorResponse}})
async def create_repo(body: RepoCreate, user_id: str = Depends(require_current_user)):
    """Register and clone a GitHub repository.

    Args:
        body:    ``RepoCreate`` with ``remote_url`` and optional ``auth_token``.
        user_id: Authenticated user email (injected via dependency).

    Returns:
        Repo dict with ``id`` and ``status``.

    Raises:
        HTTPException: 409 if already exists, 502 if clone fails.
    """
    from src.agents.orchestrator import register_repo

    try:
        return await register_repo(body.remote_url, body.auth_token, user_id=user_id)
    except RepoAnalyzerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.get("")
async def list_repos(user_id: str = Depends(require_current_user)):
    """Return repos for the authenticated user, ordered by creation date.

    Uses the async DB pool so the event loop is never blocked by
    this high-frequency polling endpoint.

    Args:
        user_id: Authenticated user email (injected via dependency).

    Returns:
        List of repo dicts.
    """
    from src.db import repo_db

    try:
        return await repo_db.async_list_all(user_id=user_id)
    except RuntimeError:
        return repo_db.list_all(user_id=user_id)


@router.get("/{repo_id}")
async def get_repo(repo_id: str):
    """Get details and indexing progress for a single repo.

    Args:
        repo_id: UUID of the repo.

    Returns:
        Full repo dict.

    Raises:
        HTTPException: 404 if not found.
    """
    from src.db import repo_db

    try:
        validate_repo_id(repo_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        row = await repo_db.async_find_by_id(repo_id)
    except RuntimeError:
        row = repo_db.find_by_id(repo_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Repo not found")
    return row


@router.post("/{repo_id}/reindex", status_code=202)
async def reindex_repo(repo_id: str):
    """Trigger an incremental re-index of a repository.

    Args:
        repo_id: UUID of the repo.

    Returns:
        Status acknowledgement.

    Raises:
        HTTPException: 404 if not found.
    """
    from src.agents.orchestrator import trigger_reindex

    try:
        validate_repo_id(repo_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        return await trigger_reindex(repo_id)
    except RepoAnalyzerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.post("/{repo_id}/retry", status_code=202)
async def retry_repo(repo_id: str, user_id: str = Depends(require_current_user)):
    """Retry a failed clone/index pipeline for a repository.

    Args:
        repo_id: UUID of the repo.
        user_id: Authenticated user email (injected via dependency).

    Returns:
        Status acknowledgement.

    Raises:
        HTTPException: 404 if not found, 502 if retry fails to schedule.
    """
    from src.agents.orchestrator import trigger_retry

    try:
        validate_repo_id(repo_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        return await trigger_retry(repo_id)
    except RepoAnalyzerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.delete("/{repo_id}", status_code=204)
async def delete_repo(repo_id: str):
    """Delete a repo and all associated data.

    Args:
        repo_id: UUID of the repo.

    Raises:
        HTTPException: 404 if not found.
    """
    from src.db import repo_db

    try:
        validate_repo_id(repo_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    deleted = repo_db.delete(repo_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Repo not found")


@router.get("/{repo_id}/context")
async def get_repo_context(repo_id: str):
    """Return the global context snapshot for a repo.

    Args:
        repo_id: UUID of the repo.

    Returns:
        Repo context dict.

    Raises:
        HTTPException: 404 if not found.
    """
    from src.db import repo_context_db

    try:
        validate_repo_id(repo_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    ctx = repo_context_db.find_by_repo_id(repo_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Context not found")
    return ctx


@router.post("/{repo_id}/context/refresh", status_code=202)
async def refresh_context(repo_id: str):
    """Re-run the consolidation agent to refresh global context.

    Args:
        repo_id: UUID of the repo.

    Returns:
        Status acknowledgement.

    Raises:
        HTTPException: 404 if not found.
    """
    from src.agents.orchestrator import trigger_consolidation

    try:
        validate_repo_id(repo_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        return await trigger_consolidation(repo_id)
    except RepoAnalyzerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.post("/{repo_id}/query")
async def query_repo(repo_id: str, body: RepoQueryRequest):
    """Ask a question about the repository.

    Args:
        repo_id: UUID of the repo.
        body:    ``RepoQueryRequest`` with ``question``.

    Returns:
        Answer with cited files and relevant memories.

    Raises:
        HTTPException: 404 if not found.
    """
    from src.agents.query_agent import answer_question

    try:
        validate_repo_id(repo_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        return answer_question(repo_id, body.question)
    except RepoAnalyzerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.get("/{repo_id}/files")
async def list_repo_files(repo_id: str):
    """List all indexed files with their LLM-extracted summaries.

    Args:
        repo_id: UUID of the repo.

    Returns:
        List of file memory summaries.

    Raises:
        HTTPException: 404 if not found.
    """
    from src.db import repo_memory_db

    try:
        validate_repo_id(repo_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return repo_memory_db.list_summaries(repo_id)


@router.get("/{repo_id}/files/{file_path:path}/content")
async def get_file_content(repo_id: str, file_path: str):
    """Return raw content of a single file from the local clone.

    Args:
        repo_id:   UUID of the repo.
        file_path: Repo-relative file path.

    Returns:
        Dict with path, content, size_bytes, and truncated flag.

    Raises:
        HTTPException: 400/403/404 on bad input or missing file.
    """
    from src.repo.repo_file_service import read_file_content

    try:
        validate_repo_id(repo_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        return read_file_content(repo_id, file_path)
    except RepoAnalyzerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
