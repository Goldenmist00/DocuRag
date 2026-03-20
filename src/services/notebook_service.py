"""
notebook_service.py
===================
Business logic for notebook operations.

Validates input and delegates to notebook_db for persistence.
"""

import logging
from typing import Dict, List, Optional

from src.db import notebook_db

logger = logging.getLogger(__name__)

MAX_TITLE_LENGTH = 200


def create_notebook(title: Optional[str] = None) -> Dict:
    """
    Create a new notebook with an optional title.

    Args:
        title: Display title (defaults to "Untitled notebook").

    Returns:
        Created notebook dict.

    Raises:
        ValueError: If title exceeds MAX_TITLE_LENGTH.
    """
    clean_title = (title or "").strip() or "Untitled notebook"
    if len(clean_title) > MAX_TITLE_LENGTH:
        raise ValueError(f"Title must be {MAX_TITLE_LENGTH} characters or fewer.")

    nb = notebook_db.create_notebook(clean_title)
    logger.info("Created notebook %s: %s", nb["id"], nb["title"])
    return nb


def list_notebooks() -> List[Dict]:
    """
    List all notebooks, most recently updated first.

    Returns:
        List of notebook dicts with source_count.
    """
    return notebook_db.list_notebooks()


def get_notebook(notebook_id: str) -> Dict:
    """
    Fetch a single notebook by ID.

    Args:
        notebook_id: UUID string.

    Returns:
        Notebook dict.

    Raises:
        ValueError: If notebook is not found.
    """
    nb = notebook_db.get_notebook(notebook_id)
    if not nb:
        raise ValueError(f"Notebook not found: {notebook_id}")
    return nb


def update_title(notebook_id: str, title: str) -> Dict:
    """
    Rename a notebook.

    Args:
        notebook_id: UUID string.
        title: New title.

    Returns:
        Updated notebook dict.

    Raises:
        ValueError: If not found or title is invalid.
    """
    clean = title.strip()
    if not clean:
        raise ValueError("Title cannot be empty.")
    if len(clean) > MAX_TITLE_LENGTH:
        raise ValueError(f"Title must be {MAX_TITLE_LENGTH} characters or fewer.")

    nb = notebook_db.update_notebook(notebook_id, clean)
    if not nb:
        raise ValueError(f"Notebook not found: {notebook_id}")
    logger.info("Renamed notebook %s -> %s", notebook_id, clean)
    return nb


def delete_notebook(notebook_id: str) -> None:
    """
    Delete a notebook and all associated sources/chunks.

    Args:
        notebook_id: UUID string.

    Raises:
        ValueError: If notebook is not found.
    """
    deleted = notebook_db.delete_notebook(notebook_id)
    if not deleted:
        raise ValueError(f"Notebook not found: {notebook_id}")
    logger.info("Deleted notebook %s", notebook_id)
