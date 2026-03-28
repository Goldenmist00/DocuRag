"""
github_controller.py
====================
GitHub OAuth endpoints for MindSync.

Handles the OAuth authorization flow:
  GET  /auth/github          — redirect user to GitHub authorization page
  GET  /auth/github/callback — exchange code for access token, store it
  GET  /auth/github/status   — check if a GitHub account is connected
  POST /auth/github/disconnect — remove stored token
"""

import logging
import os

import requests as _requests
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse

from src.db import github_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/github", tags=["GitHub OAuth"])

GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET", "")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")

GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"

SCOPES = "repo,read:user"


@router.get("", summary="Start GitHub OAuth flow")
async def github_auth_start():
    """Redirect the user to GitHub's authorization page.

    Returns:
        RedirectResponse to GitHub OAuth.

    Raises:
        HTTPException: 500 if GitHub credentials are not configured.
    """
    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="GitHub OAuth not configured — set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET",
        )

    redirect_uri = f"{BACKEND_URL}/auth/github/callback"
    auth_url = (
        f"{GITHUB_AUTH_URL}"
        f"?client_id={GITHUB_CLIENT_ID}"
        f"&scope={SCOPES}"
        f"&redirect_uri={redirect_uri}"
    )
    return RedirectResponse(url=auth_url)


@router.get("/callback", summary="GitHub OAuth callback")
async def github_auth_callback(code: str = Query(...)):
    """Exchange the authorization code for an access token.

    GitHub redirects here after the user authorizes. We exchange the
    ``code`` for an access token, fetch the user profile, store the
    token, and redirect to the frontend success page.

    Args:
        code: Authorization code from GitHub.

    Returns:
        RedirectResponse to the frontend with connection status.

    Raises:
        HTTPException: 400 if the token exchange fails.
    """
    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="GitHub OAuth not configured")

    token_resp = _requests.post(
        GITHUB_TOKEN_URL,
        headers={"Accept": "application/json"},
        data={
            "client_id": GITHUB_CLIENT_ID,
            "client_secret": GITHUB_CLIENT_SECRET,
            "code": code,
        },
        timeout=15,
    )

    if token_resp.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"GitHub token exchange failed: {token_resp.text[:300]}",
        )

    token_data = token_resp.json()
    access_token = token_data.get("access_token")
    if not access_token:
        error = token_data.get("error_description") or token_data.get("error", "unknown")
        raise HTTPException(status_code=400, detail=f"GitHub OAuth error: {error}")

    token_type = token_data.get("token_type", "bearer")
    scope = token_data.get("scope", "")

    user_resp = _requests.get(
        GITHUB_USER_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
        },
        timeout=10,
    )
    github_user = "unknown"
    if user_resp.status_code == 200:
        github_user = user_resp.json().get("login", "unknown")

    github_db.upsert_token(github_user, access_token, token_type, scope)

    logger.info("GitHub connected: user=%s scope=%s", github_user, scope)

    return RedirectResponse(
        url=f"{FRONTEND_URL}/auth/github/callback?status=success&user={github_user}"
    )


@router.get("/status", summary="Check GitHub connection status")
async def github_status():
    """Return whether a GitHub account is connected.

    Returns:
        Dict with ``connected`` flag and optional ``github_user``.
    """
    info = github_db.get_github_user()
    if info:
        return {"connected": True, **info}
    return {"connected": False}


@router.post("/disconnect", summary="Disconnect GitHub account")
async def github_disconnect():
    """Remove the stored GitHub token.

    Returns:
        Dict with ``disconnected`` flag.
    """
    info = github_db.get_github_user()
    if info:
        github_db.delete_token(info["github_user"])
        return {"disconnected": True, "github_user": info["github_user"]}
    return {"disconnected": False, "message": "No GitHub account connected"}
