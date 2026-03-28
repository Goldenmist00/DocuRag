const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ─── Shared types ───

export interface Source {
  citation: string;
  section_title: string;
  page: number;
  score: number;
  source_name: string;
}

export interface AnswerGrade {
  faithfulness: number;
  completeness: number;
  citation_accuracy: number;
  overall: number;
  passed: boolean;
  issues: string[];
}

export interface QueryResponse {
  question: string;
  answer: string;
  references: { sections: string[]; pages: number[] };
  chunks_used: number;
  latency_ms: number;
  sources: Source[];
  grade?: AnswerGrade | null;
}

export interface Notebook {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  source_count?: number;
}

export interface SourceRecord {
  id: string;
  notebook_id: string;
  name: string;
  source_type: string;
  status: string;
  error_message: string | null;
  chunk_count: number;
  created_at: string;
  updated_at: string;
}

// ─── Notebook CRUD ───

export async function createNotebook(title?: string): Promise<Notebook> {
  const res = await fetch(`${API_BASE}/notebooks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: title || undefined }),
  });
  if (!res.ok) throw new Error(`Create notebook failed: ${res.status}`);
  return res.json();
}

export async function listNotebooks(): Promise<Notebook[]> {
  const res = await fetch(`${API_BASE}/notebooks`);
  if (!res.ok) throw new Error(`List notebooks failed: ${res.status}`);
  return res.json();
}

export async function getNotebook(id: string): Promise<Notebook> {
  const res = await fetch(`${API_BASE}/notebooks/${id}`);
  if (!res.ok) throw new Error(`Get notebook failed: ${res.status}`);
  return res.json();
}

export async function updateNotebookTitle(
  id: string,
  title: string
): Promise<Notebook> {
  const res = await fetch(`${API_BASE}/notebooks/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  if (!res.ok) throw new Error(`Update notebook failed: ${res.status}`);
  return res.json();
}

export async function deleteNotebook(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/notebooks/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`Delete notebook failed: ${res.status}`);
}

// ─── Notebook conversation history ───

export interface NotebookHistoryEntry {
  role: "user" | "ai";
  content: string;
}

export interface NotebookExportContext {
  notebook_id: string;
  title: string;
  sources: { name: string; source_type: string }[];
  conversation_history: NotebookHistoryEntry[];
}

export async function getNotebookHistory(
  notebookId: string,
): Promise<NotebookHistoryEntry[]> {
  const res = await fetch(`${API_BASE}/notebooks/${notebookId}/history`);
  if (!res.ok) throw new Error(`Get history failed: ${res.status}`);
  return res.json();
}

export async function exportNotebookContext(
  notebookId: string,
): Promise<NotebookExportContext> {
  const res = await fetch(`${API_BASE}/notebooks/${notebookId}/export-context`);
  if (!res.ok) throw new Error(`Export context failed: ${res.status}`);
  return res.json();
}

// ─── Source management ───

export async function uploadSource(
  notebookId: string,
  file: File
): Promise<SourceRecord> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(
    `${API_BASE}/notebooks/${notebookId}/sources/upload`,
    { method: "POST", body: form }
  );
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Upload failed: ${detail}`);
  }
  return res.json();
}

/**
 * Upload a file source with real-time upload progress via XMLHttpRequest.
 * @param notebookId - Parent notebook UUID
 * @param file - File to upload
 * @param onProgress - Callback receiving upload percentage (0-100)
 * @returns Created source record from server
 */
export function uploadSourceWithProgress(
  notebookId: string,
  file: File,
  onProgress?: (percent: number) => void
): Promise<SourceRecord> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const form = new FormData();
    form.append("file", file);

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    };

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText));
        } catch {
          reject(new Error("Invalid response from server"));
        }
      } else {
        reject(new Error(`Upload failed: ${xhr.status}`));
      }
    };

    xhr.onerror = () => reject(new Error("Network error during upload"));

    xhr.open(
      "POST",
      `${API_BASE}/notebooks/${notebookId}/sources/upload`
    );
    xhr.send(form);
  });
}

export async function addTextSource(
  notebookId: string,
  name: string,
  text: string
): Promise<SourceRecord> {
  const res = await fetch(
    `${API_BASE}/notebooks/${notebookId}/sources/text`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, text }),
    }
  );
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Add text source failed: ${detail}`);
  }
  return res.json();
}

export async function listSources(
  notebookId: string
): Promise<SourceRecord[]> {
  const res = await fetch(
    `${API_BASE}/notebooks/${notebookId}/sources`
  );
  if (!res.ok) throw new Error(`List sources failed: ${res.status}`);
  return res.json();
}

