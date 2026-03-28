"""
OpenAI-style function-calling schemas for the DocuRag coding agent.

Defines :data:`AGENT_TOOLS`: a list of dicts (``name``, ``description``,
``parameters``) passed to LLM tool APIs so the model can invoke repository
operations in a structured way.
"""

from __future__ import annotations

AGENT_TOOLS: list[dict[str, object]] = [
    {
        "name": "read_file",
        "description": "Read the contents of a file from the repository",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative file path from repo root",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Create a new file or overwrite an existing file",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative file path"},
                "content": {
                    "type": "string",
                    "description": "Complete file content",
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": (
            "Replace a specific short text snippet in a file. Best for single-line "
            "or very small changes (1-3 lines). Uses fuzzy whitespace matching. "
            "For larger edits prefer rewrite_file or patch_file."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative file path"},
                "old_text": {
                    "type": "string",
                    "description": "Text to find and replace (whitespace is matched flexibly)",
                },
                "new_text": {"type": "string", "description": "Replacement text"},
            },
            "required": ["path", "old_text", "new_text"],
        },
    },
    {
        "name": "rewrite_file",
        "description": (
            "Rewrite an existing file with entirely new content. The MOST RELIABLE "
            "editing tool — use this when edit_file fails or for changes spanning "
            "many lines. Output the COMPLETE file content. The file must already exist."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative file path (must exist)"},
                "content": {
                    "type": "string",
                    "description": "The complete new content for the entire file",
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_directory",
        "description": "List files and subdirectories in a directory",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative directory path, use '.' for root",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_code",
        "description": "Search for a pattern across the repository (regex supported)",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Search pattern (regex)",
                },
                "path": {
                    "type": "string",
                    "description": "Optional: limit search to this directory",
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "run_command",
        "description": "Execute a shell command in the repository",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to execute",
                },
                "workdir": {
                    "type": "string",
                    "description": "Optional: working directory relative to repo root",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "query_context",
        "description": (
            "Ask the repository knowledge base a question about the project's "
            "architecture, patterns, or code"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "Question about the repository",
                },
            },
            "required": ["question"],
        },
    },
    {
        "name": "patch_file",
        "description": (
            "Replace a range of lines in a file with new content using line "
            "numbers from read_file output. Good for targeted edits in large "
            "files where rewriting the whole file is too expensive."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative file path"},
                "start_line": {
                    "type": "integer",
                    "description": "First line to replace (1-based, from read_file output)",
                },
                "end_line": {
                    "type": "integer",
                    "description": "Last line to replace (1-based, inclusive)",
                },
                "new_content": {
                    "type": "string",
                    "description": "Replacement text for the specified line range",
                },
            },
            "required": ["path", "start_line", "end_line", "new_content"],
        },
    },
    {
        "name": "ask_user",
        "description": (
            "Pause execution and ask the user a clarification question. "
            "Use when the task is ambiguous, you need to choose between approaches, "
            "or you want confirmation before changing sensitive files. "
            "The agent loop will pause until the user responds."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "Clear, specific question for the user",
                },
            },
            "required": ["question"],
        },
    },
    {
        "name": "done",
        "description": "Signal that the task is complete and provide a summary",
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Summary of all changes made and why",
                },
            },
            "required": ["summary"],
        },
    },
]
