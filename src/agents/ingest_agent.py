"""
ingest_agent.py
===============
Service-layer ingestion: walk a repo, analyze each file with an LLM, and
persist structured memories via ``repo_memory_db``.
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from src.config.repo_constants import (
    AST_ONLY_EXTENSIONS,
    AST_ONLY_MAX_FILE_SIZE,
    INGEST_COMPLETION_MAX_TOKENS,
    INGEST_COMPLETION_TEMPERATURE,
    INGEST_COMPLETION_TOP_P,
    INGEST_HTTP_TIMEOUT_SECONDS,
    INGEST_LLM_INITIAL_BACKOFF_SECONDS,
    INGEST_LLM_MAX_RETRIES,
    INGEST_LLM_RETRY_JITTER_NARROW,
    INGEST_LLM_RETRY_JITTER_WIDE,
    INGEST_PARSE_FALLBACK_SNIPPET_CHARS,
    LLM_SEMAPHORE_LIMIT,
    MAX_CONCURRENT_INGEST_WORKERS,
    MAX_FILE_SIZE_BYTES,
    NVIDIA_API_KEY_SENTINEL,
    REPO_INDEXING_STATUS_FAILED,
    REPO_INDEXING_STATUS_INDEXING,
)
from src.db import repo_db, repo_memory_db
from src.generator import (
    Generator,
    GROQ_MODEL,
    GROQ_URL,
    NVIDIA_MODEL,
    NVIDIA_URL,
)
from src.git.git_service import compute_file_hash
from src.repo.repo_processor import walk_repo

logger = logging.getLogger(__name__)

_INGEST_LLM_SEM = threading.Semaphore(LLM_SEMAPHORE_LIMIT)

INGEST_SYSTEM_PROMPT = """You are an expert software analyst. Given one source \
file along with its structurally extracted AST data (functions, classes, \
imports, exports), produce a single JSON object (no markdown fences, no \
commentary) with exactly these keys:

- summary (string): concise overview of what the file does.
- purpose (string): why this file exists in the codebase.
- exports (array of strings): public symbols, APIs, or modules exported. \
If AST exports are provided, use them directly.
- imports (array of objects): each object has "module" (string) and \
"used_for" (string). Use AST imports as the base, add "used_for" context.
- internal_dependencies (array of strings): other project files or internal \
modules this file depends on.
- patterns_detected (array of strings): notable design or idioms \
(e.g. "singleton", "repository pattern").
- todos_and_debt (array of objects): each has "line" (number or null), \
"text" (string), "severity" (string: info|low|medium|high).
- entities (array of strings): key domain or technical entities mentioned.
- topics (array of strings): thematic labels for search.
- functions_and_classes (array of objects): each has "name", "type" \
(function|class|method|other), "params" (string or null), "line" (number or null). \
If AST data is provided, merge it with any additional items you detect.
- complexity_assessment (string): brief complexity note.
- importance_score (number): 0.0 to 1.0 relevance TO THIS SPECIFIC PROJECT. \
Score based on how central the file is to the project's own business logic: \
entry points, core services, and domain models score high (0.7-1.0); \
helpers and utilities score medium (0.4-0.6); config, tests, and boilerplate \
score low (0.1-0.3). Third-party library code, vendored dependencies, or \
auto-generated files should ALWAYS score 0.0-0.1 regardless of their \
internal complexity.