export async function deleteSource(
  notebookId: string,
  sourceId: string
): Promise<void> {
  const res = await fetch(
    `${API_BASE}/notebooks/${notebookId}/sources/${sourceId}`,
    { method: "DELETE" }
  );
  if (!res.ok) throw new Error(`Delete source failed: ${res.status}`);
}

// ─── Scoped Q&A ───

export async function askQuestion(
  question: string,
  top_k = 5,
  notebookId?: string
): Promise<QueryResponse> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 120000);

  const url = notebookId
    ? `${API_BASE}/notebooks/${notebookId}/query`
    : `${API_BASE}/query`;

  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, top_k }),
      signal: controller.signal,
    });
    if (!res.ok) {
      const detail = await res.text();
      throw new Error(`API error ${res.status}: ${detail}`);
    }
    return res.json();
  } finally {
    clearTimeout(timeout);
  }
}

// ─── Batch Q&A from file ───

export interface BatchQueryResult {
  question: string;
  answer: string | null;
  error: string | null;
  sources: Source[];
  grade: AnswerGrade | null;
  latency_ms: number;
}

export interface BatchQueryResponse {
  results: BatchQueryResult[];
  total_questions: number;
  answered: number;
  failed: number;
  total_latency_ms: number;
}

/**
 * Upload a JSON or PDF file containing questions and get answers for each.
 * @param notebookId - Parent notebook UUID
 * @param file - JSON or PDF file with questions
 * @param topK - Number of chunks per question (default 5)
 * @returns Batch response with individual question results
 */
export async function batchQueryFromFile(
  notebookId: string,
  file: File,
  topK = 5
): Promise<BatchQueryResponse> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 600_000);

  const form = new FormData();
  form.append("file", file);

  try {
    const res = await fetch(
      `${API_BASE}/notebooks/${notebookId}/batch-query?top_k=${topK}`,
      { method: "POST", body: form, signal: controller.signal }
    );
    if (!res.ok) {
      const detail = await res.text();
      throw new Error(`Batch query failed: ${detail}`);
    }
    return res.json();
  } finally {
    clearTimeout(timeout);
  }
}

// ─── Health / Stats (legacy) ───

export async function getHealth() {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) throw new Error("Health check failed");
  return res.json();
}

export async function getStats() {
  const res = await fetch(`${API_BASE}/stats`);
  if (!res.ok) throw new Error("Stats fetch failed");
  return res.json();
}

// ─── Studio: Flashcards ───

export interface Flashcard {
  term: string;
  definition: string;
  question: string;
  answer: string;
}

export async function generateFlashcards(
  text: string,
  count = 10
): Promise<Flashcard[]> {
  const res = await fetch(`${API_BASE}/flashcards`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, count }),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Flashcard generation failed: ${detail}`);
  }
  const data = await res.json();
  return data.flashcards;
}

// ─── Studio: Summary ───

export async function generateSummary(
  text: string,
  level: "short" | "medium" | "detailed" = "medium"
): Promise<{ summary: string; level: string }> {
  const res = await fetch(`${API_BASE}/summary`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, level }),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Summary generation failed: ${detail}`);
  }
  return res.json();
}

// ─── Studio: Mind Map ───

export interface MindMapBranch {
  label: string;
  children: string[];
}

export interface MindMapData {
  root: string;
  branches: MindMapBranch[];
}

export async function generateMindMap(text: string): Promise<MindMapData> {
  const res = await fetch(`${API_BASE}/mindmap`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Mind map generation failed: ${detail}`);
  }
  return res.json();
}

// ─── Studio: Quiz ───

export interface QuizQuestion {
  q: string;
  options: string[];
  answer: number;
}

// ─── Podcast ───

export interface PodcastRecord {
  id: string;
  notebook_id: string;
  status: string;
  transcript: string | null;
  audio_path: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * Trigger podcast generation for a notebook.
 * @param notebookId - Parent notebook UUID
 * @returns Created podcast record (status will be "pending")
 */
export async function generatePodcast(
  notebookId: string
): Promise<PodcastRecord> {
  const res = await fetch(
    `${API_BASE}/notebooks/${notebookId}/podcast`,
    { method: "POST" }
  );
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Podcast generation failed: ${detail}`);
  }
  return res.json();
}

/**
 * Get the current podcast status for a notebook.
 * @param notebookId - Parent notebook UUID
 * @returns Podcast record or null if none exists
 */
