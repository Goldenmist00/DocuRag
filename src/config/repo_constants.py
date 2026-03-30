"""
repo_constants.py
=================
Centralized constants for the repo analyzer feature.

All configurable values live here so service code contains
no magic numbers. Import individual constants where needed:

    from src.config.repo_constants import MAX_FILE_SIZE_BYTES
"""

# ---------------------------------------------------------------------------
# File filtering
# ---------------------------------------------------------------------------

SKIP_DIRS: frozenset = frozenset({
    ".git", "node_modules", "__pycache__", ".next", ".venv", "venv",
    "dist", "build", ".cache", "coverage", ".tox", "vendor",
    "target", "bin", "obj", ".idea", ".vscode",
    "env", ".env", "Lib", "lib", "site-packages", "dist-packages",
    ".eggs", "__pypackages__", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", "htmlcov", ".nox", ".pipdeptree",
    "bower_components", "jspm_packages", ".yarn", ".pnp",
    "_pytest", ".tox",
})
"""Directories to skip when walking a repository file tree (os.walk fallback)."""

SKIP_EXTENSIONS: frozenset = frozenset({
    ".pyc", ".pyo", ".so", ".dll", ".exe", ".bin", ".dat",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
    ".mp3", ".mp4", ".wav", ".zip", ".tar", ".gz", ".lock",
    ".woff", ".woff2", ".ttf", ".eot", ".map",
})
"""File extensions to skip during repository indexing."""

SENSITIVE_FILE_PATTERNS: frozenset = frozenset({
    ".env", "credentials", ".pem", ".key", ".secret",
})
"""Substrings that mark a filename as sensitive (block agent writes)."""

# ---------------------------------------------------------------------------
# Indexing limits
# ---------------------------------------------------------------------------

MAX_FILE_SIZE_BYTES: int = 100_000
"""Files larger than this are skipped during ingestion (100 KB)."""

MAX_CONCURRENT_INGEST_WORKERS: int = 6
"""ThreadPoolExecutor worker count for parallel file ingestion."""

MAX_CONCURRENT_SESSIONS: int = 3
"""Maximum active agent worktree sessions per repository."""

LLM_SEMAPHORE_LIMIT: int = 5
"""Global semaphore permits for concurrent LLM API calls."""

# ---------------------------------------------------------------------------
# LLM file ingest (non-streaming completion)
# ---------------------------------------------------------------------------

INGEST_COMPLETION_MAX_TOKENS: int = 4096
"""Max tokens for per-file ingest analysis completion."""

INGEST_COMPLETION_TEMPERATURE: float = 0.2
"""Sampling temperature for ingest analysis."""

INGEST_COMPLETION_TOP_P: float = 0.9
"""Top-p nucleus sampling for ingest analysis."""

INGEST_HTTP_TIMEOUT_SECONDS: int = 120
"""HTTP timeout for non-streaming ingest LLM requests."""

INGEST_LLM_MAX_RETRIES: int = 5
"""Retry attempts for ingest LLM HTTP failures and rate limits."""

INGEST_LLM_INITIAL_BACKOFF_SECONDS: float = 1.5
"""Base delay before exponential backoff for ingest LLM retries."""

INGEST_LLM_RETRY_JITTER_WIDE: float = 1.5
"""Upper bound (seconds) for uniform jitter after rate-limit responses."""

INGEST_LLM_RETRY_JITTER_NARROW: float = 1.0
"""Upper bound (seconds) for uniform jitter on generic ingest LLM retries."""

INGEST_PARSE_FALLBACK_SNIPPET_CHARS: int = 500
"""Max characters kept from raw LLM output when JSON parsing fails."""

AST_ONLY_EXTENSIONS: frozenset = frozenset({
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".md", ".txt", ".rst", ".csv", ".html", ".css", ".scss",
    ".sql", ".sh", ".dockerfile", ".xml", ".svg", ".lock",
})
"""Extensions where AST or basic parsing is sufficient — skip LLM analysis."""

AST_ONLY_MAX_FILE_SIZE: int = 500
"""Files smaller than this many bytes get AST-only treatment (too small for LLM)."""

NVIDIA_API_KEY_SENTINEL: str = "your_nvidia_api_key_here"
"""Placeholder value treated as a missing NVIDIA API key."""

# ---------------------------------------------------------------------------
# Repo indexing lifecycle (``repos.indexing_status``)
# ---------------------------------------------------------------------------

REPO_INDEXING_STATUS_PENDING: str = "pending"
"""Repository registered; clone or indexing not finished."""

REPO_INDEXING_STATUS_INDEXING: str = "indexing"
"""Repository is actively ingesting file memories."""

REPO_INDEXING_STATUS_CONSOLIDATING: str = "consolidating"
"""Repository memories are being merged into repo-wide context."""

REPO_INDEXING_STATUS_READY: str = "ready"
"""Repository is indexed and consolidated; agent sessions allowed."""

REPO_INDEXING_STATUS_FAILED: str = "failed"
"""Last indexing pass failed."""

SESSION_STATUS_QUEUED: str = "queued"
"""Agent session waiting to start."""

