const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ─── Shared types ───

export interface Source {
  citation: string;
  section_title: string;
  page: number;
  score: number;
}

export interface QueryResponse {
  question: string;
  answer: string;
  references: { sections: string[]; pages: number[] };
  chunks_used: number;
  latency_ms: number;
  sources: Source[];
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
  const timeout = setTimeout(() => controller.abort(), 60000);

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