export async function getPodcast(
  notebookId: string
): Promise<PodcastRecord | null> {
  const res = await fetch(
    `${API_BASE}/notebooks/${notebookId}/podcast`
  );
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Get podcast failed: ${res.status}`);
  return res.json();
}

/**
 * Get the audio URL for a notebook's podcast.
 * @param notebookId - Parent notebook UUID
 * @returns Full URL to the podcast MP3 audio
 */
export function getPodcastAudioUrl(notebookId: string): string {
  return `${API_BASE}/notebooks/${notebookId}/podcast/audio`;
}

/**
 * Delete the podcast for a notebook.
 * @param notebookId - Parent notebook UUID
 */
export async function deletePodcast(notebookId: string): Promise<void> {
  const res = await fetch(
    `${API_BASE}/notebooks/${notebookId}/podcast`,
    { method: "DELETE" }
  );
  if (!res.ok) throw new Error(`Delete podcast failed: ${res.status}`);
}

// ─── Studio: Quiz ───

export async function generateQuiz(
  text: string,
  count = 10,
  difficulty: "easy" | "medium" | "hard" | "mixed" = "mixed"
): Promise<QuizQuestion[]> {
  const res = await fetch(`${API_BASE}/quiz`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, count, difficulty }),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Quiz generation failed: ${detail}`);
  }
  const data = await res.json();
  return data.questions;
}

// ─── Repo Analyzer ───

const WS_BASE = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace("http", "ws");

export interface Repo {
  id: string;
  name: string;
  remote_url: string;
  indexing_status: string;
  indexing_phase: string;
  indexing_progress: number;
  indexing_detail: string;
  total_files: number;
  indexed_files: number;
  last_indexed_at: string | null;
}

export interface RepoContext {
  architecture: Record<string, unknown>;
  tech_stack: Record<string, unknown>;
  features: unknown[];
  api_surface: unknown[];
  future_scope: unknown[];
  security_findings: unknown[];
  tech_debt: unknown[];
  test_coverage: Record<string, unknown>;
  dependency_graph: Record<string, unknown>;
  key_files: unknown[];
}

export interface ConversationMessage {
  role: "system" | "user" | "assistant" | "tool";
  content?: string;
  tool_calls?: unknown[];
}

export interface AgentSession {
  id: string;
  status: string;
  task_description: string;
  current_step: string | null;
  agent_log: Record<string, unknown>[];
  plan: Record<string, unknown>[];
  conversation_history: ConversationMessage[];
  result_summary: string | null;
  error_message: string | null;
  created_at: string;
}

export interface SessionDiff {
  session_id: string;
  base_branch: string;
  stats: { files_changed: number; insertions: number; deletions: number };
  raw_diff: string;
  files: { path: string; status: string; diff: string; insertions?: number; deletions?: number }[];
  files_changed?: number;
  insertions?: number;
  deletions?: number;
  agent_summary?: string;
  diff_text?: string;
}

export interface MergeResult {
  merged: boolean;
  commit_hash: string | null;
  conflicts: string[];
}

export interface RepoQueryResult {
  answer: string;
  cited_files: string[];
  relevant_memories: Record<string, unknown>[];
}

export async function createRepo(remoteUrl: string, authToken?: string): Promise<Repo> {
  const res = await fetch(`${API_BASE}/repos`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ remote_url: remoteUrl, auth_token: authToken }),
  });
  if (!res.ok) throw new Error((await res.json()).detail || "Create repo failed");
  return res.json();
}

export async function listRepos(): Promise<Repo[]> {
  const res = await fetch(`${API_BASE}/repos`);
  if (!res.ok) throw new Error("List repos failed");
  return res.json();
}

export async function getRepo(repoId: string): Promise<Repo> {
  const res = await fetch(`${API_BASE}/repos/${repoId}`);
  if (!res.ok) throw new Error("Get repo failed");
  return res.json();
}

export async function deleteRepo(repoId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/repos/${repoId}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Delete repo failed");
}

export async function reindexRepo(repoId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/repos/${repoId}/reindex`, { method: "POST" });
  if (!res.ok) throw new Error("Reindex failed");
}

/**
 * Re-run the consolidation agent to refresh the global context for a repo.
 * Useful when indexing succeeded but consolidation failed.
 * @param repoId - UUID of the repo
 */
export async function refreshRepoContext(repoId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/repos/${repoId}/context/refresh`, { method: "POST" });
  if (!res.ok) throw new Error("Context refresh failed");
}

export async function getRepoContext(repoId: string): Promise<RepoContext> {
  const res = await fetch(`${API_BASE}/repos/${repoId}/context`);
  if (!res.ok) throw new Error("Get context failed");
  return res.json();
}

