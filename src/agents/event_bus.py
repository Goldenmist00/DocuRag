"""
event_bus.py
============
Lightweight per-session event queue for streaming agent activity to SSE clients.

Each active session gets a bounded ``asyncio.Queue``. The :class:`CodingAgent`
pushes events (tool starts, results, lint errors, completion) and the SSE
endpoint in ``session_controller`` consumes them.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_session_queues: Dict[str, asyncio.Queue] = {}


def get_or_create_queue(session_id: str, maxsize: int = 500) -> asyncio.Queue:
    """Return the event queue for *session_id*, creating one if needed.

    Args:
        session_id: Agent session UUID.
        maxsize: Upper bound on queued events before drops.

    Returns:
        The shared ``asyncio.Queue`` instance for this session.
    """
    if session_id not in _session_queues:
        _session_queues[session_id] = asyncio.Queue(maxsize=maxsize)
    return _session_queues[session_id]


def get_queue(session_id: str) -> Optional[asyncio.Queue]:
    """Return the queue if it exists, else ``None``.

    Args:
        session_id: Agent session UUID.

    Returns:
        Queue or ``None``.
    """
    return _session_queues.get(session_id)


def remove_queue(session_id: str) -> None:
    """Discard the queue when a session finishes.

    Args:
        session_id: Agent session UUID.
    """
    _session_queues.pop(session_id, None)


async def emit(session_id: str, event_type: str, data: Optional[Dict[str, Any]] = None) -> None:
    """Push an event to the session queue (non-blocking, drops on full).

    Must be called from the event loop thread (i.e. inside an ``async`` function).

    Args:
        session_id: Agent session UUID.
        event_type: Short event label (``tool_start``, ``tool_result``, etc.).
        data: Optional extra payload merged into the event dict.
    """
    queue = _session_queues.get(session_id)
    if queue is None:
        return
    event: Dict[str, Any] = {"type": event_type}
    if data:
        event.update(data)
    try:
        queue.put_nowait(event)
    except asyncio.QueueFull:
        logger.debug("Event queue full for session %s, dropping event %s", session_id, event_type)
