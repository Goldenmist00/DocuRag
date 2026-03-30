"""
llm_semaphore.py
================
Process-wide semaphore that gates **all** outbound LLM API calls.

Every module that calls NVIDIA / Groq (``generator.py``,
``agents/llm_client.py``, ``agents/ingest_agent.py``) must acquire
this single semaphore so total in-flight requests never exceed the
provider's rate limit regardless of how many thread pools are active.

The limit is read from ``LLM_SEMAPHORE_LIMIT`` in ``repo_constants``
(default 5) and can be overridden via the ``LLM_CONCURRENCY`` env var.
"""

import os
import threading

from src.config.repo_constants import LLM_SEMAPHORE_LIMIT

_limit = int(os.environ.get("LLM_CONCURRENCY", str(LLM_SEMAPHORE_LIMIT)))

LLM_SEMAPHORE: threading.Semaphore = threading.Semaphore(_limit)
"""Acquire before every LLM HTTP request; release in ``finally``."""