export interface RepoFile {
  path: string;
  language: string | null;
  summary: string | null;
  importance_score: number | null;
}

export async function listRepoFiles(repoId: string): Promise<RepoFile[]> {
  const res = await fetch(`${API_BASE}/repos/${repoId}/files`);
  if (!res.ok) return [];
  return res.json();
}

export interface FileContent {
  path: string;
  content: string;
  size_bytes: number;
  truncated: boolean;
}

export async function getFileContent(repoId: string, filePath: string): Promise<FileContent> {
  const res = await fetch(`${API_BASE}/repos/${repoId}/files/${filePath}/content`);
  if (!res.ok) throw new Error("Failed to load file content");
  return res.json();
}

export async function queryRepo(repoId: string, question: string): Promise<RepoQueryResult> {
  const res = await fetch(`${API_BASE}/repos/${repoId}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  if (!res.ok) throw new Error("Query failed");
  return res.json();
}

export async function createSession(
  repoId: string,
  task: string,
  notebookId?: string,
): Promise<AgentSession> {
  const body: Record<string, string> = { task };
  if (notebookId) body.notebook_id = notebookId;

  const res = await fetch(`${API_BASE}/repos/${repoId}/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error((await res.json()).detail || "Create session failed");
  return res.json();
}

export async function listSessions(repoId: string): Promise<AgentSession[]> {
  const res = await fetch(`${API_BASE}/repos/${repoId}/sessions`);
  if (!res.ok) throw new Error("List sessions failed");
  return res.json();
}

export async function getSession(repoId: string, sessionId: string): Promise<AgentSession> {
  const res = await fetch(`${API_BASE}/repos/${repoId}/sessions/${sessionId}`);
  if (!res.ok) throw new Error("Get session failed");
  return res.json();
}

export async function sendSessionMessage(repoId: string, sessionId: string, message: string): Promise<void> {
  const res = await fetch(`${API_BASE}/repos/${repoId}/sessions/${sessionId}/message`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!res.ok) throw new Error("Send message failed");
}

export interface CommitResult {
  session_id: string;
  commit_hash: string;
  branch: string;
}

/**
 * Commit the agent's uncommitted changes in the session worktree.
 * @param repoId - UUID of the repo
 * @param sessionId - UUID of the session
 * @param message - Commit message
 * @param newBranch - Optional new branch name to create before committing
 * @returns Commit result with hash and branch
 */
export async function commitSession(
  repoId: string,
  sessionId: string,
  message: string,
  newBranch?: string,
): Promise<CommitResult> {
  const body: Record<string, string> = { message };
  if (newBranch) body.new_branch = newBranch;
  const res = await fetch(`${API_BASE}/repos/${repoId}/sessions/${sessionId}/commit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error((await res.json()).detail || "Commit failed");
  return res.json();
}

export async function getSessionDiff(repoId: string, sessionId: string): Promise<SessionDiff> {
  const res = await fetch(`${API_BASE}/repos/${repoId}/sessions/${sessionId}/diff`);
  if (!res.ok) throw new Error("Get diff failed");
  return res.json();
}

export async function mergeSession(repoId: string, sessionId: string, targetBranch = "main"): Promise<MergeResult> {
  const res = await fetch(`${API_BASE}/repos/${repoId}/sessions/${sessionId}/merge`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target_branch: targetBranch }),
  });
  if (!res.ok) throw new Error("Merge failed");
  return res.json();
}

export interface PullRequestResult {
  pr_url: string;
  pr_number: number;
  branch: string;
  base_branch: string;
}

/**
 * Push the session branch and open a GitHub pull request.
 * @param repoId - UUID of the repo
 * @param sessionId - UUID of the session
 * @param title - PR title
 * @param body - PR description (Markdown)
 * @param targetBranch - Base branch for the PR (default "main")
 * @returns PR result with URL and number
 */
export async function createPullRequest(
  repoId: string,
  sessionId: string,
  title: string,
  body: string,
  targetBranch = "main",
): Promise<PullRequestResult> {
  const res = await fetch(`${API_BASE}/repos/${repoId}/sessions/${sessionId}/pull-request`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, body, target_branch: targetBranch }),
  });
  if (!res.ok) throw new Error((await res.json()).detail || "Failed to create pull request");
  return res.json();
}

/**
 * Retry a failed session by re-running the agent with the same task.
 * Prefixes the message with [RETRY] so the frontend can render a separator.
 * @param repoId - UUID of the repo
 * @param sessionId - UUID of the failed session
 * @returns Status acknowledgement
 */
export async function retrySession(repoId: string, sessionId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/repos/${repoId}/sessions/${sessionId}/message`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: "[RETRY] The previous attempt failed. Please retry the original task from scratch — search the entire repo broadly, verify file paths, and make the required changes." }),
  });
  if (!res.ok) throw new Error("Retry failed");
}