SESSION_STATUS_RUNNING: str = "running"
"""Agent session executing."""

SESSION_STATUS_COMPLETED: str = "completed"
"""Agent session finished successfully."""

SESSION_STATUS_FAILED: str = "failed"
"""Agent session ended with an error."""

SESSION_STATUS_CANCELLED: str = "cancelled"
"""Agent session was cancelled by the user."""

SESSION_STATUS_AWAITING_INPUT: str = "awaiting_input"
"""Agent session is paused waiting for user clarification."""

# ---------------------------------------------------------------------------
# Consolidation
# ---------------------------------------------------------------------------

CONSOLIDATION_BATCH_SIZE: int = 25
"""Number of file memories per LLM consolidation call."""

CONSOLIDATION_TYPES: tuple = (
    "architecture",
    "feature",
    "security",
    "debt",
    "pattern",
    "dependency",
    "test_coverage",
)
"""Allowed ``consolidation_type`` values for cross-file consolidation insights."""

QUERY_KEYWORD_STOP_WORDS: frozenset = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "must", "shall", "can", "need", "dare",
    "ought", "used", "to", "of", "in", "for", "on", "with", "at", "by",
    "from", "as", "into", "through", "during", "before", "after", "above",
    "below", "between", "under", "again", "further", "then", "once", "here",
    "there", "when", "where", "why", "how", "all", "each", "few", "more",
    "most", "other", "some", "such", "no", "nor", "not", "only", "own",
    "same", "so", "than", "too", "very", "just", "and", "but", "if", "or",
    "because", "until", "while", "about", "against", "between", "into",
    "through", "what", "which", "who", "whom", "this", "that", "these",
    "those", "am", "i", "me", "my", "we", "our", "you", "your", "it",
    "its", "they", "their", "them", "he", "him", "his", "she", "her",
})
"""Lowercase tokens dropped when extracting query keywords from user questions."""

MIN_MEMORIES_FOR_QUERY_MATCH: int = 3
"""Minimum relevant memories before falling back to broader search."""

QUERY_KEYWORD_MIN_LENGTH: int = 2
"""Minimum token length (characters) to keep as a query keyword."""

# ---------------------------------------------------------------------------
# Coding agent
# ---------------------------------------------------------------------------

MAX_AGENT_TURNS: int = 30
"""Maximum LLM tool-calling turns before forcing session completion."""

TOOL_TIMEOUT_SECONDS: int = 30
"""Subprocess timeout for agent shell commands."""

MAX_TOOL_OUTPUT_BYTES: int = 10_240
"""Truncate tool stdout/stderr beyond this limit (10 KB)."""

CONTEXT_COMPACTION_THRESHOLD: float = 0.8
"""Fraction of context window that triggers conversation compaction."""

AGENT_CONVERSATION_CHAR_BUDGET: int = 96_000
"""Rough UTF-8 character budget for the agent conversation before compaction."""

AGENT_COMPACTION_TAIL_MESSAGES: int = 24
"""Number of recent messages to keep after compaction (plus system)."""

AGENT_CHAT_COMPLETION_429_MAX_RETRIES: int = 3
"""Maximum retry attempts after HTTP 429 on agent chat completion."""

AGENT_CHAT_COMPLETION_INITIAL_BACKOFF_SECONDS: float = 1.0
"""Base delay for exponential backoff after HTTP 429 on agent chat completion."""

AGENT_COMPLETION_MAX_TOKENS: int = 8192
"""Max tokens for agent chat completions (higher than ingest for richer output)."""

LINT_CHECK_TIMEOUT_SECONDS: int = 10
"""Subprocess timeout for post-edit syntax checking."""

AGENT_SESSION_STATUS_RUNNING: str = "running"
"""Agent session status while the coding agent loop is active."""

AGENT_SESSION_STEP_CHAT: str = "llm_turn"
"""``current_step`` value while waiting on or processing an LLM turn."""

# ---------------------------------------------------------------------------
# Command safety
# ---------------------------------------------------------------------------

BLOCKED_COMMANDS: frozenset = frozenset({
    "rm -rf /", "format", "mkfs", "dd", "shutdown", "reboot",
})
"""Shell commands the tool executor must never run."""

AGENT_CONTEXT_QUERY_PLACEHOLDER: str = "Context query not yet connected"
"""Response body when the repository context / RAG hook is not wired up."""

AGENT_SEARCH_MAX_MATCHES: int = 200
"""Maximum number of search hits returned by the agent ``search_code`` tool."""

# ---------------------------------------------------------------------------
# Language detection (extension -> human-readable name)
# ---------------------------------------------------------------------------

EXTENSION_TO_LANGUAGE: dict = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".jsx": "JavaScript",
    ".java": "Java",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".cpp": "C++",
    ".c": "C",
    ".swift": "Swift",
    ".kt": "Kotlin",
    ".scala": "Scala",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".json": "JSON",
    ".md": "Markdown",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".sql": "SQL",
    ".sh": "Shell",
    ".dockerfile": "Dockerfile",
}
"""Maps file extensions to their language name for file memories."""

