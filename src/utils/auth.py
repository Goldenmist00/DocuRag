"""
auth.py
=======
FastAPI dependencies for extracting the authenticated user identity.

The frontend sends the logged-in user's email in the ``X-User-Id``
header.  Two dependency variants are provided:

- ``get_current_user`` — lenient; returns ``None`` when the header is
  absent (for endpoints that can optionally personalise responses).
- ``require_current_user`` — strict; raises HTTP 401 when the header
  is absent (for endpoints that must not leak cross-user data).
"""

from typing import Optional

from fastapi import Header, HTTPException


async def get_current_user(x_user_id: Optional[str] = Header(None)) -> Optional[str]:
    """Extract the current user's email from the ``X-User-Id`` header.

    Args:
        x_user_id: Value of the ``X-User-Id`` header (injected by FastAPI).

    Returns:
        The user email string, or ``None`` if the header is absent.
    """
    if x_user_id and x_user_id.strip():
        return x_user_id.strip()
    return None


async def require_current_user(x_user_id: Optional[str] = Header(None)) -> str:
    """Extract and require the current user's email.

    Use this dependency on endpoints that must not serve data to
    unauthenticated callers.

    Args:
        x_user_id: Value of the ``X-User-Id`` header (injected by FastAPI).

    Returns:
        The user email string.

    Raises:
        HTTPException: 401 if the header is missing or empty.
    """
    if x_user_id and x_user_id.strip():
        return x_user_id.strip()
    raise HTTPException(status_code=401, detail="Authentication required")