Focus on PURPOSE, PATTERNS, and COMPLEXITY rather than symbol extraction \
(AST handles that). Use empty arrays where there is nothing to report. \
Be factual; if unknown, use empty strings or empty arrays. Respond with \
valid JSON only."""


def _posix_rel_path(rel_path: str) -> str:
    """Normalize a repo-relative path to POSIX form for storage and lookup.

    Args:
        rel_path: Path as returned by the walker (may use OS separators).

    Returns:
        Forward-slash normalized relative path string.

    Raises:
        None.
    """
    return Path(rel_path).as_posix()


def _ingest_build_provider_attempts() -> List[Tuple[str, str, str]]:
    """Build ordered (url, model, api_key) tuples for ingest LLM calls.

    Args:
        None

    Returns:
        Ordered list of provider tuples (may be empty if no keys are set);
        NVIDIA is listed before Groq when both are valid.

    Raises:
        None.
    """
    nvidia_key = os.getenv("NVIDIA_API_KEY", "").strip()
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    nvidia_ok = bool(nvidia_key and nvidia_key != NVIDIA_API_KEY_SENTINEL)
    attempts: List[Tuple[str, str, str]] = []
    if nvidia_ok:
        attempts.append((NVIDIA_URL, NVIDIA_MODEL, nvidia_key))
    if groq_key:
        attempts.append((GROQ_URL, GROQ_MODEL, groq_key))
    return attempts


def _ingest_json_headers(api_key: str) -> Dict[str, str]:
    """HTTP headers for a non-streaming JSON chat completion request.

    Args:
        api_key: Bearer token for the provider.

    Returns:
        Header dict suitable for ``requests.post``.

    Raises:
        None.
    """
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _ingest_build_payload(
    model: str,
    messages: List[Dict[str, str]],
    max_tokens: Optional[int] = INGEST_COMPLETION_MAX_TOKENS,
) -> Dict[str, Any]:
    """Assemble the JSON body for a non-streaming chat completion.

    Args:
        model:      Provider model id.
        messages:   OpenAI-style chat messages.
        max_tokens: Cap on completion tokens.  Pass ``None`` to let the
                    provider use its full remaining context window.

    Returns:
        Request payload dict.

    Raises:
        None.
    """
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": INGEST_COMPLETION_TEMPERATURE,
        "top_p": INGEST_COMPLETION_TOP_P,
        "stream": False,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    return payload


def _ingest_parse_non_stream_body(response: requests.Response) -> str:
    """Extract assistant text from a non-streaming chat completion response.

    Args:
        response: Successful HTTP response with JSON body.

    Returns:
        Trimmed assistant message content.

    Raises:
        requests.HTTPError: If the response status indicates an error.
        KeyError: If the response JSON lacks expected keys.
        IndexError: If ``choices`` is empty.
    """
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"].strip()


def _ingest_post_completion(
    url: str,
    headers: Dict[str, str],
    payload: Dict[str, Any],
) -> str:
    """POST once and return assistant text (non-streaming).

    Args:
        url:     Chat completions endpoint URL.
        headers: Request headers including authorization.
        payload: JSON body with ``stream: false``.

    Returns:
        Assistant content string.

    Raises:
        requests.RequestException: On network or HTTP errors.
        KeyError: If the response shape is unexpected.
        IndexError: If ``choices`` is empty.
    """
    resp = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=INGEST_HTTP_TIMEOUT_SECONDS,
    )
    return _ingest_parse_non_stream_body(resp)


def _ingest_one_attempt(
    url: str,
    headers: Dict[str, str],
    payload: Dict[str, Any],
) -> str:
    """Perform a single guarded HTTP completion request.

    Args:
        url:     Chat completions endpoint URL.
        headers: Request headers including authorization.
        payload: JSON body with ``stream: false``.

    Returns:
        Assistant content string.

    Raises:
        requests.RequestException: On network or HTTP errors.
        KeyError: If the response shape is unexpected.
        IndexError: If ``choices`` is empty.
        json.JSONDecodeError: If the response body is not valid JSON.
    """
    _INGEST_LLM_SEM.acquire()
    try:
        return _ingest_post_completion(url, headers, payload)
    finally:
        _INGEST_LLM_SEM.release()


def _ingest_try_provider(
    url: str,
    model: str,
    api_key: str,
    messages: List[Dict[str, str]],
    max_tokens: Optional[int] = INGEST_COMPLETION_MAX_TOKENS,
) -> Tuple[Optional[str], Optional[Exception]]:
    """Call one provider with retries and return assistant text or failure.

    Args:
        url:        Chat completions endpoint.
        model:      Model id for that endpoint.
        api_key:    API key for authorization.
        messages:   Chat messages for the completion.
        max_tokens: Cap on completion tokens.  Pass ``None`` to omit the
                    limit and let the provider use its full context window.

    Returns:
        Tuple of (assistant text, ``None``) on success, or (``None``, last error).

    Raises:
        None.
    """
    headers = _ingest_json_headers(api_key)
    payload = _ingest_build_payload(model, messages, max_tokens=max_tokens)
    delay = INGEST_LLM_INITIAL_BACKOFF_SECONDS
    last_error: Optional[Exception] = None
    for attempt in range(1, INGEST_LLM_MAX_RETRIES + 1):
        try:
            text = _ingest_one_attempt(url, headers, payload)
            return text, None
        except requests.exceptions.HTTPError as exc:
            last_error = exc
            code = exc.response.status_code if exc.response else 0
            if code == 429 and attempt < INGEST_LLM_MAX_RETRIES:
                wait = delay * 2 + random.uniform(0, INGEST_LLM_RETRY_JITTER_WIDE)
                logger.warning(
                    "Ingest LLM rate limited (%s), retry in %.1fs (%d/%d)",
                    url, wait, attempt, INGEST_LLM_MAX_RETRIES,
                )
                time.sleep(wait)
                delay *= 2
            elif attempt < INGEST_LLM_MAX_RETRIES:
                wait = delay + random.uniform(0, INGEST_LLM_RETRY_JITTER_NARROW)
                logger.warning(
                    "Ingest LLM HTTP error (%s): %s — retry in %.1fs",
                    url, exc, wait,
                )
                time.sleep(wait)
                delay *= 2
        except (requests.RequestException, KeyError, IndexError, json.JSONDecodeError) as exc:
            last_error = exc
            wait = delay + random.uniform(0, INGEST_LLM_RETRY_JITTER_NARROW)
            logger.warning(
                "Ingest LLM request failed (%s): %s — retry in %.1fs",
                url, exc, wait,
            )
            if attempt < INGEST_LLM_MAX_RETRIES:
                time.sleep(wait)
                delay *= 2
    return None, last_error


def _ingest_chat_completion(
    messages: List[Dict[str, str]],
    generator: Generator,
    max_tokens: Optional[int] = INGEST_COMPLETION_MAX_TOKENS,
) -> str:
    """Call NVIDIA and/or Groq with retries and provider fallback (non-streaming).

    Args:
        messages:   OpenAI-style chat messages (system + user).
        generator:  Existing ``Generator`` (confirms keys were validated at init).
        max_tokens: Cap on completion tokens.  Pass ``None`` to omit the
                    limit and let the provider use its full context window.

    Returns:
        Raw assistant string (expected to be JSON).

    Raises:
        RuntimeError: If no provider keys exist or all attempts fail.
    """
    _ = generator
    attempts = _ingest_build_provider_attempts()
    if not attempts:
        raise RuntimeError(
            "No LLM API key available for ingest (NVIDIA_API_KEY / GROQ_API_KEY)."
        )
    last_error: Optional[Exception] = None
    for url, model, api_key in attempts:
        text, err = _ingest_try_provider(url, model, api_key, messages, max_tokens=max_tokens)
        if text is not None:
            return text
        last_error = err
        logger.warning("Ingest provider exhausted retries, trying next if any")
    raise RuntimeError(f"Ingest LLM failed after all providers: {last_error}") from last_error


def _strip_json_fence(text: str) -> str:
    """Remove optional ``` / ```json fences from model output.

    Args:
        text: Raw model output.

    Returns:
        Inner JSON text.

    Raises:
        None.
    """
    stripped = text.strip()
    fence = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", stripped, re.IGNORECASE)
    if fence:
        return fence.group(1).strip()
    return stripped


def _empty_memory_shell(summary: str) -> Dict[str, Any]:
    """Build a minimal memory dict when JSON parsing fails.

    Args:
        summary: Text to store as ``summary``.

    Returns:
        Dict compatible with ``repo_memory_db.upsert`` expectations.

    Raises:
        None.
    """
    return {
        "summary": summary,
        "purpose": "",
        "exports": [],
        "imports": [],
        "internal_dependencies": [],
        "patterns_detected": [],
        "todos_and_debt": [],
        "entities": [],
        "topics": [],
        "functions_and_classes": [],
        "complexity_assessment": "",
        "importance_score": None,
    }


def _parse_memory_json(raw: str) -> Dict[str, Any]:
    """Parse model JSON into a memory dict.

    Args:
        raw: Model output (possibly fenced).

    Returns:
        Parsed dictionary.

    Raises:
        json.JSONDecodeError: If content is not valid JSON.
    """
    inner = _strip_json_fence(raw)
    return json.loads(inner)


def _build_ingest_user_message(
    file_path: str,
    language: str,
    file_content: str,
    ast_data: Optional[Dict[str, Any]] = None,
) -> str:
    """Format the user message for per-file analysis, including AST context.

    Args:
        file_path:    Repo-relative path.
        language:     Human-readable language label.
        file_content: Full file text (already size-filtered by the walker).
        ast_data:     Optional AST extraction dict from ``ast_to_dict``.

    Returns:
        User message string.

    Raises:
        None.
    """
    cap_note = (
        f"\n(Note: files larger than {MAX_FILE_SIZE_BYTES} bytes are skipped "
        "by the indexer; this content is within that limit.)\n"
    )
    ast_section = ""
    if ast_data and ast_data.get("parsed"):
        ast_section = (
            "\n---AST STRUCTURE (Tree-sitter extracted, authoritative)---\n"
            f"Functions: {json.dumps(ast_data.get('functions', []), ensure_ascii=False)}\n"
            f"Classes: {json.dumps(ast_data.get('classes', []), ensure_ascii=False)}\n"
            f"Imports: {json.dumps(ast_data.get('imports', []), ensure_ascii=False)}\n"
            f"Exports: {json.dumps(ast_data.get('exports', []), ensure_ascii=False)}\n"
            "---END AST---\n"
        )
    return (
        f"File path: {file_path}\n"
        f"Language: {language}\n"
        f"{cap_note}"
        f"{ast_section}"
        "---SOURCE---\n"
        f"{file_content}\n"
        "---END---\n"
        "Respond with ONLY valid JSON as specified in the system message."
    )


def analyze_file(
    file_path: str,
    file_content: str,
    language: str,
    generator: Generator,
    ast_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run the ingest LLM on one file and return structured memory fields.

    When AST data is provided, it is included in the prompt so the LLM
    can focus on purpose/patterns/complexity rather than symbol extraction.

    Args:
        file_path:    Repository-relative path (for prompt context).
        file_content: Full source text.
        language:     Language label (e.g. ``Python``).
        generator:    Initialized ``Generator`` instance.
        ast_data:     Optional AST extraction dict from ``ast_to_dict``.

    Returns:
        Dict of memory fields; on JSON parse failure, a shell with ``summary`` only.

    Raises:
        RuntimeError: If the LLM call fails entirely (propagated from completion).
    """
    user_msg = _build_ingest_user_message(file_path, language, file_content, ast_data)
    messages = [
        {"role": "system", "content": INGEST_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]
    raw = _ingest_chat_completion(messages, generator)
    try:
        memory = _parse_memory_json(raw)
    except json.JSONDecodeError as exc:
        logger.warning("Ingest JSON parse failed for %s: %s", file_path, exc)
        cap = INGEST_PARSE_FALLBACK_SNIPPET_CHARS
        snippet = (raw[:cap] + "…") if len(raw) > cap else raw
        memory = _empty_memory_shell(snippet or "Failed to parse model JSON.")

    if ast_data and ast_data.get("parsed"):
        _merge_ast_into_memory(memory, ast_data)

    return memory


def _merge_ast_into_memory(
    memory: Dict[str, Any],
    ast_data: Dict[str, Any],
) -> None:
    """Override LLM-extracted structural fields with AST-extracted data.

    Mutates *memory* in place.  AST data is considered authoritative
    for functions_and_classes, imports, and exports.

    Args:
        memory:   Memory dict from LLM analysis.
        ast_data: Parsed AST dict from ``ast_to_dict``.

    Returns:
        None
    """
    ast_funcs = ast_data.get("functions", [])
    ast_classes = ast_data.get("classes", [])
    if ast_funcs or ast_classes:
        merged_fc: List[Dict[str, Any]] = []
        for f in ast_funcs:
            merged_fc.append({
                "name": f.get("name", ""),
                "type": "function",
                "params": f.get("params", ""),
                "line": f.get("start_line"),
            })
        for c in ast_classes:
            merged_fc.append({
                "name": c.get("name", ""),
                "type": "class",
                "params": None,
                "line": c.get("start_line"),
            })
            for m in c.get("methods", []):
                merged_fc.append({
                    "name": f"{c.get('name', '')}.{m}",
                    "type": "method",
                    "params": None,
                    "line": None,
                })
        memory["functions_and_classes"] = merged_fc

    ast_imports = ast_data.get("imports", [])
    if ast_imports:
        existing_imports = memory.get("imports") or []
        existing_map = {}
        for ei in existing_imports:
            if isinstance(ei, dict):
                existing_map[ei.get("module", "")] = ei.get("used_for", "")
        merged_imports = []
        for imp in ast_imports:
            mod = imp.get("module", "")
            merged_imports.append({
                "module": mod,
                "used_for": existing_map.get(mod, ""),
            })
        memory["imports"] = merged_imports

    ast_exports = ast_data.get("exports", [])
    if ast_exports:
        memory["exports"] = [e.get("name", "") for e in ast_exports]


def _should_skip_llm(file_path: str, size_bytes: int, ast_parsed: bool) -> bool:
    """Decide whether a file can be indexed with AST alone, skipping LLM.

    Config/data files, very small files, and non-code files are indexed
    using only AST-extracted structure (or a minimal summary), saving
    an expensive LLM API call per file.

    Args:
        file_path:   Repo-relative file path.
        size_bytes:  File size in bytes.
        ast_parsed:  Whether Tree-sitter successfully parsed the file.

    Returns:
        ``True`` if the LLM call should be skipped.
    """
    ext = Path(file_path).suffix.lower()
    if ext in AST_ONLY_EXTENSIONS:
        return True
    if size_bytes < AST_ONLY_MAX_FILE_SIZE:
        return True
    return False


def _build_ast_only_memory(
    file_path: str,
    content: str,
    ast_data: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build a memory dict from AST data alone, without an LLM call.

    Args:
        file_path: Repo-relative path.
        content:   File text.
        ast_data:  AST extraction dict, or ``None``.

    Returns:
        Memory dict compatible with ``repo_memory_db.upsert``.
    """
    ext = Path(file_path).suffix.lower()
    name = Path(file_path).name
    first_line = (content.split("\n", 1)[0] or "").strip()[:120]
    summary = f"{name}: {first_line}" if first_line else name

    memory: Dict[str, Any] = {
        "summary": summary,
        "purpose": "",
        "exports": [],
        "imports": [],
        "internal_dependencies": [],
        "patterns_detected": [],
        "todos_and_debt": [],
        "entities": [],
        "topics": [ext.lstrip(".")] if ext else [],
        "functions_and_classes": [],
        "complexity_assessment": "low",
        "importance_score": 0.2,
    }

    if ast_data and ast_data.get("parsed"):
        _merge_ast_into_memory(memory, ast_data)

    return memory


def _process_single_file(
    repo_id: str,
    file_info: Dict[str, Any],
    file_hash: str,
    generator: Generator,
) -> Tuple[bool, Optional[Tuple[str, str, "ASTResult"]]]:
    """Read one file, parse AST, analyze via LLM, and upsert its memory row.

    For simple config/data files, skips the LLM call entirely and uses
    AST-only indexing for speed.

    Returns a tuple of (success, optional (rel_path, content, ast_result))
    so callers can collect AST results for reference graph and embedding.

    Args:
        repo_id:    Repository UUID.
        file_info:  Entry from ``walk_repo`` (path, abs_path, language, size).
        file_hash:  SHA-256 hex digest of current file bytes.
        generator:  ``Generator`` instance for LLM access.

    Returns:
        ``(True, (path, content, ast))`` on success, ``(False, None)`` on failure.

    Raises:
        None.
    """
    from src.repo.ast_parser import ASTResult as _ASTResult, ast_to_dict, parse_file

    rel = _posix_rel_path(str(file_info["path"]))
    abs_path = str(file_info["abs_path"])
    lang = file_info.get("language") or "Unknown"
    size_b = int(file_info.get("size_bytes") or 0)
    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as handle:
            content = handle.read()
    except OSError as exc:
        logger.warning("Could not read file %s: %s", abs_path, exc)
        return False, None

    ast_result = parse_file(content, rel)
    ast_data = ast_to_dict(ast_result) if ast_result.parsed else None

    try:
        if _should_skip_llm(rel, size_b, ast_result.parsed):
            memory = _build_ast_only_memory(rel, content, ast_data)
        else:
            memory = analyze_file(rel, content, str(lang), generator, ast_data=ast_data)
        repo_memory_db.upsert(
            repo_id,
            rel,
            file_hash,
            str(lang) if lang else None,
            size_b,
            memory,
        )
        return True, (rel, content, ast_result)
    except Exception as exc:
        logger.warning("Ingest failed for %s: %s", rel, exc)
        return False, None


def _build_ingest_queue(
    repo_id: str,
    files: List[Dict[str, Any]],
) -> Tuple[List[Tuple[Dict[str, Any], str]], int]:
    """Split walk results into skipped (unchanged hash) vs work items.

    Args:
        repo_id: Repository UUID.
        files:   List from ``walk_repo``.

    Returns:
        Tuple of (list of (file_info, file_hash) to process, skip count).

    Raises:
        None.
    """
    existing_hashes = repo_memory_db.get_path_hash_map(repo_id)

    to_process: List[Tuple[Dict[str, Any], str]] = []
    skipped = 0
    for fi in files:
        rel = _posix_rel_path(str(fi["path"]))
        abs_path = str(fi["abs_path"])
        try:
            digest = compute_file_hash(abs_path)
        except OSError as exc:
            logger.warning("Hash failed for %s: %s", abs_path, exc)
            continue
        if existing_hashes.get(rel) == digest:
            skipped += 1
            continue
        to_process.append((fi, digest))
    return to_process, skipped


def _run_ingest_pool(
    repo_id: str,
    total_files: int,
    skipped_baseline: int,
    work: List[Tuple[Dict[str, Any], str]],
    generator: Generator,
) -> Tuple[int, Dict[str, Any], Dict[str, str], Dict[str, str]]:
    """Process pending files concurrently and update progress in ``repo_db``.

    Returns AST results, file contents, and file hashes for downstream
    reference graph and embedding pipeline.

    Args:
        repo_id:          Repository UUID.
        total_files:      Total files discovered in the walk.
        skipped_baseline: Files skipped due to unchanged hash.
        work:             List of (file_info, file_hash) to analyze.
        generator:        Shared ``Generator`` instance.

    Returns:
        Tuple of (success_count, ast_results_dict, file_contents_dict,
        file_hashes_dict).

    Raises:
        None.
    """
    lock = threading.Lock()
    success = 0
    ast_results: Dict[str, Any] = {}
    file_contents: Dict[str, str] = {}
    file_hashes: Dict[str, str] = {}
    repo_db.update_file_counts(repo_id, total_files, skipped_baseline)
    if not work:
        return 0, ast_results, file_contents, file_hashes
    max_workers = min(MAX_CONCURRENT_INGEST_WORKERS, len(work))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_process_single_file, repo_id, fi, h, generator): (fi, h)
            for fi, h in work
        }
        processed = 0
        for fut in as_completed(futures):
            ok, extra = fut.result()
            processed += 1
            with lock:
                if ok:
                    success += 1
                    if extra:
                        rel_path, content, ast_result = extra
                        ast_results[rel_path] = ast_result
                        file_contents[rel_path] = content
                        file_hashes[rel_path] = futures[fut][1]
                done = skipped_baseline + processed
                detail = f"Analyzed {processed}/{len(work)} files"
                if ok and extra:
                    detail = f"{extra[0]} ({processed}/{len(work)})"
                repo_db.update_file_counts(repo_id, total_files, skipped_baseline + success)
                repo_db.update_progress(repo_id, "ingesting", done, total_files, detail)
    return success, ast_results, file_contents, file_hashes


def ingest_repo(
    repo_id: str,
    repo_path: str,
    generator: Generator,
    force: bool = False,
) -> Dict[str, Any]:
    """Ingest all indexable files under ``repo_path`` into ``repo_file_memories``.

    Also builds the cross-file reference graph and embeds code chunks
    using Tree-sitter AST data collected during ingestion.

    When ``force`` is ``True`` all existing memories are deleted first so
    every file is re-analyzed with the current prompts — use this for
    explicit "Full Reindex" actions.  When ``False`` (the default),
    unchanged files are skipped via content-hash comparison.

    Args:
        repo_id:   UUID of the repo row.
        repo_path: Absolute path to the cloned repository root.
        generator: Initialized ``Generator``.
        force:     Delete all existing memories before re-ingesting.

    Returns:
        Stats dict with ``total_files``, ``indexed_files``, ``skipped_files``,
        ``reference_edges``, ``code_chunks``.

    Raises:
        ValueError: If the repository id is unknown.
        Exception: Any other failure after ``repos.indexing_status`` is set to
            ``failed`` (the original exception is re-raised).
    """
    if repo_db.find_by_id(repo_id) is None:
        raise ValueError(f"Repository not found: {repo_id}")
    repo_memory_db.ensure_table()

    repo_db.update_progress(repo_id, "scanning", 0, 1, "Discovering files…")
    files = walk_repo(repo_path)
    total = len(files)
    try:
        repo_db.update_status(repo_id, REPO_INDEXING_STATUS_INDEXING, None)
        repo_db.update_file_counts(repo_id, total, 0)

        if force:
            repo_memory_db.delete_by_repo(repo_id)
            logger.info("Force reindex: cleared all memories for %s", repo_id)
        else:
            current_paths = [_posix_rel_path(str(f["path"])) for f in files]
            repo_memory_db.delete_stale_files(repo_id, current_paths)
            logger.info("Purged stale memories for %s (keeping %d paths)", repo_id, len(current_paths))

        repo_db.update_progress(repo_id, "parsing", 0, total, "Building work queue…")

        work, skipped = _build_ingest_queue(repo_id, files)
        repo_db.update_progress(repo_id, "ingesting", skipped, total, f"{len(work)} files to analyze")

        indexed, ast_results, file_contents, file_hashes = _run_ingest_pool(
            repo_id, total, skipped, work, generator,
        )
        repo_db.update_file_counts(repo_id, total, skipped + indexed)
        repo_db.update_progress(repo_id, "ingesting", skipped + indexed, total, "File analysis complete")

        ref_edges = 0
        chunk_count = 0
        if ast_results:
            repo_files = {_posix_rel_path(str(f["path"])) for f in files}
            try:
                repo_db.update_progress(repo_id, "building_graph", 0, 1, "Building reference graph…")
                from src.repo.reference_graph import build_reference_graph
                from src.db import repo_reference_db
                repo_reference_db.ensure_table()
                ref_edges = build_reference_graph(repo_id, ast_results, repo_files)
                repo_db.update_progress(repo_id, "building_graph", 1, 1, f"{ref_edges} edges built")
            except Exception as exc:
                logger.warning("Reference graph build failed: %s", exc)

            try:
                repo_db.update_progress(repo_id, "embedding", 0, len(file_contents), "Embedding code chunks…")
                from src.repo.code_embedder import embed_repo_code
                from src.db import repo_code_chunk_db
                repo_code_chunk_db.ensure_table()
                chunk_count = embed_repo_code(
                    repo_id, repo_path, ast_results, file_contents, file_hashes,
                )
                repo_db.update_progress(repo_id, "embedding", len(file_contents), len(file_contents), f"{chunk_count} chunks embedded")
            except Exception as exc:
                logger.warning("Code embedding failed: %s", exc)

        repo_db.update_progress(repo_id, "complete", total, total, "Indexing complete")
        repo_db.mark_indexed(repo_id)
        return {
            "total_files": total,
            "indexed_files": indexed,
            "skipped_files": skipped,
            "reference_edges": ref_edges,
            "code_chunks": chunk_count,
        }
    except Exception as exc:
        logger.exception("ingest_repo failed for %s", repo_id)
        repo_db.update_status(repo_id, REPO_INDEXING_STATUS_FAILED, str(exc))
        raise


def ingest_files(
    repo_id: str,
    file_paths: List[str],
    repo_path: str,
    generator: Generator,
) -> Dict[str, Any]:
    """Targeted re-ingest of specific files (not full walk).

    Used for incremental post-agent refresh of changed files.

    Args:
        repo_id:    Repository UUID.
        file_paths: POSIX-normalized repo-relative paths to re-ingest.
        repo_path:  Absolute path to the repo root.
        generator:  Initialized ``Generator``.

    Returns:
        Stats dict with ``processed``, ``succeeded``, ``ast_results``,
        ``file_contents``, ``file_hashes``.
    """
    from src.repo.ast_parser import parse_file as _parse_file, ast_to_dict as _ast_to_dict

    succeeded = 0
    ast_results: Dict[str, Any] = {}
    file_contents_map: Dict[str, str] = {}
    file_hashes_map: Dict[str, str] = {}

    for rel in file_paths:
        abs_path = os.path.join(repo_path, rel.replace("/", os.sep))
        if not os.path.isfile(abs_path):
            continue
        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except OSError:
            continue

        from src.git.git_service import compute_file_hash
        file_hash = compute_file_hash(abs_path)

        ast_result = _parse_file(content, rel)
        ast_data = _ast_to_dict(ast_result) if ast_result.parsed else None

        from src.config.repo_constants import EXTENSION_TO_LANGUAGE
        ext = Path(rel).suffix.lower()
        lang = EXTENSION_TO_LANGUAGE.get(ext, "Unknown")
        size_b = os.path.getsize(abs_path)

        try:
            memory = analyze_file(rel, content, lang, generator, ast_data=ast_data)
            repo_memory_db.upsert(repo_id, rel, file_hash, lang, size_b, memory)
            succeeded += 1
            ast_results[rel] = ast_result
            file_contents_map[rel] = content
            file_hashes_map[rel] = file_hash
        except Exception as exc:
            logger.warning("Targeted ingest failed for %s: %s", rel, exc)

    return {
        "processed": len(file_paths),
        "succeeded": succeeded,
        "ast_results": ast_results,
        "file_contents": file_contents_map,
        "file_hashes": file_hashes_map,
    }