# ---------------------------------------------------------------------------
# Repo storage defaults
# ---------------------------------------------------------------------------

DEFAULT_REPOS_DIR: str = "repos"
"""Root directory under the project where cloned repos are stored."""

DEFAULT_GIT_BRANCH: str = "main"
"""Fallback default branch when ``repos.default_branch`` is unset."""

WORKTREES_DIR_SUFFIX: str = "-worktrees"
"""Suffix appended to repo dir name to form the worktree parent directory."""

WORKTREE_STATUS_MERGED: str = "merged"
"""Worktree branch has been merged into the main clone."""

# ---------------------------------------------------------------------------
# Orchestrator (user-visible strings)
# ---------------------------------------------------------------------------

MSG_ORCHESTRATOR_INVALID_GITHUB_URL: str = "Invalid GitHub URL"
"""Returned when ``validate_github_url`` fails during registration."""

MSG_ORCHESTRATOR_REPO_ALREADY_REGISTERED_TEMPLATE: str = (
    "Repository already registered: {remote_url}"
)
"""Detail for :class:`RepoAlreadyExistsError` (format with ``remote_url``)."""

MSG_ORCHESTRATOR_REPO_NOT_READY: str = (
    "Repository is not ready for agent sessions"
)
"""Raised when ``indexing_status`` is not ``ready`` for a new session."""

MSG_ORCHESTRATOR_SESSION_LIMIT_TEMPLATE: str = (
    "Maximum concurrent sessions ({max_sessions}) reached"
)
"""Detail for :class:`SessionLimitError`; format with ``max_sessions``."""

MSG_ORCHESTRATOR_REINDEX_STARTED: str = "Reindex started"
"""Acknowledgement body when a background reindex is scheduled."""

MSG_ORCHESTRATOR_CONSOLIDATION_STARTED: str = "Consolidation started"
"""Acknowledgement when background consolidation is scheduled."""

MSG_ORCHESTRATOR_AGENT_RESTARTED: str = "Agent restarted"
"""Acknowledgement when a session agent loop is re-scheduled."""

MSG_ORCHESTRATOR_SESSION_NO_WORKTREE: str = "Session has no worktree"
"""Session row is missing ``worktree_id``."""

MSG_ORCHESTRATOR_WORKTREE_NOT_FOUND: str = "Worktree not found for session"
"""Worktree row missing for a session."""

MSG_ORCHESTRATOR_MERGE_CONFLICT_TEMPLATE: str = "Merge conflicts: {conflicts}"
"""Detail for :class:`MergeConflictError`; format with ``conflicts``."""

# ---------------------------------------------------------------------------
# Database: repo analyzer tables & DDL helpers (no magic strings in db layer)
# ---------------------------------------------------------------------------

TABLE_REPO_FILE_MEMORIES: str = "repo_file_memories"
"""Per-file memory rows for a repository."""

TABLE_REPO_CONTEXT: str = "repo_context"
"""Aggregated repository context (one row per repo)."""

TABLE_REPO_CONSOLIDATIONS: str = "repo_consolidations"
"""Consolidation insights linked to a repository."""

CONSOLIDATION_STATUS_PENDING: str = "pending"
"""File memory not yet rolled into repo-wide context."""

CONSOLIDATION_STATUS_CONSOLIDATED: str = "consolidated"
"""File memory included in a consolidation pass."""

CONSOLIDATION_SEVERITY_DEFAULT: str = "info"
"""Default severity for a consolidation record."""

CONSOLIDATION_SCOPE_DEFAULT: str = "project-wide"
"""Default scope for a consolidation record."""

CONTEXT_ASSEMBLY_USER_LEADIN: str = (
    "Consolidation insights (one JSON object per line):\n"
)
"""User-message prefix when assembling global ``repo_context`` from insights."""

IDX_REPO_FILE_MEMORIES_TOPICS_GIN: str = "idx_repo_file_memories_topics_gin"
"""GIN index name for JSONB ``topics``."""

IDX_REPO_FILE_MEMORIES_ENTITIES_GIN: str = "idx_repo_file_memories_entities_gin"
"""GIN index name for JSONB ``entities``."""

IDX_REPO_FILE_MEMORIES_REPO_CONSOLIDATION: str = "idx_repo_file_memories_repo_consolidation"
"""B-tree index on ``(repo_id, consolidation_status)``."""

IDX_REPO_CONSOLIDATIONS_REPO_ID: str = "idx_repo_consolidations_repo_id"
"""Index on ``repo_consolidations(repo_id)``."""

IDX_REPO_CONSOLIDATIONS_REPO_TYPE: str = "idx_repo_consolidations_repo_type"
"""Index on ``repo_consolidations(repo_id, consolidation_type)``."""

SQL_JSONB_EMPTY_OBJECT: str = "'{}'::jsonb"
"""SQL literal for an empty JSON object default in DDL."""

SQL_JSONB_EMPTY_ARRAY: str = "'[]'::jsonb"
"""SQL literal for an empty JSON array default in DDL."""

REPO_CONTEXT_INITIAL_VERSION: int = 1
"""Default ``version`` for a new ``repo_context`` row."""
