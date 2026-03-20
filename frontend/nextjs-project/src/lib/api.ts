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