export interface RevertResult {
  session_id: string;
  reverted: boolean;
  files_reverted: number;
  message?: string;
}

/**
 * Revert all uncommitted changes in the session worktree.
 */
export async function revertSession(repoId: string, sessionId: string): Promise<RevertResult> {
  const res = await fetch(`${API_BASE}/repos/${repoId}/sessions/${sessionId}/revert`, {
    method: "POST",
  });
  if (!res.ok) throw new Error((await res.json()).detail || "Revert failed");
  return res.json();
}

export interface Checkpoint {
  sha: string;
  step: number;
  message: string;
  timestamp: string;
}

/**
 * List all checkpoints for a session.
 */
export async function getSessionCheckpoints(repoId: string, sessionId: string): Promise<Checkpoint[]> {
  const res = await fetch(`${API_BASE}/repos/${repoId}/sessions/${sessionId}/checkpoints`);
  if (!res.ok) throw new Error("Failed to load checkpoints");
  const data = await res.json();
  return data.checkpoints || [];
}

/**
 * Restore the session worktree to a specific checkpoint step.
 */
export async function restoreCheckpoint(repoId: string, sessionId: string, step: number): Promise<{ restored_to_step: number; sha: string }> {
  const res = await fetch(`${API_BASE}/repos/${repoId}/sessions/${sessionId}/restore`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ step }),
  });
  if (!res.ok) throw new Error((await res.json()).detail || "Restore failed");
  return res.json();
}

/**
 * Re-run a specific step from the agent log with optional argument overrides.
 */
export async function rerunStep(repoId: string, sessionId: string, step: number, modifiedArgs?: Record<string, unknown>): Promise<void> {
  const body: Record<string, unknown> = { step };
  if (modifiedArgs) body.modified_args = modifiedArgs;
  const res = await fetch(`${API_BASE}/repos/${repoId}/sessions/${sessionId}/rerun`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error((await res.json()).detail || "Rerun failed");
}

export async function cancelSession(repoId: string, sessionId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/repos/${repoId}/sessions/${sessionId}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Cancel session failed");
}

/**
 * Stop a running agent session immediately.
 * @param repoId - UUID of the repo
 * @param sessionId - UUID of the session
 * @returns Status dict with session_id, status, and message
 */
export async function stopSession(
  repoId: string,
  sessionId: string,
): Promise<{ session_id: string; status: string; message: string }> {
  const res = await fetch(`${API_BASE}/repos/${repoId}/sessions/${sessionId}/stop`, {
    method: "POST",
  });
  if (!res.ok) throw new Error((await res.json()).detail || "Stop session failed");
  return res.json();
}

export function connectAgentWs(repoId: string, sessionId: string): WebSocket {
  return new WebSocket(`${WS_BASE}/repos/${repoId}/sessions/${sessionId}/ws`);
}

/**
 * Get the SSE stream URL for real-time agent session events.
 * @param repoId - UUID of the repo
 * @param sessionId - UUID of the session
 * @returns Full URL to the SSE endpoint
 */
export function getSessionStreamUrl(repoId: string, sessionId: string): string {
  return `${API_BASE}/repos/${repoId}/sessions/${sessionId}/stream`;
}

// ─── GitHub OAuth ───

export interface GitHubStatus {
  connected: boolean;
  github_user?: string;
  scope?: string;
  connected_at?: string;
}

/**
 * Check if a GitHub account is connected.
 * @returns Connection status with optional user info.
 */
export async function getGitHubStatus(): Promise<GitHubStatus> {
  const res = await fetch(`${API_BASE}/auth/github/status`);
  if (!res.ok) return { connected: false };
  return res.json();
}

/**
 * Get the URL to start the GitHub OAuth flow.
 * Opens in a new window/tab to authorize on GitHub.
 * @returns The backend redirect URL.
 */
export function getGitHubAuthUrl(): string {
  return `${API_BASE}/auth/github`;
}

/**
 * Disconnect the connected GitHub account.
 * @returns Disconnection result.
 */
export async function disconnectGitHub(): Promise<{ disconnected: boolean }> {
  const res = await fetch(`${API_BASE}/auth/github/disconnect`, { method: "POST" });
  if (!res.ok) throw new Error("Disconnect failed");
  return res.json();
}
