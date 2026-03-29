"""
query_agent.py
==============
Service-layer Q&A over structured repo memories, vector search, and
consolidated context.

Uses a multi-signal retrieval strategy:
1. **Vector search** on ``repo_code_chunks`` for semantic relevance.
2. **Keyword search** on ``repo_file_memories`` for text/topic/entity matches.
3. **Global context** from ``repo_context`` (architecture, features, etc.)
   is always included and prioritized for broad questions.
4. **Consolidation insights** filtered by keyword relevance.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Set

from src.agents.ingest_agent import _ingest_chat_completion, _strip_json_fence
from src.config.repo_constants import (
    MIN_MEMORIES_FOR_QUERY_MATCH,
    QUERY_KEYWORD_MIN_LENGTH,
    QUERY_KEYWORD_STOP_WORDS,
)
from src.db import repo_context_db, repo_db, repo_memory_db
from src.generator import Generator
from src.utils.repo_errors import RepoNotFoundError

logger = logging.getLogger(__name__)

QUERY_SYSTEM_PROMPT = """\
You are an expert code analyst answering questions about a software repository. \
Use ONLY the provided project context, code snippets, file memories, and \
consolidation insights.

## Response quality guidelines

1. **Structure**: Use markdown headings (##, ###), bullet points, and numbered \
steps. Never return a wall of text.
2. **Code references**: Embed short inline code snippets (```language … ```) \
from the provided code chunks when they help explain behavior. Always show \
the file path above the snippet.
3. **Diagrams**: For architecture, data-flow, or sequence questions, include a \
Mermaid diagram (```mermaid … ```) that visualizes the relationships. \
Use correct Mermaid arrow syntax: `A -->|label| B` is correct; \
`A -->|label|> B` is INVALID and will cause parse errors. Never add a \
trailing `>` after the label pipes.
4. **Specificity**: Cite exact file paths (`src/foo.py`), function/class names, \
API routes, and tech-stack components visible in the context.
5. **Depth**: Explain *how* things work, not just *that* they exist. Walk \
through the logic step-by-step when describing flows.
6. **Honesty**: If information is missing from the context, say so explicitly.

## Answer structure (adapt to question type)

- **Broad questions** ("what is this project?"): Start with a 2-3 sentence \
overview, then list key features, architecture layers, and tech stack.
- **Specific function/file questions**: Explain purpose, parameters, return \
values, and show the relevant code snippet. Mention callers/callees if known.
- **Flow/architecture questions**: Describe step-by-step with numbered steps \
and include a Mermaid diagram.
- **Comparison questions**: Use a table or side-by-side bullet points.

## Output format

Respond with a single JSON object (no markdown fences around the JSON) with:
  "answer" (string — rich markdown including headings, code blocks, and \
mermaid diagrams as described above),
  "cited_files" (array of repo-relative path strings you relied on).
Do not fabricate paths; every cited path must appear in the provided context.

IMPORTANT: The "answer" value must contain ONLY your markdown response. \
Do NOT embed a duplicate JSON object or a ```json code block containing \
the same answer inside the markdown. Return the JSON wrapper exactly once."""


def _ensure_generator(generator: Optional[Generator]) -> Generator:
    """Return a usable Generator, constructing one if omitted.

    Args:
        generator: Optional pre-built ``Generator`` instance.

    Returns:
        A ``Generator`` with valid API keys.

    Raises:
        ValueError: If no provider keys are available (from ``Generator``).
    """
    if generator is not None:
        return generator
    return Generator()


def _extract_keywords(question: str) -> List[str]:
    """Tokenize a question into lowercase keywords (stop words removed).

    Args:
        question: Natural-language user question.

    Returns:
        Distinct keyword strings suitable for memory search.

    Raises:
        None.
    """
    tokens = re.findall(r"[a-zA-Z0-9_]+", (question or "").lower())
    min_len = QUERY_KEYWORD_MIN_LENGTH
    out: List[str] = []
    seen: Set[str] = set()
    for t in tokens:
        if len(t) < min_len or t in QUERY_KEYWORD_STOP_WORDS:
            continue
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _dedupe_memory_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate file memory rows by primary key ``id``.

    Args:
        rows: Full ``repo_file_memories`` row dicts.

    Returns:
        First-seen row per ``id``, stable order.

    Raises:
        None.
    """
    seen: Set[str] = set()
    out: List[Dict[str, Any]] = []
    for r in rows:
        rid = str(r.get("id", ""))
        if not rid or rid in seen:
            continue
        seen.add(rid)
        out.append(r)
    return out


def _vector_search_chunks(
    repo_id: str,
    question: str,
    limit: int = 12,
) -> List[Dict[str, Any]]:
    """Embed the question and search code chunks by vector similarity.

    Falls back gracefully to an empty list if the embedder or pgvector
    table is unavailable.

    Args:
        repo_id:  Repository UUID.
        question: Natural-language query string.
        limit:    Max chunks to return.

    Returns:
        List of matching chunk dicts with ``file_path``, ``symbol_name``,
        ``content``, ``similarity``.
    """
    try:
        from src.db import repo_code_chunk_db
        from src.embedder import get_embedder

        embedder = get_embedder()
        query_vec = embedder.embed(question, use_cache=True).tolist()
        return repo_code_chunk_db.search_similar(
            repo_id, query_vec, limit=limit, threshold=0.35,
        )
    except Exception as exc:
        logger.debug("Vector search unavailable: %s", exc)
        return []


def _gather_initial_memories(
    repo_id: str,
    keywords: List[str],
) -> List[Dict[str, Any]]:
    """Collect memories via topics, entities, and per-keyword text search.

    Args:
        repo_id:  Repository UUID.
        keywords: Extracted keywords.

    Returns:
        Deduplicated matching rows.

    Raises:
        None.
    """
    acc: List[Dict[str, Any]] = []
    for kw in keywords:
        acc.extend(repo_memory_db.search_by_text(repo_id, kw))
        acc.extend(repo_memory_db.search_by_topics(repo_id, [kw]))
        acc.extend(repo_memory_db.search_by_entities(repo_id, [kw]))
    return _dedupe_memory_rows(acc)


def _broader_memory_search(
    repo_id: str,
    question: str,
) -> List[Dict[str, Any]]:
    """Run substring search over summary and purpose for the full question.

    Args:
        repo_id:  Repository UUID.
        question: Raw user question.

    Returns:
        Rows from ``search_by_text``.

    Raises:
        None.
    """
    q = (question or "").strip()
    if not q:
        return []
    return repo_memory_db.search_by_text(repo_id, q)


def _filter_consolidations(
    rows: List[Dict[str, Any]],
    keywords: List[str],
) -> List[Dict[str, Any]]:
    """Keep consolidations whose text matches any keyword (case-insensitive).

    Args:
        rows:     ``list_consolidations`` results.
        keywords: Lowercase keywords (may be empty).

    Returns:
        Filtered rows; if ``keywords`` is empty, returns ``rows``.

    Raises:
        None.
    """
    if not keywords:
        return list(rows)
    out: List[Dict[str, Any]] = []
    for r in rows:
        blob = " ".join(
            str(x).lower()
            for x in (
                r.get("insight"),
                r.get("actionable_suggestion"),
                r.get("consolidation_type"),
            )
            if x
        )
        if any(kw in blob for kw in keywords):
            out.append(r)
    return out


def _simplify_memories_for_prompt(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep the most informative fields from memory rows for the LLM prompt.

    Includes structural data (imports, dependencies, patterns) alongside
    purpose and functions so the LLM can describe file relationships,
    architecture, and data flow — not just vague summaries.

    Args:
        rows: Full memory rows.

    Returns:
        Enriched slim dicts, limited to the top 25 by importance.
    """
    slim: List[Dict[str, Any]] = []
    for r in rows:
        entry: Dict[str, Any] = {
            "file_path": r.get("file_path"),
            "summary": r.get("summary"),
            "purpose": r.get("purpose"),
            "language": r.get("language"),
            "importance_score": r.get("importance_score"),
        }
        funcs = r.get("functions_and_classes")
        if funcs:
            entry["functions_and_classes"] = funcs[:20]
        exports = r.get("exports")
        if exports:
            entry["exports"] = exports[:15]
        imports = r.get("imports")
        if imports:
            entry["imports"] = imports[:15]
        deps = r.get("internal_dependencies")
        if deps:
            entry["internal_dependencies"] = deps[:10]
        patterns = r.get("patterns_detected")
        if patterns:
            entry["patterns"] = patterns
        topics = r.get("topics")
        if topics:
            entry["topics"] = topics
        entities = r.get("entities")
        if entities:
            entry["entities"] = entities
        slim.append(entry)
    return slim[:25]


def _format_context_summary(context: Optional[Dict[str, Any]]) -> str:
    """Format the global repo_context into a readable summary block.

    Extracts the most useful fields (architecture, tech_stack, features,
    entry_points, api_routes, file_responsibility_map) and presents them
    as structured text rather than raw JSON so the LLM can reference them
    naturally.

    Args:
        context: ``repo_context`` row or ``None``.

    Returns:
        Human-readable context summary string.
    """
    if not context:
        return "{}"

    key_fields = [
        "architecture", "tech_stack", "features", "api_surface",
        "entry_points", "file_responsibility_map", "api_routes",
        "data_flow", "dependency_graph", "key_files",
        "security_findings", "tech_debt", "test_coverage",
    ]
    filtered: Dict[str, Any] = {}
    for k in key_fields:
        val = context.get(k)
        if val and val != [] and val != {}:
            filtered[k] = val
    return json.dumps(filtered, ensure_ascii=False, default=str)


_EXT_TO_LANG: Dict[str, str] = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".tsx": "tsx", ".jsx": "jsx", ".java": "java", ".go": "go",
    ".rs": "rust", ".rb": "ruby", ".php": "php", ".cs": "csharp",
    ".cpp": "cpp", ".c": "c", ".swift": "swift", ".kt": "kotlin",
    ".sql": "sql", ".sh": "bash", ".yaml": "yaml", ".yml": "yaml",
    ".json": "json", ".html": "html", ".css": "css", ".scss": "scss",
}


def _lang_hint(file_path: str) -> str:
    """Derive a code-fence language hint from a file path extension.

    Args:
        file_path: Repo-relative file path.

    Returns:
        Language string for markdown code fences (e.g. 'python').
    """
    ext = "." + file_path.rsplit(".", 1)[-1] if "." in file_path else ""
    return _EXT_TO_LANG.get(ext.lower(), "")


def _format_vector_hits(chunks: List[Dict[str, Any]]) -> str:
    """Format vector search results as labelled code blocks the LLM can embed.

    Each chunk is presented with its file path, symbol name, and code
    content wrapped in a fenced code block with the correct language hint
    so the LLM can quote snippets directly.

    Args:
        chunks: Chunk dicts from ``search_similar``.

    Returns:
        Formatted string with structured code blocks.
    """
    if not chunks:
        return "(no code chunks matched)"
    parts: List[str] = []
    for ch in chunks[:10]:
        fp = ch.get("file_path", "?")
        sym = ch.get("symbol_name", "")
        content = ch.get("content", "")
        if len(content) > 2000:
            content = content[:2000] + "\n// … truncated"
        lang = _lang_hint(fp)
        header = f"### `{fp}`" + (f" — `{sym}`" if sym else "")
        code_fence = f"```{lang}\n{content}\n```"
        parts.append(f"{header}\n{code_fence}")
    return "\n\n".join(parts)


def _build_query_prompt(
    question: str,
    memories: List[Dict[str, Any]],
    consolidations: List[Dict[str, Any]],
    context: Optional[Dict[str, Any]],
    vector_chunks: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Format retrieved data for the user message.

    Global context is placed FIRST so the LLM prioritizes it for broad
    questions. Vector search results come next (most semantically
    relevant code), followed by file memories and consolidation insights.

    Each section is clearly labelled so the LLM can reference and quote
    specific code blocks in its answer.

    Args:
        question:        User question.
        memories:        Simplified memory dicts.
        consolidations:  Consolidation row dicts (subset of columns).
        context:         ``repo_context`` row or ``None``.
        vector_chunks:   Semantically similar code chunks (optional).

    Returns:
        Single user message string for the chat completion.
    """
    ctx_block = _format_context_summary(context)
    mem_block = json.dumps(memories, ensure_ascii=False, default=str)
    cons_block = json.dumps(consolidations, ensure_ascii=False, default=str)

    sections = [f"# Question\n{question}"]

    sections.append(
        f"\n# Global Project Context\n"
        f"Use this to answer high-level/broad questions. Contains architecture, "
        f"tech stack, features, API surface, and dependency graph.\n\n{ctx_block}"
    )

    if vector_chunks:
        code_block = _format_vector_hits(vector_chunks)
        sections.append(
            f"\n# Relevant Source Code ({len(vector_chunks)} snippets)\n"
            f"These are the most semantically relevant code chunks from the repo. "
            f"You may quote these directly in your answer using fenced code blocks.\n\n"
            f"{code_block}"
        )

    if memories:
        sections.append(
            f"\n# File Memories ({len(memories)} files)\n"
            f"Structured metadata per file — includes purpose, functions/classes, "
            f"imports, internal dependencies, and patterns.\n\n{mem_block}"
        )

    if consolidations:
        sections.append(
            f"\n# Consolidation Insights ({len(consolidations)} entries)\n"
            f"Cross-file architectural observations, patterns, and tech debt.\n\n"
            f"{cons_block}"
        )

    sections.append(
        "\n# Instructions\n"
        "Answer using ONLY the above data. Follow the response guidelines "
        "from the system prompt:\n"
        "- Use markdown headings, bullet points, and numbered steps.\n"
        "- Embed code snippets from the Relevant Source Code section when helpful.\n"
        "- Include a Mermaid diagram for architecture/flow questions.\n"
        "- Cite exact file paths and function names.\n"
        "- Respond with the JSON object as specified (no wrapping fences around "
        "the JSON itself)."
    )

    return "\n".join(sections)


def _sanitize_mermaid(answer: str) -> str:
    """Fix common Mermaid syntax errors produced by LLMs.

    Corrects the invalid ``-->|label|>`` arrow pattern to ``-->|label|``
    and strips embedded JSON/markdown code blocks that duplicate the
    answer payload.

    Args:
        answer: Markdown answer string.

    Returns:
        Sanitized answer.
    """
    answer = re.sub(r'-->\|([^|]*)\|>', r'-->|\1|', answer)

    answer = re.sub(
        r'```json\s*\n\s*\{\s*"answer"\s*:[\s\S]*?```',
        '',
        answer,
    ).rstrip()

    return answer


def _strip_trailing_json_dupe(answer: str) -> str:
    """Remove a duplicate JSON blob the LLM sometimes appends after markdown.

    Some models output the markdown answer as free text, then append the
    same content wrapped in a ``{"answer": ...}`` JSON object.  This
    strips everything from the first ``{"answer":`` onwards if it appears
    after substantial markdown content.

    Args:
        answer: Raw answer string (may contain trailing JSON).

    Returns:
        Cleaned answer with trailing JSON removed.
    """
    match = re.search(r'\n\s*\{\s*\n?\s*"answer"\s*:', answer)
    if match and match.start() > 100:
        return answer[: match.start()].rstrip()
    return answer


def _parse_query_llm_output(raw: str) -> Dict[str, Any]:
    """Parse LLM JSON into answer and cited_files.

    Handles the common case where the LLM outputs markdown first and
    then a JSON wrapper — extracts the JSON and cleans the answer of
    any duplicate trailing blob.

    Args:
        raw: Raw assistant output.

    Returns:
        Dict with keys ``answer`` (str) and ``cited_files`` (list).

    Raises:
        None.
    """
    def _clean(text: str) -> str:
        return _sanitize_mermaid(_strip_trailing_json_dupe(text))

    try:
        inner = _strip_json_fence(raw)
        data = json.loads(inner)
        if isinstance(data, dict):
            ans = _clean(str(data.get("answer") or ""))
            cf = data.get("cited_files")
            files = [str(x) for x in cf] if isinstance(cf, list) else []
            return {"answer": ans, "cited_files": files}
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass

    json_match = re.search(r'\{\s*"answer"\s*:', raw or "")
    if json_match:
        try:
            data = json.loads(raw[json_match.start():])
            if isinstance(data, dict):
                ans = _clean(str(data.get("answer") or ""))
                cf = data.get("cited_files")
                files = [str(x) for x in cf] if isinstance(cf, list) else []
                return {"answer": ans, "cited_files": files}
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass

    return {"answer": _clean((raw or "").strip()), "cited_files": []}


def _relevant_memories_payload(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Shape memory rows returned to API callers.

    Args:
        rows: Full memory rows used for answering.

    Returns:
        List of dicts with ``file_path``, ``summary``, ``importance_score``.

    Raises:
        None.
    """
    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "file_path": r.get("file_path"),
                "summary": r.get("summary"),
                "importance_score": r.get("importance_score"),
            }
        )
    return out


def _run_query_llm(user_prompt: str, gen: Generator) -> str:
    """Execute the query chat completion without a token cap.

    Unlike ingest completions, query answers can be lengthy (markdown with
    code blocks, mermaid diagrams, tables, etc.) so ``max_tokens`` is
    omitted to let the provider use the full remaining context window.

    Args:
        user_prompt: Full user message from ``_build_query_prompt``.
        gen:         ``Generator`` instance.

    Returns:
        Raw assistant string.

    Raises:
        RuntimeError: If the LLM call fails.
    """
    messages = [
        {"role": "system", "content": QUERY_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    return _ingest_chat_completion(messages, gen, max_tokens=None)


def _sort_by_importance(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sort memory rows by importance_score descending.

    Files with the highest importance scores appear first in the prompt
    so the LLM prioritizes them.

    Args:
        rows: Memory row dicts.

    Returns:
        Sorted list (original list is not mutated).
    """
    def _score(r: Dict[str, Any]) -> float:
        try:
            return float(r.get("importance_score") or 0)
        except (ValueError, TypeError):
            return 0.0
    return sorted(rows, key=_score, reverse=True)


def answer_question(
    repo_id: str,
    question: str,
    generator: Optional[Generator] = None,
) -> Dict[str, Any]:
    """Answer a user question using vector search, memories, and context.

    Retrieval strategy:
    1. Vector search on code chunks for semantic relevance.
    2. Keyword search on file memories for text/topic/entity matches.
    3. Global ``repo_context`` is always included.
    4. Consolidation insights filtered by keyword relevance.

    Memories are sorted by importance_score so the LLM sees the most
    significant files first.

    Args:
        repo_id:   Repository UUID.
        question:  Natural-language question.
        generator: Optional ``Generator`` for the completion.

    Returns:
        Dict with ``answer``, ``cited_files``, ``relevant_memories``.

    Raises:
        RepoNotFoundError: If the repository does not exist.
        ValueError: If API keys are missing when ``generator`` is omitted.
        RuntimeError: If the LLM call fails.
    """
    if repo_db.find_by_id(repo_id) is None:
        raise RepoNotFoundError(f"Repository not found: {repo_id}")
    repo_memory_db.ensure_table()
    repo_context_db.ensure_table()
    gen = _ensure_generator(generator)

    keywords = _extract_keywords(question)

    vector_chunks = _vector_search_chunks(repo_id, question)

    memories = _gather_initial_memories(repo_id, keywords)

    vector_file_paths = {ch.get("file_path") for ch in vector_chunks if ch.get("file_path")}
    if vector_file_paths:
        for fp in vector_file_paths:
            extra_rows = repo_memory_db.search_by_text(repo_id, fp.rsplit("/", 1)[-1])
            memories = _dedupe_memory_rows(memories + extra_rows)

    if len(memories) < MIN_MEMORIES_FOR_QUERY_MATCH:
        extra = _broader_memory_search(repo_id, question)
        memories = _dedupe_memory_rows(memories + extra)

    memories = _sort_by_importance(memories)

    cons_all = repo_context_db.list_consolidations(repo_id)
    consolidations = _filter_consolidations(cons_all, keywords)
    if not consolidations and cons_all:
        consolidations = cons_all[:]

    context_row = repo_context_db.find_by_repo_id(repo_id)

    slim = _simplify_memories_for_prompt(memories)
    user_prompt = _build_query_prompt(
        question, slim, consolidations, context_row,
        vector_chunks=vector_chunks,
    )
    raw = _run_query_llm(user_prompt, gen)
    parsed = _parse_query_llm_output(raw)
    cited = parsed.get("cited_files") or []
    if not cited:
        all_paths: List[str] = []
        for ch in vector_chunks[:5]:
            fp = ch.get("file_path")
            if fp and fp not in all_paths:
                all_paths.append(fp)
        for r in memories[:10]:
            fp = str(r.get("file_path", ""))
            if fp and fp not in all_paths:
                all_paths.append(fp)
        cited = all_paths
    return {
        "answer": parsed.get("answer") or "",
        "cited_files": cited,
        "relevant_memories": _relevant_memories_payload(memories),
    }
