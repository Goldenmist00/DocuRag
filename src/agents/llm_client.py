"""
Non-streaming chat completions with OpenAI-style tools for the coding agent.

Uses NVIDIA first, then Groq, reusing endpoint and model constants from
``src.generator``. Concurrency is limited by a process-wide semaphore.
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
from typing import Any, Optional

import requests

from src.config.repo_constants import (
    AGENT_CHAT_COMPLETION_429_MAX_RETRIES,
    AGENT_CHAT_COMPLETION_INITIAL_BACKOFF_SECONDS,
    AGENT_COMPLETION_MAX_TOKENS,
    INGEST_COMPLETION_TEMPERATURE,
    INGEST_COMPLETION_TOP_P,
    INGEST_HTTP_TIMEOUT_SECONDS,
    MAX_AGENT_TURNS,
    NVIDIA_API_KEY_SENTINEL,
)
from src.config.llm_semaphore import LLM_SEMAPHORE
from src.generator import GEMINI_MODEL, GEMINI_URL, GROQ_MODEL, GROQ_URL, NVIDIA_MODEL, NVIDIA_URL

logger = logging.getLogger(__name__)


def _nvidia_key_valid(raw: str) -> bool:
    """Return True if *raw* is a usable NVIDIA API key.

    Args:
        raw: Value from ``NVIDIA_API_KEY`` (may be empty or a placeholder).

    Returns:
        Whether NVIDIA requests should be attempted.

    Raises:
        This function does not raise.
    """
    s = (raw or "").strip()
    return bool(s and s != NVIDIA_API_KEY_SENTINEL)


def _groq_key_valid(raw: str) -> bool:
    """Return True if *raw* is a non-empty Groq API key.

    Args:
        raw: Value from ``GROQ_API_KEY``.

    Returns:
        Whether Groq requests should be attempted.

    Raises:
        This function does not raise.
    """
    return bool((raw or "").strip())


def _tools_api_payload(tools: Optional[list]) -> Optional[list[dict[str, Any]]]:
    """Wrap tool schemas in OpenAI ``tools`` list format.

    Args:
        tools: Raw schemas with ``name``, ``description``, ``parameters``.

    Returns:
        List of ``{"type": "function", "function": {...}}`` or ``None``.

    Raises:
        This function does not raise.
    """
    if not tools:
        return None
    wrapped: list[dict[str, Any]] = []
    for schema in tools:
        wrapped.append(
            {
                "type": "function",
                "function": {
                    "name": schema["name"],
                    "description": schema["description"],
                    "parameters": schema["parameters"],
                },
            }
        )
    return wrapped


def _post_chat_completion(
    url: str,
    headers: dict[str, str],
    model: str,
    messages: list,
    tools_payload: Optional[list[dict[str, Any]]],
) -> requests.Response:
    """POST a non-streaming chat completion and return the HTTP response.

    Args:
        url: Provider chat completions URL.
        headers: Request headers including authorization.
        model: Model id for the provider.
        messages: OpenAI-style message list.
        tools_payload: Optional wrapped tools list.

    Returns:
        The ``requests.Response`` object (not yet validated).

    Raises:
        requests.RequestException: On connection errors.
    """
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "max_tokens": AGENT_COMPLETION_MAX_TOKENS,
        "temperature": INGEST_COMPLETION_TEMPERATURE,
        "top_p": INGEST_COMPLETION_TOP_P,
    }
    if tools_payload:
        body["tools"] = tools_payload
    return requests.post(url, headers=headers, json=body, timeout=INGEST_HTTP_TIMEOUT_SECONDS)


def _request_json_with_429_retries(
    url: str,
    headers: dict[str, str],
    model: str,
    messages: list,
    tools_payload: Optional[list[dict[str, Any]]],
) -> dict[str, Any]:
    """Send completion request, retrying HTTP 429 with exponential backoff.

    Args:
        url: Provider URL.
        headers: Request headers.
        model: Model name.
        messages: Message list.
        tools_payload: Optional tools list.

    Returns:
        Parsed JSON object from the response body.

    Raises:
        requests.HTTPError: If a non-429 HTTP error occurs.
        requests.RequestException: On repeated failures after retries.
        ValueError: If the response body is not valid JSON.
    """
    delay = AGENT_CHAT_COMPLETION_INITIAL_BACKOFF_SECONDS
    last_exc: Optional[BaseException] = None
    for attempt in range(AGENT_CHAT_COMPLETION_429_MAX_RETRIES + 1):
        resp = _post_chat_completion(url, headers, model, messages, tools_payload)
        if resp.status_code == 429:
            last_exc = requests.HTTPError(
                f"429 Too Many Requests for {url}", response=resp
            )
            if attempt < AGENT_CHAT_COMPLETION_429_MAX_RETRIES:
                jitter = random.uniform(0, delay)
                wait = delay + jitter
                logger.warning(
                    "LLM 429 on attempt %s/%s — sleeping %.2fs",
                    attempt + 1,
                    AGENT_CHAT_COMPLETION_429_MAX_RETRIES + 1,
                    wait,
                )
                time.sleep(wait)
                delay *= 2
            continue
        if resp.status_code >= 400:
            body_preview = (resp.text or "")[:500]
            logger.warning(
                "LLM API %d from %s: %s", resp.status_code, url, body_preview,
            )
        resp.raise_for_status()
        return resp.json()
    assert last_exc is not None
    raise last_exc


def _gemini_key_valid(raw: str) -> bool:
    """Return True if *raw* is a non-empty Gemini API key.

    Args:
        raw: Value from ``GEMINI_API_KEY``.

    Returns:
        Whether Gemini requests should be attempted.
    """
    return bool((raw or "").strip())


def _dispatch_chat_providers(
    messages: list,
    tools_payload: Optional[list[dict[str, Any]]],
    nvidia_key: str,
    groq_key: str,
) -> dict[str, Any]:
    """Try Gemini, then Groq, then NVIDIA for a chat completion.

    Args:
        messages: OpenAI-style message list.
        tools_payload: Wrapped tools or ``None``.
        nvidia_key: Raw ``NVIDIA_API_KEY`` value.
        groq_key: Raw ``GROQ_API_KEY`` value.

    Returns:
        Parsed JSON response dict.

    Raises:
        RuntimeError: If all providers fail.
        requests.HTTPError: On non-retryable HTTP errors.
        ValueError: If JSON decoding of the response body fails.
    """
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    last_exc: Optional[Exception] = None

    if _gemini_key_valid(gemini_key):
        headers = {
            "Authorization": f"Bearer {gemini_key.strip()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        try:
            return _request_json_with_429_retries(
                GEMINI_URL, headers, GEMINI_MODEL, messages, tools_payload
            )
        except Exception as exc:
            logger.warning("Gemini chat completion failed: %s", exc)
            last_exc = exc

    if _groq_key_valid(groq_key):
        headers = {
            "Authorization": f"Bearer {groq_key.strip()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        try:
            return _request_json_with_429_retries(
                GROQ_URL, headers, GROQ_MODEL, messages, tools_payload
            )
        except Exception as exc:
            logger.warning("Groq chat completion failed: %s", exc)
            last_exc = exc

    if _nvidia_key_valid(nvidia_key):
        headers = {
            "Authorization": f"Bearer {nvidia_key.strip()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        try:
            return _request_json_with_429_retries(
                NVIDIA_URL, headers, NVIDIA_MODEL, messages, tools_payload
            )
        except Exception as exc:
            logger.warning("NVIDIA chat completion failed: %s", exc)
            last_exc = exc

    raise RuntimeError(
        f"All LLM providers failed. Last error: {last_exc}"
    )


def chat_completion(messages: list, tools: list = None) -> dict:
    """Run a non-streaming chat completion; NVIDIA first, then Groq fallback.

    Args:
        messages: OpenAI-style ``messages`` list.
        tools: Optional list of tool schemas (``name``, ``description``, ``parameters``).

    Returns:
        Full parsed JSON response dict from the provider.

    Raises:
        ValueError: If neither ``NVIDIA_API_KEY`` nor ``GROQ_API_KEY`` is usable.
        RuntimeError: If all attempts against all providers fail.
        requests.HTTPError: Propagated for non-429 HTTP errors on the last try.
    """
    nvidia_key = os.getenv("NVIDIA_API_KEY", "")
    groq_key = os.getenv("GROQ_API_KEY", "")
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    if not _gemini_key_valid(gemini_key) and not _nvidia_key_valid(nvidia_key) and not _groq_key_valid(groq_key):
        raise ValueError(
            "No LLM API key found. Set GEMINI_API_KEY, NVIDIA_API_KEY, or GROQ_API_KEY."
        )
    tools_payload = _tools_api_payload(tools)
    if len(messages) > MAX_AGENT_TURNS * 4:
        logger.warning(
            "chat_completion message count %s is large relative to MAX_AGENT_TURNS=%s",
            len(messages),
            MAX_AGENT_TURNS,
        )
    LLM_SEMAPHORE.acquire()
    try:
        return _dispatch_chat_providers(messages, tools_payload, nvidia_key, groq_key)
    finally:
        LLM_SEMAPHORE.release()


def extract_tool_calls(response: dict) -> list:
    """Extract and normalize ``tool_calls`` from a chat completion response.

    Args:
        response: Parsed JSON from ``chat_completion``.

    Returns:
        List of dicts with keys ``id``, ``name``, ``arguments`` (parsed object).

    Raises:
        This function does not raise; malformed entries are skipped with logging.
    """
    try:
        choices = response.get("choices") or []
        if not choices:
            return []
        message = (choices[0] or {}).get("message") or {}
        raw_calls = message.get("tool_calls") or []
    except (TypeError, AttributeError):
        return []
    out: list[dict[str, Any]] = []
    for call in raw_calls:
        if not isinstance(call, dict):
            continue
        fn = call.get("function") or {}
        if not isinstance(fn, dict):
            continue
        name = fn.get("name") or ""
        args_raw = fn.get("arguments") or "{}"
        if isinstance(args_raw, dict):
            args_obj = args_raw
        else:
            try:
                args_obj = json.loads(str(args_raw))
            except json.JSONDecodeError:
                logger.warning("Invalid tool arguments JSON for tool %r", name)
                args_obj = {}
        out.append(
            {
                "id": call.get("id") or "",
                "name": name,
                "arguments": args_obj if isinstance(args_obj, dict) else {},
            }
        )
    return out


def get_assistant_content(response: dict) -> str:
    """Return assistant text content from a completion response.

    Args:
        response: Parsed JSON from ``chat_completion``.

    Returns:
        ``choices[0].message.content`` or empty string if missing.

    Raises:
        This function does not raise.
    """
    try:
        choices = response.get("choices") or []
        if not choices:
            return ""
        message = (choices[0] or {}).get("message") or {}
        content = message.get("content")
        if content is None:
            return ""
        return str(content)
    except (TypeError, AttributeError):
        return ""
