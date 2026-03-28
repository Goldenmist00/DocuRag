"""
Autonomous coding agent: multi-turn LLM loop with tools and session persistence.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.agents.agent_tools import AGENT_TOOLS
from src.agents import event_bus
from src.agents.llm_client import chat_completion, extract_tool_calls, get_assistant_content
from src.agents.tool_executor import ToolExecutor, ToolResult
from src.git import worktree_service
from src.config.repo_constants import (
    AGENT_COMPACTION_TAIL_MESSAGES,
    AGENT_CONVERSATION_CHAR_BUDGET,
    AGENT_SESSION_STATUS_RUNNING,
    AGENT_SESSION_STEP_CHAT,
    CONTEXT_COMPACTION_THRESHOLD,
    MAX_AGENT_TURNS,
    SESSION_STATUS_AWAITING_INPUT,
)
from src.db import session_db

logger = logging.getLogger(__name__)

CODING_AGENT_SYSTEM_PROMPT = """You are an expert software engineer working in a git worktree.
You have tools to read, write, edit files, search code, run commands, and ask
the user for clarification when needed.

PROJECT CONTEXT:
__CONTEXT__
__RELEVANT_FILES__
YOUR TASK:
__TASK__

═══════════════════════════════════════════════════════════
EDITING TOOLS — choose the right one (ordered by reliability):
═══════════════════════════════════════════════════════════

1. rewrite_file(path, content)  ★ MOST RELIABLE
   Outputs the COMPLETE new file. Use for:
   - Any edit that changes more than ~5 lines
   - When edit_file has failed even once on this file
   - When you need to restructure or heavily modify a file
   Always read_file first, then output the full corrected content.

2. write_file(path, content)
   Creates a brand-new file (or overwrites). Use ONLY for new files.

3. patch_file(path, start_line, end_line, new_content)
   Replaces a line range using numbers from read_file output.
   Use for surgical edits in very large files (500+ lines) where
   outputting the whole file is too expensive.

4. edit_file(path, old_text, new_text)  ← LEAST RELIABLE
   Replaces the first occurrence of old_text. Has fuzzy whitespace
   matching but still fragile. Use ONLY for trivial 1-2 line changes
   where you are confident old_text is unique and correct.

RULE: If edit_file fails, do NOT retry with slightly different old_text.
Switch to rewrite_file immediately — read the file and output it fully
with your changes applied.

═══════════════════════════════════════════════════════════
WORKFLOW — follow these in order, one step at a time:
═══════════════════════════════════════════════════════════

1. EXPLORE FIRST: Use search_code and list_directory to find where the relevant
   code lives. NEVER guess file paths — always verify.
2. READ before you edit: read every file you plan to change so you understand it.
   read_file output includes line numbers (format: "     N|content").
3. Make minimal, focused changes — don't refactor unrelated code.
4. Pick the right editing tool from the hierarchy above.
5. VERIFY after editing: re-read the file to confirm your edit took effect.
   If a LINT ERROR message appears after your edit, fix it before proceeding.
6. If the project has tests, run them after making changes.
7. Do NOT commit changes — the user will review and commit from the UI.

THOROUGHNESS — rename, refactor, and project-wide tasks:
- For tasks involving renaming, replacing text across the project, or
  refactoring, you MUST search the ENTIRE repository (path ".") for ALL
  occurrences using search_code before starting edits.
- Edit EVERY file that contains a match — not just the first one you find.
- Try multiple search patterns: exact match, case-insensitive variations,
  and partial patterns.
- After editing all files, run a final search_code to confirm zero remaining
  occurrences of the old text.
- NEVER call done() if there are still unedited occurrences.

ASKING THE USER — use ask_user when:
- The task is ambiguous and multiple interpretations are possible.
- You need to choose between significantly different approaches.
- You found occurrences in config files, package names, or other sensitive
  locations and want confirmation before changing them.
- Do NOT ask for obvious things — proceed without asking.

