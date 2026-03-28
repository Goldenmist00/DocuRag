"""
Sandboxed execution layer for DocuRag coding-agent tool calls.

Maps LLM tool names to filesystem, subprocess, and git operations confined
to a single worktree, with timeouts, output caps, and safety checks.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from src.config.repo_constants import (
    AGENT_CONTEXT_QUERY_PLACEHOLDER,
    AGENT_SEARCH_MAX_MATCHES,
    BLOCKED_COMMANDS,
    LINT_CHECK_TIMEOUT_SECONDS,
    MAX_FILE_SIZE_BYTES,
    MAX_TOOL_OUTPUT_BYTES,
    MIN_MEMORIES_FOR_QUERY_MATCH,
    QUERY_KEYWORD_MIN_LENGTH,
    QUERY_KEYWORD_STOP_WORDS,
    SENSITIVE_FILE_PATTERNS,
    SKIP_DIRS,
    SKIP_EXTENSIONS,
    TOOL_TIMEOUT_SECONDS,
)
from src.utils.repo_errors import PathTraversalError, ToolExecutionError
from src.utils.repo_validation import (
    is_blocked_command,
    is_sensitive_file,
    sanitize_file_path,
)

logger = logging.getLogger(__name__)


@dataclass
class ToolResult:
    """Outcome of a single agent tool invocation.

    Attributes:
        tool_name: Name of the tool that ran.
        success: Whether the operation completed without error.
        output: Primary text payload (stdout, file body, summary, etc.).
        error: Human-readable error when ``success`` is False.
    """

    tool_name: str
    success: bool
    output: str
    error: str = ""


def _decode_truncated(raw: bytes, max_bytes: int) -> str:
    """Decode bytes to text and truncate to a UTF-8 byte budget.

    Args:
        raw: Raw byte string (e.g. subprocess output).
        max_bytes: Maximum number of UTF-8 bytes to keep.

    Returns:
        Decoded text, truncated with an ellipsis marker if needed.

    Raises:
        This function does not raise.
    """
    if len(raw) <= max_bytes:
        return raw.decode("utf-8", errors="replace")
    cut = raw[:max_bytes]
    text = cut.decode("utf-8", errors="replace")
    return f"{text}\n... [truncated at {max_bytes} bytes]"


def _ensure_parent(path: str) -> None:
    """Create parent directories for a file path if missing.

    Args:
        path: Absolute file path whose parent dir should exist.

    Returns:
        None

    Raises:
        OSError: Propagated if creating the parent directory fails.
    """
    parent = Path(path).parent
    parent.mkdir(parents=True, exist_ok=True)


def _git_add_all(worktree: str, timeout: int) -> None:
    """Run ``git add -A`` inside *worktree*.

    Args:
        worktree: Absolute path to the git worktree.
        timeout: Subprocess timeout in seconds.

    Returns:
        None

    Raises:
        subprocess.CalledProcessError: If ``git add`` exits non-zero.
        OSError: If the subprocess cannot be executed.
    """
    subprocess.run(
        ["git", "add", "-A"],
        cwd=worktree,
        capture_output=True,
        check=True,
        timeout=timeout,
        text=True,
    )


def _shell_output(command: str, cwd: str, timeout: int, max_bytes: int) -> tuple[int, str]:
    """Execute *command* under *cwd* and return exit code plus capped text.

    Args:
        command: Shell command string passed to the platform shell.
        cwd: Working directory for the child process.
        timeout: Seconds before ``subprocess`` aborts the run.
        max_bytes: Maximum UTF-8 bytes to keep from merged streams.

    Returns:
        ``(returncode, decoded_output)`` where output may be truncated.

    Raises:
        subprocess.TimeoutExpired: When *timeout* is exceeded.
        OSError: When the subprocess cannot be started.
    """
    proc = subprocess.run(
        command,
        shell=True,
        cwd=cwd,
        capture_output=True,
        timeout=timeout,
    )
    raw_out = proc.stdout + b"\n" + proc.stderr
    return proc.returncode, _decode_truncated(raw_out, max_bytes)


class ToolExecutor:
    """Run agent tools inside one resolved worktree directory."""

    def __init__(self, worktree_path: str, repo_id: Optional[str] = None) -> None:
        """Bind the executor to a worktree root.

        Args:
            worktree_path: Path to the repository worktree (relative or absolute).
            repo_id:       Repository UUID for querying indexed memories (optional).

        Returns:
            None

        Raises:
            OSError: Not raised; path is only stored, not validated here.
        """
        self._worktree_path = str(Path(worktree_path).resolve())
        self._repo_id = repo_id

    def _resolve(self, relative: str) -> str:
        """Resolve *relative* inside the worktree or raise ``PathTraversalError``.

        Args:
            relative: Path relative to the worktree root.

        Returns:
            Absolute normalized path within the sandbox.

        Raises:
            PathTraversalError: When ``sanitize_file_path`` rejects the path.
        """
        try:
            return sanitize_file_path(relative, self._worktree_path)
        except ValueError as exc:
            raise PathTraversalError(str(exc)) from exc

    def _dispatch_tool(self, tool_name: str, args: dict[str, Any]) -> ToolResult:
        """Map *tool_name* and *args* to a concrete ``_exec_*`` call.

        Args:
            tool_name: Tool identifier from the model.
            args: Normalized argument mapping.

        Returns:
            Result from the handler, or an unknown-tool failure.

        Raises:
            This function does not raise.
        """
        handlers: dict[str, Any] = {
            "read_file": lambda a: self._exec_read_file(str(a.get("path", ""))),
            "write_file": lambda a: self._exec_write_file(
                str(a.get("path", "")),
                str(a.get("content", "")),
            ),
            "edit_file": lambda a: self._exec_edit_file(
                str(a.get("path", "")),
                str(a.get("old_text", "")),
                str(a.get("new_text", "")),
            ),
            "rewrite_file": lambda a: self._exec_rewrite_file(
                str(a.get("path", "")),
                str(a.get("content", "")),
            ),
            "patch_file": lambda a: self._exec_patch_file(
                str(a.get("path", "")),
                a.get("start_line", 0),
                a.get("end_line", 0),
                str(a.get("new_content", "")),
            ),
            "list_directory": lambda a: self._exec_list_directory(str(a.get("path", ""))),
            "search_code": lambda a: self._exec_search_code(
                str(a.get("pattern", "")),
                None if a.get("path") is None else str(a.get("path")),
            ),
            "run_command": lambda a: self._exec_run_command(
                str(a.get("command", "")),
                None if a.get("workdir") is None else str(a.get("workdir")),
            ),
            "query_context": lambda a: self._exec_query_context(str(a.get("question", ""))),
            "ask_user": lambda a: self._exec_ask_user(str(a.get("question", ""))),
            "done": lambda a: self._exec_done(str(a.get("summary", ""))),
        }
        fn = handlers.get(tool_name)
        if fn is None:
            return ToolResult(
                tool_name=tool_name,
                success=False,
                output="",
                error=f"Unknown tool: {tool_name}",
            )
        return fn(args)

    def execute(self, tool_name: str, arguments: dict) -> ToolResult:
        """Dispatch *tool_name* to the matching ``_exec_*`` handler.

        Args:
            tool_name: Tool identifier (see ``AGENT_TOOLS``).
            arguments: JSON object from the model (may be empty or invalid).

        Returns:
            A :class:`ToolResult` for the invocation.

        Raises:
            RuntimeError: Not used; errors are returned in ``ToolResult``.
        """
        args: dict[str, Any] = arguments if isinstance(arguments, dict) else {}
        return self._dispatch_tool(tool_name, args)

    def _exec_read_file(self, path: str) -> ToolResult:
        """Read a text file from the sandbox.

        Args:
            path: Relative path from the worktree root.

        Returns:
            :class:`ToolResult` with file contents or an error.

        Raises:
            ToolExecutionError: Not raised; errors are returned in ``ToolResult``.
        """
        name = "read_file"
        try:
            if not path.strip():
                return ToolResult(
                    tool_name=name,
                    success=False,
                    output="",
                    error="path is required",
                )
            abs_path = self._resolve(path)
            if not os.path.isfile(abs_path):
                return ToolResult(
                    tool_name=name,
                    success=False,
                    output="",
                    error="Not a file or does not exist",
                )
            if os.path.getsize(abs_path) > MAX_FILE_SIZE_BYTES:
                return ToolResult(
                    tool_name=name,
                    success=False,
                    output="",
                    error=f"File exceeds MAX_FILE_SIZE_BYTES ({MAX_FILE_SIZE_BYTES})",
                )
            text = Path(abs_path).read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()
            out = "\n".join(f"{i:6d}|{line}" for i, line in enumerate(lines, 1))
            if len(out.encode("utf-8")) > MAX_TOOL_OUTPUT_BYTES:
                out = _decode_truncated(out.encode("utf-8"), MAX_TOOL_OUTPUT_BYTES)
            return ToolResult(tool_name=name, success=True, output=out, error="")
        except PathTraversalError as exc:
            return ToolResult(tool_name=name, success=False, output="", error=str(exc))
        except OSError as exc:
            logger.warning("read_file failed: %s", exc)
            return ToolResult(tool_name=name, success=False, output="", error=str(exc))
        except Exception as exc:
            logger.exception("read_file unexpected error")
            return ToolResult(tool_name=name, success=False, output="", error=str(exc))

    def _exec_write_file(self, path: str, content: str) -> ToolResult:
        """Write or overwrite a file after path and sensitivity checks.

        Args:
            path: Relative destination path.
            content: Full file body to write.

        Returns:
            :class:`ToolResult` describing success or failure.

        Raises:
            PathTraversalError: Not raised; surfaced via ``ToolResult``.
        """
        name = "write_file"
        try:
            if not path.strip():
                return ToolResult(
                    tool_name=name,
                    success=False,
                    output="",
                    error="path is required",
                )
            if is_sensitive_file(path):
                logger.warning(
                    "Blocked sensitive write path=%r patterns=%r",
                    path,
                    SENSITIVE_FILE_PATTERNS,
                )
                return ToolResult(
                    tool_name=name,
                    success=False,
                    output="",
                    error="Refusing to write sensitive file path",
                )
            abs_path = self._resolve(path)
            _ensure_parent(abs_path)
            Path(abs_path).write_text(content, encoding="utf-8", newline="")
            return ToolResult(tool_name=name, success=True, output="written", error="")
        except PathTraversalError as exc:
            return ToolResult(tool_name=name, success=False, output="", error=str(exc))
        except OSError as exc:
            logger.warning("write_file failed: %s", exc)
            return ToolResult(tool_name=name, success=False, output="", error=str(exc))
        except Exception as exc:
            logger.exception("write_file unexpected error")
            return ToolResult(tool_name=name, success=False, output="", error=str(exc))

    @staticmethod
    def _normalize_ws(text: str) -> str:
        """Strip trailing whitespace from each line for fuzzy comparison."""
        return "\n".join(line.rstrip() for line in text.splitlines())

    @staticmethod
    def _normalize_indent(text: str) -> str:
        """Strip all leading and trailing whitespace from each line."""
        return "\n".join(line.strip() for line in text.splitlines())

    def _fuzzy_find_and_replace(
        self, body: str, old_text: str, new_text: str,
    ) -> Optional[str]:
        """Try progressively looser matching strategies to find and replace.

        Strategy 1: Exact match (original behavior).
        Strategy 2: Trailing-whitespace-normalized match.
        Strategy 3: Fully indent-agnostic line match — find the contiguous
                     block in the file whose stripped lines match stripped
                     old_text lines, then replace the original lines.

        Returns:
            The updated file body, or ``None`` if no strategy matched.
        """
        if old_text in body:
            return body.replace(old_text, new_text, 1)

        body_lines = body.splitlines(keepends=True)
        old_lines_raw = old_text.splitlines()

        body_rstripped = [l.rstrip() for l in body.splitlines()]
        old_rstripped = [l.rstrip() for l in old_lines_raw]
        n_old = len(old_rstripped)
        if n_old > 0:
            for i in range(len(body_rstripped) - n_old + 1):
                if body_rstripped[i : i + n_old] == old_rstripped:
                    before = body_lines[:i]
                    after = body_lines[i + n_old :]
                    replacement = new_text
                    if replacement and not replacement.endswith("\n"):
                        replacement += "\n"
                    return "".join(before) + replacement + "".join(after)

        old_stripped = [l.strip() for l in old_lines_raw if l.strip()]
        if not old_stripped:
            return None
        n_stripped = len(old_stripped)
        body_stripped = [l.strip() for l in body.splitlines()]
        for i in range(len(body_stripped) - n_stripped + 1):
            window = body_stripped[i : i + n_stripped]
            non_empty = [w for w in window if w]
            if non_empty == old_stripped:
                match_end = i + n_stripped
                while match_end < len(body_lines) and match_end - i < n_stripped + 3:
                    if body_stripped[match_end].strip():
                        break
                    match_end += 1
                before = body_lines[:i]
                after = body_lines[match_end:]
                replacement = new_text
                if replacement and not replacement.endswith("\n"):
                    replacement += "\n"
                return "".join(before) + replacement + "".join(after)

        return None

    def _edit_file_body(
        self, abs_path: str, old_text: str, new_text: str, name: str
    ) -> ToolResult:
        """Replace the first occurrence of *old_text* with *new_text* using
        progressively looser matching (exact → whitespace-normalized →
        indent-agnostic).

        Args:
            abs_path: Absolute file path inside the worktree.
            old_text: Substring to replace once.
            new_text: Replacement text.
            name: Tool name label for the result.

        Returns:
            Success or validation :class:`ToolResult`.

        Raises:
            OSError: If reading or writing the file fails.
        """
        if not os.path.isfile(abs_path):
            return ToolResult(
                tool_name=name,
                success=False,
                output="",
                error="Not a file or does not exist",
            )
        body = Path(abs_path).read_text(encoding="utf-8", errors="replace")
        updated = self._fuzzy_find_and_replace(body, old_text, new_text)
        if updated is None:
            old_lines = [l.strip() for l in old_text.splitlines() if l.strip()]
            hint = ""
            if old_lines:
                first_line = old_lines[0][:60]
                hint = f" (first non-empty line: '{first_line}')"
            return ToolResult(
                tool_name=name,
                success=False,
                output="",
                error=(
                    f"old_text not found in file (tried exact, whitespace-normalized, "
                    f"and indent-agnostic matching){hint}. "
                    f"Use rewrite_file to output the complete file instead."
                ),
            )
        Path(abs_path).write_text(updated, encoding="utf-8", newline="")
        return ToolResult(tool_name=name, success=True, output="updated", error="")

    def _edit_precheck(self, path: str, old_text: str, name: str) -> Optional[ToolResult]:
        """Validate *path* and *old_text* before resolving or reading the file.

        Args:
            path: Relative path from the worktree root.
            old_text: Substring that must be non-empty.
            name: Tool name for failure results.

        Returns:
            A failed :class:`ToolResult` if validation fails, else ``None``.

        Raises:
            This function does not raise.
        """
        if not path.strip():
            return ToolResult(
                tool_name=name,
                success=False,
                output="",
                error="path is required",
            )
        if old_text == "":
            return ToolResult(
                tool_name=name,
                success=False,
                output="",
                error="old_text must be non-empty",
            )
        if is_sensitive_file(path):
            logger.warning(
                "Blocked sensitive edit path=%r patterns=%r",
                path,
                SENSITIVE_FILE_PATTERNS,
            )
            return ToolResult(
                tool_name=name,
                success=False,
                output="",
                error="Refusing to edit sensitive file path",
            )
        return None

    def _exec_edit_file(self, path: str, old_text: str, new_text: str) -> ToolResult:
        """Apply a single occurrence text replacement in a file.

        Args:
            path: Relative file path.
            old_text: Exact substring to replace once.
            new_text: Replacement substring.

        Returns:
            :class:`ToolResult` with a short status message or error.

        Raises:
            ToolExecutionError: Not raised; errors use ``ToolResult``.
        """
        name = "edit_file"
        try:
            bad = self._edit_precheck(path, old_text, name)
            if bad is not None:
                return bad
            abs_path = self._resolve(path)
            return self._edit_file_body(abs_path, old_text, new_text, name)
        except PathTraversalError as exc:
            return ToolResult(tool_name=name, success=False, output="", error=str(exc))
        except OSError as exc:
            logger.warning("edit_file failed: %s", exc)
            return ToolResult(tool_name=name, success=False, output="", error=str(exc))
        except Exception as exc:
            logger.exception("edit_file unexpected error")
            return ToolResult(tool_name=name, success=False, output="", error=str(exc))

    def _exec_rewrite_file(self, path: str, content: str) -> ToolResult:
        """Rewrite an existing file with entirely new content.

        Unlike ``write_file`` (which creates or overwrites), this tool
        requires the file to already exist and returns a change summary.

        Args:
            path: Relative file path (must exist).
            content: Complete new file content.

        Returns:
            :class:`ToolResult` with a diff summary.
        """
        name = "rewrite_file"
        try:
            if not path.strip():
                return ToolResult(
                    tool_name=name, success=False, output="",
                    error="path is required",
                )
            if is_sensitive_file(path):
                return ToolResult(
                    tool_name=name, success=False, output="",
                    error="Refusing to rewrite sensitive file path",
                )
            abs_path = self._resolve(path)
            if not os.path.isfile(abs_path):
                return ToolResult(
                    tool_name=name, success=False, output="",
                    error="File does not exist — use write_file for new files",
                )
            old_body = Path(abs_path).read_text(encoding="utf-8", errors="replace")
            old_count = len(old_body.splitlines())
            Path(abs_path).write_text(content, encoding="utf-8", newline="")
            new_count = len(content.splitlines())
            return ToolResult(
                tool_name=name,
                success=True,
                output=f"Rewrote {path}: {old_count} → {new_count} lines",
                error="",
            )
        except PathTraversalError as exc:
            return ToolResult(tool_name=name, success=False, output="", error=str(exc))
        except OSError as exc:
            logger.warning("rewrite_file failed: %s", exc)
            return ToolResult(tool_name=name, success=False, output="", error=str(exc))
        except Exception as exc:
            logger.exception("rewrite_file unexpected error")
            return ToolResult(tool_name=name, success=False, output="", error=str(exc))

    def _exec_patch_file(
        self, path: str, start_line: Any, end_line: Any, new_content: str
    ) -> ToolResult:
        """Replace a range of lines in a file with new content.

        Args:
            path: Relative file path.
            start_line: First line number (1-based).
            end_line: Last line number (1-based, inclusive).
            new_content: Replacement text for the specified range.

        Returns:
            :class:`ToolResult` with patch summary or error.

        Raises:
            PathTraversalError: Not raised; surfaced via ``ToolResult``.
        """
        name = "patch_file"
        try:
            if not path.strip():
                return ToolResult(
                    tool_name=name, success=False, output="", error="path is required",
                )
            try:
                s_line = int(start_line)
                e_line = int(end_line)
            except (TypeError, ValueError):
                return ToolResult(
                    tool_name=name, success=False, output="",
                    error="start_line and end_line must be integers",
                )
            if s_line < 1 or e_line < s_line:
                return ToolResult(
                    tool_name=name, success=False, output="",
                    error=f"Invalid line range: {s_line}-{e_line}",
                )
            if is_sensitive_file(path):
                return ToolResult(
                    tool_name=name, success=False, output="",
                    error="Refusing to patch sensitive file path",
                )
            abs_path = self._resolve(path)
            if not os.path.isfile(abs_path):
                return ToolResult(
                    tool_name=name, success=False, output="",
                    error="Not a file or does not exist",
                )
            lines = Path(abs_path).read_text(
                encoding="utf-8", errors="replace",
            ).splitlines(keepends=True)
            if e_line > len(lines):
                return ToolResult(
                    tool_name=name, success=False, output="",
                    error=f"end_line {e_line} exceeds file length ({len(lines)} lines)",
                )
            new_lines = new_content.splitlines(keepends=True)
            if new_content and not new_content.endswith("\n"):
                if new_lines:
                    last = new_lines[-1]
                    if not last.endswith("\n"):
                        new_lines[-1] = last + "\n"
                else:
                    new_lines = [new_content + "\n"]

            patched = lines[: s_line - 1] + new_lines + lines[e_line:]
            Path(abs_path).write_text("".join(patched), encoding="utf-8", newline="")
            removed = e_line - s_line + 1
            added = len(new_lines)
            return ToolResult(
                tool_name=name,
                success=True,
                output=f"Patched lines {s_line}-{e_line}: removed {removed}, added {added} lines",
                error="",
            )
        except PathTraversalError as exc:
            return ToolResult(tool_name=name, success=False, output="", error=str(exc))
        except OSError as exc:
            logger.warning("patch_file failed: %s", exc)
            return ToolResult(tool_name=name, success=False, output="", error=str(exc))
        except Exception as exc:
            logger.exception("patch_file unexpected error")
            return ToolResult(tool_name=name, success=False, output="", error=str(exc))

    def _exec_list_directory(self, path: str) -> ToolResult:
        """List entries in a directory under the worktree.

        Args:
            path: Relative directory path (``'.'`` for root).

        Returns:
            :class:`ToolResult` with newline-separated names.

        Raises:
            PathTraversalError: Not raised; returned as ``ToolResult.error``.
        """
        name = "list_directory"
        try:
            if not path.strip():
                return ToolResult(
                    tool_name=name,
                    success=False,
                    output="",
                    error="path is required",
                )
            abs_path = self._resolve(path)
            if not os.path.isdir(abs_path):
                return ToolResult(
                    tool_name=name,
                    success=False,
                    output="",
                    error="Not a directory or does not exist",
                )
            entries = sorted(os.listdir(abs_path))
            return ToolResult(
                tool_name=name,
                success=True,
                output="\n".join(entries),
                error="",
            )
        except PathTraversalError as exc:
            return ToolResult(tool_name=name, success=False, output="", error=str(exc))
        except OSError as exc:
            logger.warning("list_directory failed: %s", exc)
            return ToolResult(tool_name=name, success=False, output="", error=str(exc))
        except Exception as exc:
            logger.exception("list_directory unexpected error")
            return ToolResult(tool_name=name, success=False, output="", error=str(exc))

    def _append_search_hits(
        self,
        abs_file: str,
        rel: str,
        rx: re.Pattern[str],
        matches: list[str],
    ) -> None:
        """Scan one file and append regex hit lines to *matches*.

        Args:
            abs_file: Absolute path to the file.
            rel: Path relative to worktree for display.
            rx: Compiled regular expression.
            matches: Mutable list of formatted hit strings.

        Returns:
            None

        Raises:
            OSError: If the file size cannot be read or the body cannot be read.
        """
        if os.path.getsize(abs_file) > MAX_FILE_SIZE_BYTES:
            return
        text = Path(abs_file).read_text(encoding="utf-8", errors="replace")
        for line_no, line in enumerate(text.splitlines(), start=1):
            if rx.search(line):
                matches.append(f"{rel}:{line_no}:{line}")
                if len(matches) >= AGENT_SEARCH_MAX_MATCHES:
                    return

    def _walk_regex_matches(self, root: str, rx: re.Pattern[str]) -> str:
        """Walk *root* for text files and format lines matching *rx*.

        Args:
            root: Absolute directory to search recursively.
            rx: Compiled regular expression.

        Returns:
            Newline-separated ``path:line:text`` hits, possibly empty.

        Raises:
            This function does not raise; per-file errors are skipped.
        """
        matches: list[str] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fname in filenames:
                if Path(fname).suffix.lower() in SKIP_EXTENSIONS:
                    continue
                abs_file = os.path.join(dirpath, fname)
                rel = os.path.relpath(abs_file, self._worktree_path)
                try:
                    self._append_search_hits(abs_file, rel, rx, matches)
                except OSError:
                    continue
                if len(matches) >= AGENT_SEARCH_MAX_MATCHES:
                    break
            if len(matches) >= AGENT_SEARCH_MAX_MATCHES:
                break
        out = "\n".join(matches)
        if len(out.encode("utf-8")) > MAX_TOOL_OUTPUT_BYTES:
            return _decode_truncated(out.encode("utf-8"), MAX_TOOL_OUTPUT_BYTES)
        return out

    def _exec_search_code(self, pattern: str, path: Optional[str] = None) -> ToolResult:
        """Regex-search text files under the worktree (or a subdirectory).

        Args:
            pattern: Regular expression string.
            path: Optional relative directory to restrict the walk.

        Returns:
            :class:`ToolResult` with hits or an error message.

        Raises:
            re.error: Caught and returned as a failed ``ToolResult``.
        """
        name = "search_code"
        try:
            if not pattern.strip():
                return ToolResult(
                    tool_name=name,
                    success=False,
                    output="",
                    error="pattern is required",
                )
            try:
                rx = re.compile(pattern)
            except re.error as exc:
                return ToolResult(
                    tool_name=name,
                    success=False,
                    output="",
                    error=f"Invalid regex: {exc}",
                )
            rel_base = "." if path is None or path == "" else path
            root = self._resolve(rel_base)
            if not os.path.isdir(root):
                root = self._worktree_path
            out = self._walk_regex_matches(root, rx)
            return ToolResult(tool_name=name, success=True, output=out, error="")
        except PathTraversalError as exc:
            return ToolResult(tool_name=name, success=False, output="", error=str(exc))
        except Exception as exc:
            logger.exception("search_code unexpected error")
            return ToolResult(tool_name=name, success=False, output="", error=str(exc))

    def _resolve_command_cwd(self, workdir: Optional[str]) -> str:
        """Pick the working directory for ``run_command``.

        Args:
            workdir: Optional path relative to the worktree, or ``None``.

        Returns:
            Absolute directory path for ``subprocess``.

        Raises:
            PathTraversalError: If *workdir* fails ``sanitize_file_path``.
        """
        if workdir is not None and workdir.strip():
            return self._resolve(workdir)
        return self._worktree_path

    def _run_command_inner(
        self, command: str, workdir: Optional[str], name: str
    ) -> ToolResult:
        """Validate and run *command* after resolving *workdir*.

        Args:
            command: Shell command string.
            workdir: Optional relative working directory.
            name: Tool label for the result object.

        Returns:
            A completed :class:`ToolResult` when the process finishes.

        Raises:
            ToolExecutionError: When the command is blocked by policy.
            subprocess.TimeoutExpired: When the timeout elapses.
            OSError: When the subprocess cannot be started.
        """
        if not command.strip():
            return ToolResult(
                tool_name=name,
                success=False,
                output="",
                error="command is required",
            )
        if is_blocked_command(command):
            logger.warning(
                "Blocked command=%r policy=%r",
                command,
                BLOCKED_COMMANDS,
            )
            raise ToolExecutionError("Command is not allowed")
        cwd = self._resolve_command_cwd(workdir)
        code, text = _shell_output(
            command,
            cwd,
            TOOL_TIMEOUT_SECONDS,
            MAX_TOOL_OUTPUT_BYTES,
        )
        ok = code == 0
        err = "" if ok else f"exit code {code}"
        return ToolResult(tool_name=name, success=ok, output=text, error=err)

    def _exec_run_command(self, command: str, workdir: Optional[str] = None) -> ToolResult:
        """Run a shell command with timeout and output limits.

        Args:
            command: Full shell command string.
            workdir: Optional relative working directory within the worktree.

        Returns:
            :class:`ToolResult` with combined stdout/stderr.

        Raises:
            ToolExecutionError: Not raised; blocked commands return a failed result.
        """
        name = "run_command"
        try:
            return self._run_command_inner(command, workdir, name)
        except ToolExecutionError as exc:
            return ToolResult(tool_name=name, success=False, output="", error=str(exc))
        except subprocess.TimeoutExpired:
            logger.warning("run_command timed out after %ss", TOOL_TIMEOUT_SECONDS)
            return ToolResult(
                tool_name=name,
                success=False,
                output="",
                error=f"Command timed out after {TOOL_TIMEOUT_SECONDS}s",
            )
        except OSError as exc:
            logger.warning("run_command failed: %s", exc)
            return ToolResult(tool_name=name, success=False, output="", error=str(exc))
        except Exception as exc:
            logger.exception("run_command unexpected error")
            return ToolResult(tool_name=name, success=False, output="", error=str(exc))

    @staticmethod
    def _extract_keywords(question: str) -> list[str]:
        """Split a natural-language question into search keywords.

        Args:
            question: User or agent question string.

        Returns:
            De-duplicated list of lowercase keyword tokens.
        """
        tokens = re.split(r"[^a-zA-Z0-9_]+", question.lower())
        seen: set[str] = set()
        result: list[str] = []
        for t in tokens:
            if (
                t
                and len(t) >= QUERY_KEYWORD_MIN_LENGTH
                and t not in QUERY_KEYWORD_STOP_WORDS
                and t not in seen
            ):
                seen.add(t)
                result.append(t)
        return result

    def _exec_query_context(self, question: str) -> ToolResult:
        """Query indexed repo context using vector similarity search.

        First attempts semantic vector search on ``repo_code_chunks``,
        then falls back to keyword search on ``repo_file_memories``.
        Augments results with reference graph data and consolidation insights.

        Args:
            question: Natural-language question about the codebase.

        Returns:
            :class:`ToolResult` with matching code snippets, file summaries,
            and insights.
        """
        name = "query_context"

        if not question.strip():
            return ToolResult(
                tool_name=name,
                success=False,
                output="",
                error="question is required",
            )

        if self._repo_id is None:
            logger.warning("query_context called without repo_id — falling back to placeholder")
            return ToolResult(
                tool_name=name,
                success=True,
                output=AGENT_CONTEXT_QUERY_PLACEHOLDER,
                error="",
            )

        try:
            from src.db import repo_code_chunk_db, repo_context_db, repo_memory_db, repo_reference_db

            parts: list[str] = []
            keywords = self._extract_keywords(question)
            seen_paths: set[str] = set()

            vector_hits = self._vector_search_chunks(question)
            if vector_hits:
                parts.append(f"## Semantically relevant code ({len(vector_hits)} chunks)\n")
                for vh in vector_hits[:10]:
                    fp = vh.get("file_path", "?")
                    sym = vh.get("symbol_name", "")
                    sim = vh.get("similarity", 0)
                    content = vh.get("content", "")
                    if len(content) > 2000:
                        content = content[:2000] + "..."
                    label = f"{fp}::{sym}" if sym else fp
                    parts.append(f"### {label} (similarity: {sim:.2f})")
                    parts.append(f"```\n{content}\n```")
                    seen_paths.add(fp)

                    try:
                        refs = repo_reference_db.get_importers(self._repo_id, fp)
                        if refs:
                            importers = [r["source_file"] for r in refs[:5]]
                            parts.append(f"Imported by: {', '.join(importers)}")
                    except Exception:
                        pass
                    parts.append("")

            hits: list[dict[str, Any]] = []
            for kw in keywords[:6]:
                for row in repo_memory_db.search_by_text(self._repo_id, kw):
                    fp = row.get("file_path", "")
                    if fp not in seen_paths:
                        seen_paths.add(fp)
                        hits.append(row)

            if len(hits) < MIN_MEMORIES_FOR_QUERY_MATCH and keywords:
                for row in repo_memory_db.search_by_topics(self._repo_id, keywords[:3]):
                    fp = row.get("file_path", "")
                    if fp not in seen_paths:
                        seen_paths.add(fp)
                        hits.append(row)

            if hits:
                parts.append(f"## Relevant file summaries ({len(hits)} matches)\n")
                for h in hits[:15]:
                    fp = h.get("file_path", "?")
                    summary = h.get("summary", "")
                    purpose = h.get("purpose", "")
                    funcs = h.get("functions_and_classes") or []

                    parts.append(f"### {fp}")
                    if summary:
                        parts.append(f"Summary: {summary}")
                    if purpose:
                        parts.append(f"Purpose: {purpose}")
                    if funcs:
                        func_names = [
                            f.get("name", str(f)) if isinstance(f, dict) else str(f)
                            for f in funcs[:15]
                        ]
                        parts.append(f"Functions/Classes: {', '.join(func_names)}")
                    parts.append("")

            consolidations = repo_context_db.list_consolidations(self._repo_id)
            relevant_insights = []
            for c in consolidations:
                insight_text = (c.get("insight") or "").lower()
                if any(kw in insight_text for kw in keywords[:5]):
                    relevant_insights.append(c)

            if relevant_insights:
                parts.append(f"## Consolidation insights ({len(relevant_insights)} relevant)\n")
                for ci in relevant_insights[:10]:
                    ctype = ci.get("consolidation_type", "")
                    insight = ci.get("insight", "")
                    suggestion = ci.get("actionable_suggestion", "")
                    parts.append(f"[{ctype}] {insight}")
                    if suggestion:
                        parts.append(f"  -> Suggestion: {suggestion}")
                    parts.append("")

            try:
                ctx_row = repo_context_db.get_context(self._repo_id)
                if ctx_row:
                    global_parts = []
                    entry_pts = ctx_row.get("entry_points") or []
                    api_routes = ctx_row.get("api_routes") or []
                    file_map = ctx_row.get("file_responsibility_map") or {}
                    data_flow = ctx_row.get("data_flow") or []

                    if entry_pts:
                        global_parts.append("**Entry points:** " + ", ".join(str(e) for e in entry_pts[:15]))
                    if api_routes:
                        routes_str = ", ".join(str(r) for r in api_routes[:20])
                        global_parts.append(f"**API routes:** {routes_str}")
                    if file_map:
                        relevant_files = {fp for fp in seen_paths if fp in file_map}
                        if relevant_files:
                            for fp in list(relevant_files)[:10]:
                                global_parts.append(f"  {fp}: {file_map[fp]}")
                    if data_flow:
                        global_parts.append("**Data flow:** " + "; ".join(str(d) for d in data_flow[:10]))

                    if global_parts:
                        parts.append("\n## Global project context\n")
                        parts.extend(global_parts)
                        parts.append("")
            except Exception:
                pass

            if not parts:
                parts.append("No indexed context matched the query.\n")

            output = "\n".join(parts)
            if len(output.encode("utf-8")) > MAX_TOOL_OUTPUT_BYTES:
                output = _decode_truncated(output.encode("utf-8"), MAX_TOOL_OUTPUT_BYTES)

            return ToolResult(tool_name=name, success=True, output=output, error="")

        except Exception as exc:
            logger.exception("query_context failed")
            return ToolResult(tool_name=name, success=False, output="", error=str(exc))

    def _vector_search_chunks(self, question: str) -> list[dict[str, Any]]:
        """Embed the question and search code chunks by vector similarity.

        Args:
            question: Natural-language query.

        Returns:
            List of matching chunk dicts, or empty list on failure.
        """
        try:
            from src.db import repo_code_chunk_db
            from src.embedder import get_embedder

            embedder = get_embedder()
            query_vec = embedder.embed(question, use_cache=True).tolist()
            return repo_code_chunk_db.search_similar(
                self._repo_id, query_vec, limit=15, threshold=0.4,
            )
        except Exception as exc:
            logger.debug("Vector search unavailable: %s", exc)
            return []

    def _exec_git_commit(self, message: str) -> ToolResult:
        """Run ``git add -A`` and ``git commit`` in the worktree.

        Args:
            message: Commit message string.

        Returns:
            :class:`ToolResult` with command output or errors.

        Raises:
            subprocess.CalledProcessError: Not raised; non-zero exit is returned.
        """
        name = "git_commit"
        try:
            if not message.strip():
                return ToolResult(
                    tool_name=name,
                    success=False,
                    output="",
                    error="message is required",
                )
            base = self._worktree_path
            _git_add_all(base, TOOL_TIMEOUT_SECONDS)
            proc = subprocess.run(
                ["git", "commit", "-m", message],
                cwd=base,
                capture_output=True,
                timeout=TOOL_TIMEOUT_SECONDS,
                text=True,
            )
            out = (proc.stdout or "") + (proc.stderr or "")
            if len(out.encode("utf-8")) > MAX_TOOL_OUTPUT_BYTES:
                out = _decode_truncated(out.encode("utf-8"), MAX_TOOL_OUTPUT_BYTES)
            ok = proc.returncode == 0
            err = "" if ok else (proc.stderr or "git commit failed")
            return ToolResult(tool_name=name, success=ok, output=out, error=err)
        except subprocess.CalledProcessError as exc:
            err_txt = (exc.stderr or str(exc)) if hasattr(exc, "stderr") else str(exc)
            logger.warning("git_commit add failed: %s", err_txt)
            return ToolResult(tool_name=name, success=False, output="", error=err_txt)
        except OSError as exc:
            logger.warning("git_commit failed: %s", exc)
            return ToolResult(tool_name=name, success=False, output="", error=str(exc))
        except Exception as exc:
            logger.exception("git_commit unexpected error")
            return ToolResult(tool_name=name, success=False, output="", error=str(exc))

    def _exec_ask_user(self, question: str) -> ToolResult:
        """Return the question as a tool result for the agent loop to handle.

        The actual pausing logic (setting ``awaiting_input`` status and breaking
        the loop) is handled by :class:`CodingAgent._handle_tool_calls`.

        Args:
            question: The clarification question for the user.

        Returns:
            A successful :class:`ToolResult` with the question in ``output``.

        Raises:
            This function does not raise.
        """
        if not question.strip():
            return ToolResult(
                tool_name="ask_user",
                success=False,
                output="",
                error="question is required",
            )
        return ToolResult(
            tool_name="ask_user",
            success=True,
            output=question,
            error="",
        )

    def lint_file(self, relative_path: str) -> Optional[str]:
        """Run basic syntax checking on a file after an edit.

        Currently supports Python (``py_compile``) and JavaScript
        (``node --check``).  Returns error text when the check fails,
        or ``None`` if everything is clean (or the file type is unsupported).

        Args:
            relative_path: Path relative to the worktree root.

        Returns:
            Error output string, or ``None`` if no issues detected.

        Raises:
            This function does not raise; errors are swallowed.
        """
        try:
            abs_path = self._resolve(relative_path)
            ext = Path(abs_path).suffix.lower()
            if ext == ".py":
                proc = subprocess.run(
                    ["python", "-m", "py_compile", abs_path],
                    capture_output=True,
                    text=True,
                    timeout=LINT_CHECK_TIMEOUT_SECONDS,
                )
                if proc.returncode != 0:
                    return (proc.stderr or proc.stdout or "").strip()
            elif ext == ".js":
                proc = subprocess.run(
                    ["node", "--check", abs_path],
                    capture_output=True,
                    text=True,
                    timeout=LINT_CHECK_TIMEOUT_SECONDS,
                )
                if proc.returncode != 0:
                    return (proc.stderr or proc.stdout or "").strip()
            return None
        except Exception:
            return None

    def _exec_done(self, summary: str) -> ToolResult:
        """Mark the agent turn sequence complete with a summary string.

        Args:
            summary: Human-readable recap of work performed.

        Returns:
            A successful :class:`ToolResult` carrying *summary* in ``output``.

        Raises:
            RuntimeError: Not raised.
        """
        return ToolResult(
            tool_name="done",
            success=True,
            output=summary,
            error="",
        )
