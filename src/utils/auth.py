"""
auth.py
=======
FastAPI dependency for extracting the authenticated user identity.

The frontend sends the logged-in user's email in the ``X-User-Id``
header. This module provides a reusable dependency that extracts it.
"""

from typing import Optional

from fastapi import Header


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
