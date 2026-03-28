"""
repo_schemas.py
===============
Pydantic request/response models for repo analyzer endpoints.

Keeps controllers clean by separating schema definitions into
their own module (single-responsibility principle).
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class RepoCreate(BaseModel):
    """Request body for ``POST /repos``."""

    remote_url: str = Field(
        ..., min_length=10, description="GitHub repository HTTPS URL",
    )
    auth_token: Optional[str] = Field(
        None, description="GitHub PAT for private repos",
    )


class RepoResponse(BaseModel):
    """Standard response body for repo endpoints."""

    id: str
    name: str
    remote_url: str
    indexing_status: str
    total_files: int
    indexed_files: int
    last_indexed_at: Optional[str] = None


class RepoQueryRequest(BaseModel):
    """Request body for ``POST /repos/{id}/query``."""

    question: str = Field(..., min_length=3, max_length=2000)


class RepoQueryResponse(BaseModel):
    """Response body for repo query endpoints."""

    answer: str
    cited_files: List[str]
    relevant_memories: List[Dict[str, Any]]


class SessionCreate(BaseModel):
    """Request body for ``POST /repos/{id}/sessions``."""

    task: str = Field(..., min_length=5, max_length=5000)
    notebook_id: Optional[str] = Field(
        None, description="Import planning context from this notebook session",
    )


class SessionResponse(BaseModel):
    """Response body for session endpoints."""

    id: str
    status: str
    task_description: str
    current_step: Optional[str] = None
    agent_log: List[Dict[str, Any]] = []
    plan: List[Dict[str, Any]] = []


class SessionMessageRequest(BaseModel):
    """Request body for ``POST /repos/{id}/sessions/{sid}/message``."""

    message: str = Field(..., min_length=1, max_length=5000)


class SessionDiffResponse(BaseModel):
    """Response body for ``GET /sessions/{id}/diff``."""

    files_changed: int
    insertions: int
    deletions: int
    diff_text: str
    files: List[Dict[str, Any]]
    agent_summary: str


class CommitRequest(BaseModel):
    """Request body for ``POST /sessions/{id}/commit``."""

    message: str = Field(..., min_length=1, max_length=500, description="Commit message")
    new_branch: Optional[str] = Field(
        None,
        description="If provided, create this branch before committing",
    )


class MergeRequest(BaseModel):
    """Request body for ``POST /sessions/{id}/merge``."""

    target_branch: str = Field("main", description="Branch to merge into")


class MergeResponse(BaseModel):
    """Response body for merge endpoint."""

    merged: bool
    commit_hash: Optional[str] = None
    conflicts: List[str] = []


class RestoreRequest(BaseModel):
    """Request body for ``POST /sessions/{id}/restore``."""

    step: int = Field(..., ge=0, description="Checkpoint step number to restore to")


class RerunRequest(BaseModel):
    """Request body for ``POST /sessions/{id}/rerun``."""

    step: int = Field(..., ge=0, description="Step index from agent_log to re-run")
    modified_args: Optional[Dict[str, Any]] = Field(
        None, description="Overridden arguments for the tool call (optional)",
    )


class PullRequestRequest(BaseModel):
    """Request body for ``POST /sessions/{id}/pull-request``."""

    title: str = Field(..., min_length=1, max_length=256, description="PR title")
    body: str = Field("", max_length=10000, description="PR description (Markdown)")
    target_branch: str = Field("main", description="Base branch for the PR")


class ErrorResponse(BaseModel):
    """Standard error response body."""

    error: str
    details: Optional[str] = None