RECOVERY — when tools fail:
- If search_code returns empty, widen the search: path "." for the whole
  repo, or try case variations and partial patterns.
- If a file is "Not a file or does not exist", verify the name via
  list_directory — do NOT guess extensions.
- If edit_file fails, STOP trying edit_file on that file.
  Use rewrite_file: read_file first, then output the complete corrected file.
- NEVER repeat the same failing tool call with identical arguments.

CRITICAL — done() usage:
- NEVER call done() in the same turn as your first tool call.
- NEVER call done() alongside editing tools or run_command in the same
  response. Finish your work first, verify it, THEN call done() alone.
- done() will be REJECTED if no file was modified during the session.
- If any tool returned an error, fix the problem before calling done().

SUMMARY FORMAT — when calling done(), your summary MUST follow this structure:
## Approach
Brief description of the strategy you took (1-3 sentences).

## Changes
- path/to/file1: What was changed and why
- path/to/file2: What was changed and why

## Verification
How you confirmed the changes work (e.g. re-read files, ran tests, searched for remaining occurrences).

## Notes
Any caveats, edge cases, or things the user should review (omit if none)."""

EDIT_FAILURE_ESCALATION_THRESHOLD = 2
"""After this many consecutive edit_file failures on the same file, inject a
system message forcing the agent to switch to rewrite_file."""

MAX_IDENTICAL_CALL_REPEATS = 2
"""If the same tool+args combination appears this many times, inject a loop
breaker message."""


def _context_text(repo_context: Any) -> str:
    """Serialize repository context for the system prompt.

    Args:
        repo_context: Arbitrary context (often str or JSON-serializable dict).

    Returns:
        A string embedded in the system prompt.

    Raises:
        This function does not raise.
    """
    if isinstance(repo_context, str):
        return repo_context
    try:
        return json.dumps(repo_context, indent=2, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(repo_context)


def _maybe_compact_conversation(messages: list) -> list:
    """Drop older turns when the serialized conversation exceeds the threshold.

    Args:
        messages: OpenAI-style message list (system first when present).

    Returns:
        Possibly shortened message list.

    Raises:
        This function does not raise.
    """
    if not messages:
        return messages
    try:
        serialized = json.dumps(messages)
    except (TypeError, ValueError):
        return messages
    limit = int(AGENT_CONVERSATION_CHAR_BUDGET * CONTEXT_COMPACTION_THRESHOLD)
    if len(serialized) <= limit:
        return messages
    if messages[0].get("role") == "system":
        return [messages[0]] + messages[-AGENT_COMPACTION_TAIL_MESSAGES:]
    return messages[-AGENT_COMPACTION_TAIL_MESSAGES:]


def _assistant_message_from_response(response: dict) -> dict[str, Any]:
    """Build an assistant message dict from a chat completion payload.

    Args:
        response: Parsed provider JSON.

    Returns:
        Message dict suitable to append to ``conversation``.

    Raises:
        This function does not raise.
    """
    choices = response.get("choices") or []
    if not choices:
        return {"role": "assistant", "content": ""}
    raw = (choices[0] or {}).get("message")
    if not isinstance(raw, dict):
        return {"role": "assistant", "content": ""}
    out = dict(raw)
    out.setdefault("role", "assistant")
    return out


def _format_tool_result(result: ToolResult) -> str:
    """Format a tool result as JSON text for the model.

    Args:
        result: Outcome from :class:`ToolExecutor`.

    Returns:
        UTF-8 JSON string with success, output, and error fields.

    Raises:
        This function does not raise.
    """
    payload = {
        "success": result.success,
        "output": result.output,
        "error": result.error,
    }
    return json.dumps(payload, ensure_ascii=False)


def _tokens_from_response(response: dict) -> int:
    """Read total token usage from a completion response.

    Args:
        response: Parsed provider JSON.

    Returns:
        ``usage.total_tokens`` if present, else ``0``.

    Raises:
        This function does not raise.
    """
    usage = response.get("usage") or {}
    try:
        return int(usage.get("total_tokens") or 0)
    except (TypeError, ValueError):
        return 0


@dataclass
class AgentResult:
    """Outcome of a :class:`CodingAgent` run.

    Attributes:
        summary: Final or best-effort summary text.
        agent_log: Ordered log entries for tools and outcomes.
        total_llm_calls: Number of LLM completions requested.
        total_tokens_used: Sum of reported ``total_tokens`` from responses.
        completed: Whether the agent finished via ``done`` or a text-only stop.
    """

    summary: str
    agent_log: list = field(default_factory=list)
    total_llm_calls: int = 0
    total_tokens_used: int = 0
    completed: bool = False


class CodingAgent:
    """Tool-calling agent confined to one worktree with DB-backed progress."""

    def __init__(
        self,
        session_id: str,
        worktree_path: str,
        repo_context: Any,
        task: str,
        seed_messages: Optional[List[Dict[str, Any]]] = None,
        repo_id: Optional[str] = None,
    ) -> None:
        """Store run parameters and prepare executor and mutable state.

        Args:
            session_id: UUID of the ``agent_sessions`` row.
            worktree_path: Root path of the git worktree.
            repo_context: Project context string or structured snapshot.
            task: User task description.
            seed_messages: Optional pre-filled conversation messages
                (e.g. notebook context) injected after the system prompt.
            repo_id: Repository UUID for querying indexed memories (optional).

        Returns:
            None

        Raises:
            This function does not raise.
        """
        self.session_id = session_id
        self.worktree_path = worktree_path
        self.repo_context = repo_context
        self.task = task
        self.seed_messages = seed_messages or []
        self._executor = ToolExecutor(worktree_path, repo_id=repo_id)
        self.conversation: list = []
        self.agent_log: list = []
        self._turn_counter = 0
        self._pending_question: Optional[str] = None
        self._checkpoint_counter = 0
        self._edit_failures: Dict[str, int] = {}
        self._call_history: List[str] = []

    def _pre_query_vector_search(self) -> str:
        """Run a vector similarity search for the task to pre-select relevant code.

        Returns actual code snippets from the ``repo_code_chunks`` table
        rather than just file summaries, giving the agent concrete context.

        Returns:
            Formatted string of relevant code snippets, or empty string.
        """
        if not self._executor._repo_id:
            return ""

        try:
            from src.db import repo_code_chunk_db
            from src.embedder import get_embedder

            embedder = get_embedder()
            query_vec = embedder.embed(self.task, use_cache=True).tolist()
            chunks = repo_code_chunk_db.search_similar(
                self._executor._repo_id,
                query_vec,
                limit=10,
                threshold=0.4,
            )
            if not chunks:
                return ""

            parts = ["## Pre-selected code snippets (vector search)\n"]
            for ch in chunks:
                fp = ch.get("file_path", "?")
                sym = ch.get("symbol_name", "")
                content = ch.get("content", "")
                if len(content) > 2000:
                    content = content[:2000] + "..."
                label = f"{fp}::{sym}" if sym else fp
                parts.append(f"### {label}")
                parts.append(f"```\n{content}\n```\n")

            return "\n".join(parts)
        except Exception as exc:
            logger.debug("Vector pre-query unavailable: %s", exc)
            return ""

    def _build_system_prompt(self, relevant_files: str = "") -> str:
        """Build the system prompt with context, task, and optional pre-selected files.

        Uses safe string replacement instead of ``.format()`` to avoid
        issues with braces in JSON context payloads.

        Args:
            relevant_files: Pre-queried file summaries from the knowledge base.

        Returns:
            Rendered system prompt string.

        Raises:
            This function does not raise.
        """
        ctx = _context_text(self.repo_context)
        relevant_section = ""
        if relevant_files:
            relevant_section = (
                "\nRELEVANT FILES (pre-selected for your task):\n"
                + relevant_files
                + "\n"
            )
        return (
            CODING_AGENT_SYSTEM_PROMPT
            .replace("__CONTEXT__", ctx)
            .replace("__RELEVANT_FILES__", relevant_section)
            .replace("__TASK__", self.task)
        )

    def _log_action(
        self,
        tool_name: str,
        arguments: dict,
        result: ToolResult,
    ) -> None:
        """Append one structured entry to the in-memory agent log.

        Args:
            tool_name: Tool that ran.
            arguments: Arguments passed to the tool.
            result: Execution outcome.

        Returns:
            None

        Raises:
            This function does not raise.
        """
        self.agent_log.append(
            {
                "tool": tool_name,
                "arguments": arguments,
                "success": result.success,
                "output": result.output,
                "error": result.error,
            }
        )

    def _persist_session_progress(
        self,
        summary: str,
        total_llm_calls: int,
        total_tokens_used: int,
    ) -> None:
        """Write log, conversation, counters, and status to the database.

        Args:
            summary: Latest summary or placeholder text.
            total_llm_calls: Cumulative LLM calls so far.
            total_tokens_used: Cumulative token estimate.

        Returns:
            None

        Raises:
            psycopg2.Error: If a database update fails.
        """
        step = f"{AGENT_SESSION_STEP_CHAT}:{self._turn_counter + 1}"
        session_db.update_session_status(
            self.session_id,
            AGENT_SESSION_STATUS_RUNNING,
            current_step=step,
        )
        session_db.update_session_log(self.session_id, self.agent_log, [])
        session_db.update_conversation_history(self.session_id, self.conversation)
        session_db.update_session_result(
            self.session_id,
            summary or "In progress",
            total_llm_calls,
            total_tokens_used,
        )

    async def _invoke_llm(self) -> dict:
        """Run ``chat_completion`` in a worker thread.

        Args:
            None

        Returns:
            Parsed completion JSON.

        Raises:
            Exception: Propagates errors from ``chat_completion``.
        """
        return await asyncio.to_thread(chat_completion, self.conversation, AGENT_TOOLS)

    def _has_working_tree_changes(self) -> bool:
        """Check whether the worktree has uncommitted file changes.

        Returns:
            True if ``git status --porcelain`` reports any modified/new files.
        """
        import subprocess
        try:
            proc = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.worktree_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return bool(proc.stdout.strip())
        except Exception:
            return False

    def _any_tool_failed(self) -> bool:
        """Return True if at least one non-done tool in the log failed.

        Returns:
            True when at least one non-done entry has ``success == False``.
        """
        return any(
            not entry.get("success") and entry.get("tool") != "done"
            for entry in self.agent_log
        )

    def _any_file_modified(self) -> bool:
        """Return True if at least one edit_file or write_file succeeded in the session.

        Scans the entire agent_log to confirm the agent actually changed something
        before allowing done() to succeed.

        Returns:
            True when at least one file-mutating tool call succeeded.
        """
        file_mutators = {"edit_file", "write_file", "patch_file", "rewrite_file"}
        return any(
            entry.get("success") and entry.get("tool") in file_mutators
            for entry in self.agent_log
        )

    async def _handle_tool_calls(
        self,
        response: dict,
        tool_calls: list,
    ) -> Tuple[bool, str, bool]:
        """Append assistant + tool messages and execute each tool call.

        When ``done()`` is batched alongside other tools it is deferred:
        the non-done tools run first; if any failed or no file changes exist,
        ``done()`` is rejected so the agent gets another turn to fix things.

        When ``ask_user`` is called, execution is paused: the question is
        logged, session status set to ``awaiting_input``, and the loop breaks.

        Args:
            response: Raw completion used to recover the assistant message.
            tool_calls: Normalized tool invocations from ``extract_tool_calls``.

        Returns:
            ``(done_called, summary_if_done, ask_user_called)`` — the third
            element is True when the agent wants to pause for user input.

        Raises:
            This function does not raise; tool errors are returned in messages.
        """
        self.conversation.append(_assistant_message_from_response(response))
        summary = ""
        done_called = False
        ask_user_called = False

        control_tools = {"done", "ask_user"}
        regular_calls = [c for c in tool_calls if (c.get("name") or "") not in control_tools]
        done_calls = [c for c in tool_calls if (c.get("name") or "") == "done"]
        ask_calls = [c for c in tool_calls if (c.get("name") or "") == "ask_user"]

        read_only = frozenset({"read_file", "list_directory", "search_code", "query_context"})
        read_indices = [
            i for i, c in enumerate(regular_calls)
            if (c.get("name") or "") in read_only
        ]
        mutate_indices = [
            i for i, c in enumerate(regular_calls)
            if (c.get("name") or "") not in read_only
        ]

        tool_names = [c.get("name") or "unknown" for c in regular_calls]
        await event_bus.emit(self.session_id, "tool_start", {"tools": tool_names})

        async def _run_one(idx: int) -> Tuple[int, dict, str, dict, ToolResult]:
            call = regular_calls[idx]
            nm = call.get("name") or ""
            ag = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
            res = await asyncio.to_thread(self._executor.execute, nm, ag)
            await event_bus.emit(self.session_id, "tool_result", {
                "tool": nm, "success": res.success, "step": idx,
            })
            return idx, call, nm, ag, res

        results_map: dict[int, Tuple[dict, str, dict, ToolResult]] = {}

        if read_indices:
            read_results = await asyncio.gather(*[_run_one(i) for i in read_indices])
            for idx, call, nm, ag, res in read_results:
                results_map[idx] = (call, nm, ag, res)

        for i in mutate_indices:
            idx, call, nm, ag, res = await _run_one(i)
            results_map[idx] = (call, nm, ag, res)

        mutating_tools = frozenset({"edit_file", "write_file", "patch_file", "rewrite_file"})
        edits_in_batch = 0
        lint_messages: list[str] = []

        escalation_messages: list[str] = []

        for i in range(len(regular_calls)):
            call, name, args, result = results_map[i]
            self._log_action(name, args, result)
            self.conversation.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id") or "",
                    "content": _format_tool_result(result),
                }
            )

            call_sig = f"{name}:{json.dumps(args, sort_keys=True)}"
            self._call_history.append(call_sig)

            if name == "edit_file" and not result.success:
                fpath = str(args.get("path", ""))
                self._edit_failures[fpath] = self._edit_failures.get(fpath, 0) + 1
                if self._edit_failures[fpath] >= EDIT_FAILURE_ESCALATION_THRESHOLD:
                    escalation_messages.append(
                        f"[SYSTEM] edit_file has failed {self._edit_failures[fpath]} "
                        f"times on '{fpath}'. STOP using edit_file for this file. "
                        f"Use rewrite_file instead: call read_file('{fpath}') to get "
                        f"the current content, then call rewrite_file('{fpath}', "
                        f"<complete corrected content>)."
                    )
            elif name == "edit_file" and result.success:
                fpath = str(args.get("path", ""))
                self._edit_failures.pop(fpath, None)

            recent = self._call_history[-MAX_IDENTICAL_CALL_REPEATS:]
            if (
                len(recent) == MAX_IDENTICAL_CALL_REPEATS
                and len(set(recent)) == 1
            ):
                escalation_messages.append(
                    f"[SYSTEM] You called {name} with identical arguments "
                    f"{MAX_IDENTICAL_CALL_REPEATS} times in a row. This is a loop. "
                    f"Try a completely different approach: use rewrite_file to "
                    f"output the full corrected file, or use a different tool."
                )

            if result.success and name in mutating_tools:
                edits_in_batch += 1
                lint_out = await asyncio.to_thread(
                    self._executor.lint_file, str(args.get("path", "")),
                )
                if lint_out:
                    lint_messages.append(f"{args.get('path', '')}: {lint_out}")

        if escalation_messages:
            self.conversation.append(
                {
                    "role": "system",
                    "content": "\n".join(escalation_messages),
                }
            )

        if edits_in_batch > 0:
            self._checkpoint_counter += 1
            try:
                await asyncio.to_thread(
                    worktree_service.create_checkpoint,
                    self.worktree_path,
                    self._checkpoint_counter,
                )
            except Exception:
                logger.debug("Checkpoint %d skipped", self._checkpoint_counter)

        if lint_messages:
            await event_bus.emit(self.session_id, "lint_error", {
                "errors": lint_messages,
            })
            self.conversation.append(
                {
                    "role": "system",
                    "content": (
                        "[LINT ERRORS detected after edits — fix before calling done()]\n"
                        + "\n".join(lint_messages)
                    ),
                }
            )

        for call in ask_calls:
            args = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
            result = await asyncio.to_thread(self._executor.execute, "ask_user", args)
            self._log_action("ask_user", args, result)
            self.conversation.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id") or "",
                    "content": _format_tool_result(result),
                }
            )
            if result.success:
                ask_user_called = True
                self._pending_question = result.output
                break

        if ask_user_called:
            return done_called, summary, ask_user_called

        for call in done_calls:
            args = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}

            if regular_calls and self._any_tool_failed():
                reject_msg = (
                    "done() rejected: other tools in this batch failed. "
                    "Review the errors, fix them, and call done() again."
                )
                logger.warning("Rejecting premature done() — sibling tools failed")
                fail_result = ToolResult(
                    tool_name="done", success=False, output="", error=reject_msg,
                )
                self._log_action("done", args, fail_result)
                self.conversation.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id") or "",
                        "content": _format_tool_result(fail_result),
                    }
                )
                continue

            if not self._any_file_modified() and not self._has_working_tree_changes():
                reject_msg = (
                    "done() rejected: no files were modified during this session. "
                    "No edit_file or write_file call succeeded. "
                    "Search more broadly (use path '.' for the whole repo), "
                    "check exact file names from list_directory output, "
                    "and try again."
                )
                logger.warning(
                    "Rejecting done() — no file modifications in session %s",
                    self.session_id,
                )
                fail_result = ToolResult(
                    tool_name="done", success=False, output="", error=reject_msg,
                )
                self._log_action("done", args, fail_result)
                self.conversation.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id") or "",
                        "content": _format_tool_result(fail_result),
                    }
                )
                continue

            result = await asyncio.to_thread(self._executor.execute, "done", args)
            self._log_action("done", args, result)
            if result.success:
                done_called = True
                summary = result.output
            self.conversation.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id") or "",
                    "content": _format_tool_result(result),
                }
            )

        return done_called, summary, ask_user_called

    def _append_text_only_assistant(self, response: dict) -> None:
        """Record a non-tool assistant turn in the conversation.

        Args:
            response: Provider completion JSON.

        Returns:
            None

        Raises:
            This function does not raise.
        """
        self.conversation.append(_assistant_message_from_response(response))

    def _abort_on_llm_error(
        self,
        exc: BaseException,
        total_llm: int,
        tokens: int,
    ) -> AgentResult:
        """Mark the session failed and return a result after an LLM error.

        Args:
            exc: Exception from ``chat_completion``.
            total_llm: LLM calls completed before the failure.
            tokens: Tokens accumulated before the failure.

        Returns:
            :class:`AgentResult` with ``completed`` False.

        Raises:
            psycopg2.Error: If the database update fails.
        """
        logger.exception("chat_completion failed for session %s", self.session_id)
        err_msg = str(exc)
        session_db.mark_session_failed(self.session_id, err_msg)
        session_db.update_session_log(self.session_id, self.agent_log, [])
        return AgentResult(
            summary=err_msg,
            agent_log=list(self.agent_log),
            total_llm_calls=total_llm,
            total_tokens_used=tokens,
            completed=False,
        )

    def _mark_terminal_session_status(self, completed: bool, summary: str) -> None:
        """Set completed or failed status after the agent loop ends.

        Args:
            completed: Whether the agent finished successfully.
            summary: Final summary or failure explanation.

        Returns:
            None

        Raises:
            psycopg2.Error: If the database update fails.
        """
        if completed:
            session_db.mark_session_completed(self.session_id, summary)
        else:
            session_db.mark_session_failed(self.session_id, summary)

    async def run(self) -> AgentResult:
        """Execute up to :data:`MAX_AGENT_TURNS` LLM rounds with tools.

        Args:
            None

        Returns:
            :class:`AgentResult` with logs and completion flag.

        Raises:
            psycopg2.Error: If database updates fail after successful LLM work.
        """
        summary = ""
        total_llm = 0
        tokens = 0
        completed = False

        relevant_files = ""
        try:
            relevant_files = await asyncio.to_thread(
                self._pre_query_vector_search,
            )
        except Exception:
            logger.debug("Vector pre-query failed, falling back to tool query")
        if not relevant_files or len(relevant_files) < 50:
            try:
                pre = await asyncio.to_thread(
                    self._executor.execute, "query_context", {"question": self.task},
                )
                if pre.success and len(pre.output) > 50:
                    relevant_files = pre.output
            except Exception:
                logger.debug("Pre-context query skipped")

        self.conversation = [
            {"role": "system", "content": self._build_system_prompt(relevant_files)},
        ]
        if self.seed_messages:
            self.conversation.extend(self.seed_messages)
        event_bus.get_or_create_queue(self.session_id)

        session_db.update_session_status(
            self.session_id,
            AGENT_SESSION_STATUS_RUNNING,
            current_step=AGENT_SESSION_STEP_CHAT,
        )
        for turn in range(MAX_AGENT_TURNS):
            self._turn_counter = turn
            self.conversation = _maybe_compact_conversation(self.conversation)
            await event_bus.emit(self.session_id, "thinking", {"turn": turn + 1})
            try:
                response = await self._invoke_llm()
            except Exception as exc:
                return self._abort_on_llm_error(exc, total_llm, tokens)
            total_llm += 1
            tokens += _tokens_from_response(response)
            calls = extract_tool_calls(response)
            if calls:
                done_now, sum_done, asked = await self._handle_tool_calls(response, calls)
                if sum_done:
                    summary = sum_done
                self._persist_session_progress(summary, total_llm, tokens)
                if asked and self._pending_question:
                    await event_bus.emit(self.session_id, "ask_user", {
                        "question": self._pending_question,
                    })
                    session_db.update_session_status(
                        self.session_id,
                        SESSION_STATUS_AWAITING_INPUT,
                        current_step=f"ask_user:{self._turn_counter + 1}",
                    )
                    return AgentResult(
                        summary=self._pending_question,
                        agent_log=list(self.agent_log),
                        total_llm_calls=total_llm,
                        total_tokens_used=tokens,
                        completed=False,
                    )
                if done_now:
                    completed = True
                    break
            else:
                self._append_text_only_assistant(response)
                summary = get_assistant_content(response)
                completed = True
                self._persist_session_progress(summary, total_llm, tokens)
                break
        else:
            summary = summary or "Stopped: max turns reached without done()."
            self._persist_session_progress(summary, total_llm, tokens)
        self._mark_terminal_session_status(completed, summary)
        await event_bus.emit(
            self.session_id,
            "done" if completed else "error",
            {"summary": summary},
        )
        event_bus.remove_queue(self.session_id)
        return AgentResult(
            summary=summary,
            agent_log=list(self.agent_log),
            total_llm_calls=total_llm,
            total_tokens_used=tokens,
            completed=completed,
        )
