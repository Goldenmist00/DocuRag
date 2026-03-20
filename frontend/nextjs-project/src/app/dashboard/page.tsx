"use client";

import { useState, useRef, useEffect, useCallback, Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  askQuestion,
  listSources,
  uploadSourceWithProgress,
  addTextSource,
  deleteSource as deleteSourceApi,
  updateNotebookTitle,
  generateFlashcards,
  generateSummary,
  generateMindMap,
  generateQuiz,
  type SourceRecord,
  type Source as ChunkSource,
  type Flashcard,
  type MindMapData,
  type QuizQuestion,
} from "@/lib/api";
import { useToast } from "@/components/ui/toast";

/* ─── Client-side extended source type ─── */
interface ClientSource extends SourceRecord {
  _uploadProgress?: number;
  _isOptimistic?: boolean;
}

/**
 * Map a source's pipeline status to an overall 0-100 percentage.
 * Upload phase (0-15), pending (18), extracting (25), chunking (40),
 * embedding (40-85 based on batch ratio), storing (90), ready (100).
 */
function getProgressPercent(source: ClientSource): number {
  const { status, _uploadProgress } = source;
  if (status === "uploading") return Math.round((_uploadProgress ?? 0) * 0.15);
  if (status === "pending") return 18;
  if (status === "extracting") return 25;
  if (status === "chunking") return 40;
  if (status.startsWith("embedding")) {
    const match = status.match(/(\d+)\/(\d+)/);
    if (match) {
      const ratio = parseInt(match[1]) / parseInt(match[2]);
      return Math.round(40 + ratio * 45);
    }
    return 50;
  }
  if (status === "storing") return 90;
  if (status === "ready") return 100;
  if (status === "error") return 100;
  return 0;
}

/**
 * Readable label for each pipeline status shown in the sidebar row.
 */
function getStatusLabel(status: string): string {
  if (status === "uploading") return "uploading…";
  if (status === "pending") return "queued";
  if (status === "extracting") return "extracting…";
  if (status === "chunking") return "chunking…";
  if (status.startsWith("embedding")) return status;
  if (status === "storing") return "saving…";
  return status;
}

const isTerminalStatus = (status: string) => status === "ready" || status === "error";

/* ─── types ─── */
type SourceAttribution = { name: string; pages: number[] };
type Message = { id: number; role: "user" | "ai"; text: string; sourceAttrs?: SourceAttribution[] };
type StudioView = "home" | "flashcards" | "mindmap" | "summary" | "quiz";

/* ─── sample data ─── */
const CARDS = [
  {
    term: "Mitochondria",
    def: "The powerhouse of the cell — a double-membraned organelle that produces ATP through oxidative phosphorylation.",
    q: "What organelle produces most of the cell's ATP?",
    a: "Mitochondria, via oxidative phosphorylation in the inner membrane.",
    key: "ATP synthesis",
    exp: "Occurs via chemiosmosis — protons flow through ATP synthase down their gradient.",
    tag: "Cell Biology",
    difficulty: "Easy",
  },
  {
    term: "Osmosis",
    def: "The passive movement of water molecules across a semi-permeable membrane from a region of low solute concentration to high solute concentration.",
    q: "In which direction does water move during osmosis?",
    a: "From low solute concentration (high water potential) to high solute concentration (low water potential).",
    key: "Passive transport",
    exp: "No energy required — driven purely by the water potential gradient.",
    tag: "Transport",
    difficulty: "Easy",
  },
  {
    term: "Ribosome",
    def: "A molecular machine found in all cells that synthesises proteins by translating mRNA sequences into amino acid chains.",
    q: "Where does translation (protein synthesis) occur in the cell?",
    a: "At ribosomes — either free in the cytoplasm or bound to the rough endoplasmic reticulum.",
    key: "Translation",
    exp: "mRNA codons are read by tRNA anticodons; peptide bonds form between amino acids.",
    tag: "Genetics",
    difficulty: "Medium",
  },
  {
    term: "Photosynthesis",
    def: "The process by which plants, algae, and some bacteria convert light energy into chemical energy stored as glucose.",
    q: "What is the overall equation for photosynthesis?",
    a: "6CO₂ + 6H₂O + light energy → C₆H₁₂O₆ + 6O₂",
    key: "Light reactions + Calvin cycle",
    exp: "Light reactions occur in the thylakoid; the Calvin cycle occurs in the stroma.",
    tag: "Metabolism",
    difficulty: "Medium",
  },
  {
    term: "DNA Replication",
    def: "The biological process of producing two identical copies of DNA from one original DNA molecule, occurring before cell division.",
    q: "What enzyme is primarily responsible for synthesising new DNA strands?",
    a: "DNA polymerase — it adds nucleotides in the 5′ to 3′ direction.",
    key: "Semi-conservative replication",
    exp: "Each new double helix contains one original and one new strand.",
    tag: "Genetics",
    difficulty: "Hard",
  },
  {
    term: "Enzyme",
    def: "A biological catalyst — usually a protein — that speeds up chemical reactions by lowering the activation energy without being consumed.",
    q: "How do enzymes speed up reactions?",
    a: "By lowering the activation energy required for the reaction to proceed.",
    key: "Active site & substrate",
    exp: "The substrate binds to the enzyme's active site, forming an enzyme-substrate complex.",
    tag: "Biochemistry",
    difficulty: "Easy",
  },
];

const MINDMAP = {
  root: "Cell Biology",
  branches: [
    { label: "Mitochondria",   children: ["ATP Production", "Oxidative Phosphorylation", "Chemiosmosis"] },
    { label: "Cell Membrane",  children: ["Osmosis", "Active Transport", "Phospholipid Bilayer"] },
    { label: "Ribosomes",      children: ["Translation", "mRNA Codons", "Protein Synthesis"] },
    { label: "Nucleus",        children: ["DNA Replication", "Gene Expression", "Nuclear Envelope"] },
    { label: "Enzymes",        children: ["Active Site", "Activation Energy", "Catalysis"] },
  ],
};

const QUIZ = [
  { q: "What is the primary function of mitochondria?", options: ["Protein synthesis", "ATP production", "DNA replication", "Lipid storage"], answer: 1 },
  { q: "Osmosis involves the movement of which molecule?", options: ["Glucose", "Oxygen", "Water", "Sodium"], answer: 2 },
  { q: "Where does translation occur in the cell?", options: ["Nucleus", "Mitochondria", "Golgi apparatus", "Ribosomes"], answer: 3 },
];

const EMPTY_MESSAGES: Message[] = [];

/* ─── small icon components ─── */
function Icon({ d, size = 16 }: { d: string | string[]; size?: number }) {
  const paths = Array.isArray(d) ? d : [d];
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" style={{ flexShrink: 0 }}>
      {paths.map((p, i) => <path key={i} d={p} stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />)}
    </svg>
  );
}

/* ─── Sidebar: Sources (presentational — state lifted to DashboardInner) ─── */
function SourcesSidebar({
  sources,
  onAdd,
  onDelete,
}: {
  sources: ClientSource[];
  onAdd: () => void;
  onDelete: (id: string) => void;
}) {
  return (
    <aside style={{
      width: 240,
      background: "transparent",
      display: "flex",
      flexDirection: "column",
      flexShrink: 0,
      overflow: "hidden",
    }}>
      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes progressPulse {
          0%,100% { opacity: 1; }
          50% { opacity: 0.6; }
        }
      `}</style>
      <div style={{ padding: "14px 12px 10px", borderBottom: "1px solid #1a1a1a" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
          <span style={{ fontSize: "0.72rem", fontWeight: 600, color: "rgba(255,255,255,0.35)", letterSpacing: "0.08em", textTransform: "uppercase" }}>Sources</span>
          <span style={{ fontSize: "0.65rem", padding: "2px 7px", borderRadius: 4, background: "#1a1a1a", color: "rgba(255,255,255,0.4)", border: "1px solid #2a2a2a" }}>{sources.length}</span>
        </div>
        <button onClick={onAdd} className="action-btn" style={{
          width: "100%",
          padding: "8px",
          borderRadius: 6,
          border: "1px dashed #2a2a2a",
          background: "transparent",
          color: "rgba(255,255,255,0.4)",
          cursor: "pointer",
          fontSize: "0.78rem",
          fontFamily: "inherit",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          gap: 6,
          transition: "border-color 0.15s, color 0.15s",
        }}>
          <Icon d="M12 5v14M5 12h14" />
          Add source
        </button>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: "8px" }}>
        {sources.map(s => (
          <SourceRow key={s.id} source={s} onDelete={onDelete} />
        ))}
      </div>
    </aside>
  );
}

/* ─── Source row with progress bar and hover delete ─── */
function SourceRow({ source: s, onDelete }: {
  source: ClientSource;
  onDelete: (id: string) => void;
}) {
  const [hovered, setHovered] = useState(false);
  const terminal = isTerminalStatus(s.status);
  const percent = getProgressPercent(s);
  const label = s.status === "uploading" && s._uploadProgress != null
    ? `uploading ${s._uploadProgress}%`
    : getStatusLabel(s.status);

  return (
    <div
      className="source-row"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        padding: "7px 8px",
        borderRadius: 6,
        cursor: "default",
        transition: "background 0.1s",
        marginBottom: 2,
        background: hovered ? "rgba(255,255,255,0.03)" : "transparent",
      }}
    >
      {/* Top row: icon + name + status / delete */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <div style={{ flexShrink: 0, width: 24, height: 24, borderRadius: 5, background: "#111", border: "1px solid #222", display: "flex", alignItems: "center", justifyContent: "center" }}>
          <Icon d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8zM14 2v6h6" size={11} />
        </div>
        <span style={{ fontSize: "0.75rem", color: "rgba(255,255,255,0.45)", overflow: "hidden", whiteSpace: "nowrap", textOverflow: "ellipsis", flex: 1 }}>{s.name}</span>

        {/* Status indicator for non-terminal states */}
        {!terminal && (
          <div style={{ display: "flex", alignItems: "center", gap: 4, flexShrink: 0 }}>
            <div style={{ width: 8, height: 8, borderRadius: "50%", border: "1.5px solid rgba(255,255,255,0.3)", borderTopColor: "rgba(140,175,255,0.8)", animation: "spin 0.8s linear infinite" }} />
            <span style={{ fontSize: "0.58rem", color: "rgba(140,175,255,0.7)", whiteSpace: "nowrap", maxWidth: 72, overflow: "hidden", textOverflow: "ellipsis" }}>{label}</span>
          </div>
        )}

        {/* Error dot */}
        {s.status === "error" && (
          <div style={{ width: 8, height: 8, borderRadius: "50%", background: "#ef4444", flexShrink: 0 }} title={s.error_message || "Error"} />
        )}

        {/* Ready checkmark */}
        {s.status === "ready" && (
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" style={{ flexShrink: 0 }}>
            <path d="M20 6L9 17l-5-5" stroke="rgba(74,222,128,0.7)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        )}

        {/* Delete button on hover (only when terminal) */}
        {hovered && terminal && (
          <button
            onClick={e => { e.stopPropagation(); onDelete(s.id); }}
            title="Remove source"
            style={{
              background: "none", border: "none", cursor: "pointer",
              padding: 2, display: "flex", alignItems: "center", justifyContent: "center",
              color: "rgba(255,255,255,0.25)", transition: "color 0.15s", flexShrink: 0,
            }}
            onMouseEnter={e => (e.currentTarget.style.color = "#ef4444")}
            onMouseLeave={e => (e.currentTarget.style.color = "rgba(255,255,255,0.25)")}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
              <path d="M18 6L6 18M6 6l12 12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
        )}
      </div>

      {/* Progress bar underneath — visible only during processing */}
      {!terminal && (
        <div style={{
          width: "100%",
          height: 3,
          borderRadius: 2,
          background: "rgba(255,255,255,0.06)",
          overflow: "hidden",
          marginTop: 5,
        }}>
          <div style={{
            height: "100%",
            borderRadius: 2,
            background: "linear-gradient(90deg, #3b82f6, #8b5cf6)",
            width: `${percent}%`,
            transition: "width 0.4s ease",
            animation: percent < 18 ? "progressPulse 1.4s ease-in-out infinite" : "none",
          }} />
        </div>
      )}
    </div>
  );
}

/* ─── Chat area ─── */
function ChatArea({ isNew, notebookId, onUploadFiles }: { isNew: boolean; notebookId: string | null; onUploadFiles?: (files: File[]) => void }) {
  const [messages, setMessages] = useState<Message[]>(EMPTY_MESSAGES);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [draggingOver, setDraggingOver] = useState(false);
  const [droppedFiles, setDroppedFiles] = useState<string[]>([]);
  const chatFileRef = useRef<HTMLInputElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const dragCounter = useRef(0);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  /**
   * Build de-duplicated source attribution list from chunk results.
   * Groups pages by source_name for a compact display.
   */
  const buildAttrs = (chunks: ChunkSource[]): SourceAttribution[] => {
    const map = new Map<string, Set<number>>();
    for (const c of chunks) {
      const name = c.source_name || "Unknown source";
      if (!map.has(name)) map.set(name, new Set());
      if (c.page) map.get(name)!.add(c.page);
    }
    return Array.from(map.entries()).map(([name, pages]) => ({
      name,
      pages: Array.from(pages).sort((a, b) => a - b),
    }));
  };

  const send = async () => {
    if (!input.trim() || loading) return;
    const userMsg: Message = { id: Date.now(), role: "user", text: input };
    setMessages(p => [...p, userMsg]);
    setInput("");
    setLoading(true);
    try {
      const result = await askQuestion(input, 10, notebookId ?? undefined);
      const attrs = buildAttrs(result.sources);
      const aiMsg: Message = { id: Date.now() + 1, role: "ai", text: result.answer, sourceAttrs: attrs };
      setMessages(p => [...p, aiMsg]);
    } catch (err: unknown) {
      const detail = err instanceof Error ? err.message : String(err);
      const errMsg: Message = {
        id: Date.now() + 1,
        role: "ai",
        text: `Backend error: ${detail}`,
      };
      setMessages(p => [...p, errMsg]);
    } finally {
      setLoading(false);
    }
  };

  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    dragCounter.current++;
    if (e.dataTransfer.items && e.dataTransfer.items.length > 0) setDraggingOver(true);
  };
  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    dragCounter.current--;
    if (dragCounter.current === 0) setDraggingOver(false);
  };
  const handleDragOver = (e: React.DragEvent) => { e.preventDefault(); };
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    dragCounter.current = 0;
    setDraggingOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const files = Array.from(e.dataTransfer.files);
      setDroppedFiles(files.map(f => f.name));
      onUploadFiles?.(files);
    }
  };
  const handleChatFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const files = Array.from(e.target.files);
      setDroppedFiles(files.map(f => f.name));
      onUploadFiles?.(files);
    }
    e.target.value = "";
  };

  return (
    <div
      style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", position: "relative", background: "transparent" }}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      {/* Full-area drag overlay */}
      {draggingOver && (
        <div style={{
          position: "absolute", inset: 0, zIndex: 10,
          background: "rgba(91,138,240,0.04)",
          border: "2px dashed rgba(91,138,240,0.35)",
          borderRadius: 0,
          display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 12,
          pointerEvents: "none",
        }}>
          <div style={{ width: 56, height: 56, borderRadius: 16, background: "rgba(91,138,240,0.12)", border: "1px solid rgba(91,138,240,0.3)", display: "flex", alignItems: "center", justifyContent: "center" }}>
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M17 8l-5-5-5 5M12 3v13" stroke="rgba(140,175,255,0.9)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <p style={{ fontSize: "0.95rem", fontWeight: 600, color: "rgba(140,175,255,0.9)", margin: 0 }}>Drop to add source</p>
          <p style={{ fontSize: "0.75rem", color: "rgba(255,255,255,0.35)", margin: 0 }}>pdf, docs, images, audio, and more</p>
        </div>
      )}

      <input type="file" ref={chatFileRef} style={{ display: "none" }} multiple accept=".pdf,.doc,.docx,.txt,.png,.jpg,.jpeg,.mp3,.mp4" onChange={handleChatFileChange} />

      {/* Messages */}
      <div style={{ flex: 1, overflowY: "auto", padding: "24px 0" }}>
        {messages.length === 0 ? (
          /* ── Empty state for a fresh book ── */
          <div style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            height: "100%",
            gap: 14,
            padding: "0 24px",
            textAlign: "center",
          }}>
            {droppedFiles.length > 0 ? (
              /* ── Files just dropped ── */
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>
                <div style={{ width: 44, height: 44, borderRadius: 12, background: "rgba(34,197,94,0.12)", border: "1px solid rgba(34,197,94,0.25)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
                    <path d="M20 6L9 17l-5-5" stroke="rgba(134,239,172,0.9)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </div>
                <div>
                  <p style={{ color: "rgba(255,255,255,0.8)", fontWeight: 600, fontSize: "0.95rem", margin: "0 0 6px" }}>
                    {droppedFiles.length === 1 ? droppedFiles[0] : `${droppedFiles.length} files added`}
                  </p>
                  <p style={{ color: "rgba(255,255,255,0.3)", fontSize: "0.78rem", margin: 0 }}>Source added — ask anything below.</p>
                </div>
              </div>
            ) : (
              <>
                <div
                  onClick={() => chatFileRef.current?.click()}
                  style={{
                    width: 64, height: 64, borderRadius: 16,
                    background: "rgba(255,255,255,0.05)",
                    border: "1px solid rgba(255,255,255,0.1)",
                    display: "flex", alignItems: "center", justifyContent: "center",
                    cursor: "pointer", transition: "background 0.15s, border-color 0.15s",
                  }}
                  className="action-btn"
                >
                  <svg width="26" height="26" viewBox="0 0 24 24" fill="none">
                    <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" stroke="rgba(255,255,255,0.5)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                    <polyline points="14 2 14 8 20 8" stroke="rgba(255,255,255,0.5)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </div>
                <div>
                  <p style={{ color: "rgba(255,255,255,0.75)", fontWeight: 600, fontSize: "0.95rem", margin: "0 0 6px" }}>Start by adding a source</p>
                  <p style={{ color: "rgba(255,255,255,0.3)", fontSize: "0.82rem", margin: 0, lineHeight: 1.6 }}>
                    Drag & drop a file here, or{" "}
                    <span
                      onClick={() => chatFileRef.current?.click()}
                      style={{ color: "rgba(255,255,255,0.5)", cursor: "pointer", textDecoration: "underline", textUnderlineOffset: 2 }}
                    >
                      browse
                    </span>
                  </p>
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "center", marginTop: 4 }}>
                  {["Summarise this document", "What are the key concepts?", "Create flashcards for me"].map(s => (
                    <button key={s} onClick={() => setInput(s)} style={{ padding: "6px 12px", borderRadius: 20, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(255,255,255,0.04)", color: "rgba(255,255,255,0.5)", fontSize: "0.75rem", cursor: "pointer", fontFamily: "inherit", transition: "border-color 0.15s, color 0.15s" }} className="suggestion-btn">
                      {s}
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
        ) : (
          <div style={{ maxWidth: 680, margin: "0 auto", padding: "0 24px", display: "flex", flexDirection: "column", gap: 20 }}>
            {messages.map(m => (
              <div key={m.id} style={{ display: "flex", flexDirection: "column", alignItems: m.role === "user" ? "flex-end" : "flex-start" }}>
              {m.role === "ai" && (
                <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 6 }}>
                  <img src="/Group 39.svg" alt="MindSync" style={{ width: 22, height: 22, borderRadius: "50%", objectFit: "cover" }} />
                  <span style={{ fontSize: "0.68rem", color: "rgba(255,255,255,0.3)" }}>MindSync</span>
                </div>
              )}
              <div style={{
                maxWidth: "78%",
                padding: "10px 14px",
                borderRadius: m.role === "user" ? "12px 12px 4px 12px" : "4px 12px 12px 12px",
                background: m.role === "user" ? "#111" : "transparent",
                border: `1px solid ${m.role === "user" ? "#222" : "transparent"}`,
                fontSize: "0.86rem",
                color: "rgba(255,255,255,0.85)",
                lineHeight: 1.65,
              }}>
                {m.text}
              </div>
              {/* Source attribution badges */}
              {m.role === "ai" && m.sourceAttrs && m.sourceAttrs.length > 0 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8, maxWidth: "78%" }}>
                  {m.sourceAttrs.map((sa, i) => (
                    <div key={i} style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 5,
                      padding: "4px 10px",
                      borderRadius: 6,
                      background: "rgba(91,138,240,0.08)",
                      border: "1px solid rgba(91,138,240,0.18)",
                      fontSize: "0.68rem",
                      color: "rgba(140,175,255,0.85)",
                      lineHeight: 1.3,
                    }}>
                      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" style={{ flexShrink: 0 }}>
                        <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                        <path d="M14 2v6h6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                      <span style={{ maxWidth: 140, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{sa.name}</span>
                      {sa.pages.length > 0 && (
                        <span style={{ color: "rgba(140,175,255,0.5)", fontSize: "0.62rem" }}>
                          p.{sa.pages.length <= 3 ? sa.pages.join(", ") : `${sa.pages[0]}–${sa.pages[sa.pages.length - 1]}`}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
          {loading && (
            <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
              <img src="/Group 39.svg" alt="MindSync" style={{ width: 22, height: 22, borderRadius: "50%", objectFit: "cover" }} />
              <div style={{ display: "flex", gap: 4 }}>
                {[0, 1, 2].map(i => <span key={i} className={`dot dot-${i}`} style={{ width: 6, height: 6, borderRadius: "50%", background: "rgba(140,175,255,0.5)", display: "inline-block" }} />)}
              </div>
            </div>
          )}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* Input */}
      <div style={{ padding: "10px 20px 16px", borderTop: "1px solid #1a1a1a", flexShrink: 0, background: "transparent" }}>
        <div style={{ maxWidth: 680, margin: "0 auto", display: "flex", gap: 8, alignItems: "flex-end", background: "#0a0a0a", border: "1px solid #222", borderRadius: 10, padding: "8px 10px" }}>
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === "Enter" && !e.shiftKey && (e.preventDefault(), send())}
            placeholder="Ask anything about your sources…"
            rows={1}
            style={{
              flex: 1, background: "transparent", border: "none", outline: "none",
              color: "rgba(255,255,255,0.88)", fontSize: "0.875rem", fontFamily: "inherit",
              resize: "none", lineHeight: 1.6,
            }}
          />
          <button
            onClick={send}
            disabled={!input.trim() || loading}
            style={{
              width: 30, height: 30, borderRadius: "50%", border: "none",
              background: input.trim() && !loading ? "#fff" : "#1a1a1a",
              cursor: input.trim() && !loading ? "pointer" : "not-allowed",
              display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
              transition: "background 0.15s",
            }}
          >
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none">
              <line x1="22" y1="2" x2="11" y2="13" stroke={input.trim() && !loading ? "#000" : "rgba(255,255,255,0.2)"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              <polygon points="22 2 15 22 11 13 2 9 22 2" stroke={input.trim() && !loading ? "#000" : "rgba(255,255,255,0.2)"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}

/* ─── Tool Grid with tooltips ─── */
function ToolGrid({
  tools,
  onSelect,
  generating,
}: {
  tools: { id: StudioView; label: string; sub: string; icon: string }[];
  onSelect: (v: StudioView) => void;
  generating: StudioView | null;
}) {
  const [hovered, setHovered] = useState<StudioView | null>(null);

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
      {tools.map((t, i) => {
        const isHovered = hovered === t.id;
        const isGenerating = generating === t.id;
        const isRightCol = i % 2 === 1;

        return (
          <div key={t.id} style={{ position: "relative" }}>
            <button
              onClick={() => !generating && onSelect(t.id)}
              onMouseEnter={() => setHovered(t.id)}
              onMouseLeave={() => setHovered(null)}
              style={{
                width: "100%",
                padding: "12px 10px",
                background: isGenerating ? "#111" : isHovered ? "#111" : "#0a0a0a",
                border: `1px solid ${isGenerating ? "#2a2a2a" : isHovered ? "#2a2a2a" : "#1a1a1a"}`,
                borderRadius: 8,
                color: isGenerating ? "rgba(255,255,255,0.6)" : isHovered ? "rgba(255,255,255,0.9)" : "rgba(255,255,255,0.45)",
                cursor: generating ? "default" : "pointer",
                display: "flex",
                flexDirection: "column",
                alignItems: "flex-start",
                gap: 8,
                transition: "all 0.1s ease",
                fontFamily: "inherit",
                textAlign: "left",
                position: "relative",
                overflow: "hidden",
                opacity: generating && !isGenerating ? 0.4 : 1,
              }}
            >
              {/* Shimmer sweep overlay while generating */}
              {isGenerating && (
                <div style={{
                  position: "absolute",
                  inset: 0,
                  background: "linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.06) 50%, transparent 100%)",
                  animation: "shimmerSweep 1.2s ease-in-out infinite",
                  pointerEvents: "none",
                }} />
              )}

              {/* Icon or spinner */}
              {isGenerating ? (
                <div style={{ width: 20, height: 20, display: "flex", alignItems: "center", justifyContent: "center" }}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" style={{ animation: "spin 0.9s linear infinite" }}>
                    <circle cx="12" cy="12" r="9" stroke="rgba(255,255,255,0.12)" strokeWidth="2" />
                    <path d="M12 3a9 9 0 019 9" stroke="rgba(140,175,255,0.7)" strokeWidth="2" strokeLinecap="round" />
                  </svg>
                </div>
              ) : (
                <Icon d={t.icon} size={20} />
              )}

              <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                <span style={{ fontSize: "0.82rem", fontWeight: 500 }}>{t.label}</span>
                {isGenerating && (
                  <span style={{ fontSize: "0.68rem", color: "rgba(140,175,255,0.6)", animation: "generatingPulse 1.4s ease-in-out infinite" }}>
                    Generating…
                  </span>
                )}
              </div>
            </button>

            {/* Tooltip */}
            {isHovered && !generating && (
              <div style={{
                position: "absolute",
                bottom: "calc(100% + 6px)",
                left: isRightCol ? "auto" : 0,
                right: isRightCol ? 0 : "auto",
                background: "#fff",
                color: "#000",
                fontSize: "0.75rem",
                fontWeight: 500,
                padding: "7px 10px",
                borderRadius: 6,
                whiteSpace: "normal",
                width: 170,
                boxShadow: "0 4px 16px rgba(0,0,0,0.3)",
                zIndex: 20,
                lineHeight: 1.5,
                pointerEvents: "none",
              }}>
                {t.sub}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ─── Mind Map ─── */
/* ─── Mind Map ─── */
function MindMap({ fullscreen, data }: { fullscreen?: boolean; data?: { root: string; branches: { label: string; children: string[] }[] } }) {
  const [expandedBranch, setExpandedBranch] = useState<number | null>(null);
  const [zoom, setZoom] = useState(1);

  const mapData = data || MINDMAP;

  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    setZoom(z => Math.min(2.5, Math.max(0.4, z - e.deltaY * 0.001)));
  };

  // Layout constants — scale up when fullscreen
  const scale = fullscreen ? 1.6 : 1;
  const ROOT_X = 20;
  const ROOT_Y = 220;
  const ROOT_W = 120 * scale;
  const ROOT_H = 38 * scale;
  const BRANCH_X = (180) * scale;
  const BRANCH_W = 130 * scale;
  const BRANCH_H = 34 * scale;
  const CHILD_X = (360) * scale;
  const CHILD_W = 120 * scale;
  const CHILD_H = 30 * scale;

  const branchCount = mapData.branches.length;
  const branchSpacing = 60 * scale;
  const totalBranchHeight = (branchCount - 1) * branchSpacing;
  const branchStartY = ROOT_Y - totalBranchHeight / 2;

  let svgHeight = Math.max(440, branchCount * branchSpacing + 140);
  if (expandedBranch !== null) {
    const childCount = mapData.branches[expandedBranch].children.length;
    svgHeight = Math.max(svgHeight, branchCount * branchSpacing + childCount * 40 * scale + 180);
  }

  const svgWidth = fullscreen ? 700 : 440;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10, height: fullscreen ? "100%" : "auto" }}>
      {/* Zoom controls */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, justifyContent: "flex-end" }}>
        <span style={{ fontSize: "0.68rem", color: "rgba(255,255,255,0.25)" }}>{Math.round(zoom * 100)}%</span>
        <button onClick={() => setZoom(z => Math.min(2.5, z + 0.15))} style={{ width: 24, height: 24, borderRadius: 6, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(255,255,255,0.04)", color: "rgba(255,255,255,0.5)", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "1rem", lineHeight: 1 }}>+</button>
        <button onClick={() => setZoom(z => Math.max(0.4, z - 0.15))} style={{ width: 24, height: 24, borderRadius: 6, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(255,255,255,0.04)", color: "rgba(255,255,255,0.5)", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "1rem", lineHeight: 1 }}>−</button>
        <button onClick={() => setZoom(1)} style={{ padding: "0 8px", height: 24, borderRadius: 6, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(255,255,255,0.04)", color: "rgba(255,255,255,0.35)", cursor: "pointer", fontSize: "0.68rem", fontFamily: "inherit" }}>Reset</button>
      </div>

      {/* SVG canvas */}
      <div
        onWheel={handleWheel}
        style={{
          borderRadius: 12,
          border: "1px solid rgba(255,255,255,0.1)",
          background: "rgba(255,255,255,0.02)",
          overflow: "auto",
          position: "relative",
          flex: fullscreen ? 1 : "none",
          cursor: "grab",
        }}
      >
        <svg
          width={svgWidth * zoom}
          height={svgHeight * zoom}
          viewBox={`0 0 ${svgWidth} ${svgHeight}`}
          style={{ display: "block", transition: "width 0.2s, height 0.2s" }}
        >
          {/* ── Root node ── */}
          <g>
            <rect
              x={ROOT_X} y={ROOT_Y - ROOT_H / 2}
              width={ROOT_W} height={ROOT_H}
              rx={ROOT_H / 2}
              fill="rgba(255,255,255,0.08)"
              stroke="rgba(255,255,255,0.3)"
              strokeWidth="1.5"
            />
            <text
              x={ROOT_X + ROOT_W / 2} y={ROOT_Y + 5}
              textAnchor="middle"
              fill="rgba(255,255,255,0.85)"
              fontSize={12 * scale}
              fontWeight="600"
              fontFamily="inherit"
            >
              {mapData.root}
            </text>
          </g>

          {/* ── Branches ── */}
          {mapData.branches.map((branch, bi) => {
            const by = branchStartY + bi * branchSpacing;
            const isExpanded = expandedBranch === bi;
            const childCount = branch.children.length;

            const x1 = ROOT_X + ROOT_W;
            const y1 = ROOT_Y;
            const x2 = BRANCH_X;
            const y2 = by;
            const cx1 = x1 + (x2 - x1) * 0.55;
            const cy1 = y1;
            const cx2 = x1 + (x2 - x1) * 0.45;
            const cy2 = y2;

            const childSpacing = 38 * scale;
            const totalChildH = (childCount - 1) * childSpacing;
            const childStartY = by - totalChildH / 2;

            return (
              <g key={bi}>
                <path
                  d={`M ${x1} ${y1} C ${cx1} ${cy1}, ${cx2} ${cy2}, ${x2} ${y2}`}
                  fill="none"
                  stroke="rgba(255,255,255,0.2)"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                />

                <rect
                  x={BRANCH_X} y={by - BRANCH_H / 2}
                  width={BRANCH_W} height={BRANCH_H}
                  rx={BRANCH_H / 2}
                  fill={isExpanded ? "rgba(255,255,255,0.1)" : "rgba(255,255,255,0.05)"}
                  stroke={isExpanded ? "rgba(255,255,255,0.3)" : "rgba(255,255,255,0.12)"}
                  strokeWidth="1.2"
                  style={{ cursor: "pointer", transition: "fill 0.2s, stroke 0.2s" }}
                  onClick={() => setExpandedBranch(isExpanded ? null : bi)}
                />
                <text
                  x={BRANCH_X + 16} y={by + 5 * scale}
                  fill={isExpanded ? "rgba(255,255,255,0.9)" : "rgba(255,255,255,0.75)"}
                  fontSize={11 * scale}
                  fontWeight="500"
                  fontFamily="inherit"
                  style={{ pointerEvents: "none" }}
                >
                  {branch.label}
                </text>
                <text
                  x={BRANCH_X + BRANCH_W - 16} y={by + 5 * scale}
                  fill={isExpanded ? "rgba(255,255,255,0.7)" : "rgba(255,255,255,0.3)"}
                  fontSize={12 * scale}
                  fontWeight="700"
                  fontFamily="inherit"
                  style={{ cursor: "pointer", userSelect: "none", transition: "fill 0.2s" }}
                  onClick={() => setExpandedBranch(isExpanded ? null : bi)}
                >
                  {isExpanded ? "‹" : "›"}
                </text>

                {isExpanded && branch.children.map((child, ci) => {
                  const cy = childStartY + ci * childSpacing;
                  const bx2 = BRANCH_X + BRANCH_W;
                  const ccx1 = bx2 + (CHILD_X - bx2) * 0.55;
                  const ccy1 = by;
                  const ccx2 = bx2 + (CHILD_X - bx2) * 0.45;
                  const ccy2 = cy;

                  return (
                    <g key={ci}>
                      <path
                        d={`M ${bx2} ${by} C ${ccx1} ${ccy1}, ${ccx2} ${ccy2}, ${CHILD_X} ${cy}`}
                        fill="none"
                        stroke="rgba(255,255,255,0.15)"
                        strokeWidth="1.2"
                        strokeLinecap="round"
                        strokeDasharray="4 3"
                      />
                      <rect
                        x={CHILD_X} y={cy - CHILD_H / 2}
                        width={CHILD_W} height={CHILD_H}
                        rx={CHILD_H / 2}
                        fill="rgba(255,255,255,0.04)"
                        stroke="rgba(255,255,255,0.09)"
                        strokeWidth="1"
                      />
                      <text
                        x={CHILD_X + CHILD_W / 2} y={cy + 4 * scale}
                        textAnchor="middle"
                        fill="rgba(255,255,255,0.6)"
                        fontSize={10 * scale}
                        fontFamily="inherit"
                        style={{ pointerEvents: "none" }}
                      >
                        {child}
                      </text>
                    </g>
                  );
                })}
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

/* ─── Studio sidebar ─── */
function StudioSidebar({ isNew, view, onViewChange, fullscreen, onFullscreenChange, notebookId }: {
  isNew: boolean;
  view: StudioView;
  onViewChange: (v: StudioView) => void;
  fullscreen: boolean;
  onFullscreenChange: (v: boolean) => void;
  notebookId: string | null;
}) {
  const [cardIdx, setCardIdx] = useState(0);
  const [cardAnswerShown, setCardAnswerShown] = useState(false);
  const [cardWrong, setCardWrong] = useState(0);
  const [cardRight, setCardRight] = useState(0);
  const [generating, setGenerating] = useState<StudioView | null>(null);
  const [generatedResults, setGeneratedResults] = useState<Set<StudioView>>(new Set());
  const [tappedResult, setTappedResult] = useState<StudioView | null>(null);
  const [generateError, setGenerateError] = useState<string | null>(null);

  // Real generated data
  const [realFlashcards, setRealFlashcards] = useState<Flashcard[]>([]);
  const [realSummary, setRealSummary] = useState<string>("");
  const [realMindMap, setRealMindMap] = useState<MindMapData | null>(null);
  const [realQuiz, setRealQuiz] = useState<QuizQuestion[]>([]);

  const setView = onViewChange;
  const setFullscreen = onFullscreenChange;
  const [fsClosing, setFsClosing] = useState(false);

  // Handle tool card click — call real API
  const handleToolSelect = async (v: StudioView) => {
    if (generating) return;
    setGenerating(v);
    setGenerateError(null);

    try {
      // Fetch source text via the notebook query endpoint to get context
      // We use a broad question to retrieve the most content
      const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const queryRes = await fetch(
        notebookId ? `${API_BASE}/notebooks/${notebookId}/query` : `${API_BASE}/query`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question: "summarize all key concepts topics and information", top_k: 20 }),
        }
      );

      let sourceText = "";
      if (queryRes.ok) {
        const qData = await queryRes.json();
        // Use the answer + question as context, or fall back to a placeholder
        sourceText = qData.answer || "";
        // Also append source chunk info if available
        if (qData.sources && qData.sources.length > 0) {
          sourceText = qData.sources.map((s: { citation: string }) => s.citation).join("\n") + "\n\n" + sourceText;
        }
      }

      if (!sourceText || sourceText.length < 20) {
        throw new Error("Not enough source content. Add sources to your notebook first.");
      }

      if (v === "flashcards") {
        const cards = await generateFlashcards(sourceText, 10);
        setRealFlashcards(cards);
      } else if (v === "summary") {
        const result = await generateSummary(sourceText, "medium");
        setRealSummary(result.summary);
      } else if (v === "mindmap") {
        const map = await generateMindMap(sourceText);
        setRealMindMap(map);
      } else if (v === "quiz") {
        const questions = await generateQuiz(sourceText, quizCount, quizDifficulty);
        setRealQuiz(questions);
      }

      setGeneratedResults(prev => new Set(prev).add(v));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setGenerateError(msg);
    } finally {
      setGenerating(null);
    }
  };
  const closeFullscreen = () => {
    setFsClosing(true);
    setTimeout(() => { setFsClosing(false); onFullscreenChange(false); }, 220);
  };
  const toggleFullscreen = () => {
    if (fullscreen) { closeFullscreen(); } else { onFullscreenChange(true); }
  };
  const [quizIdx, setQuizIdx] = useState(0);
  const [quizSelected, setQuizSelected] = useState<number | null>(null);
  const [quizScore, setQuizScore] = useState(0);
  const [quizDone, setQuizDone] = useState(false);
  const [quizStarted, setQuizStarted] = useState(false);
  const [quizDifficulty, setQuizDifficulty] = useState<"easy" | "medium" | "hard" | "mixed">("easy");
  const [quizCount, setQuizCount] = useState(10);
  const [quizCountPreset, setQuizCountPreset] = useState<10 | 20 | 30 | "custom">(10);
  const [quizCustomInput, setQuizCustomInput] = useState("10");

  const card = realFlashcards.length > 0 ? realFlashcards[cardIdx] : { question: CARDS[cardIdx].q, answer: CARDS[cardIdx].a, term: CARDS[cardIdx].term, definition: CARDS[cardIdx].def };
  const front = card.question;
  const back  = card.answer;

  const activeQuiz = realQuiz.length > 0 ? realQuiz : QUIZ;
  const quizQ = activeQuiz[quizIdx];
  const quizCorrect = quizSelected === quizQ?.answer;

  const handleQuizNext = () => {
    const newScore = quizScore + (quizCorrect ? 1 : 0);
    if (quizIdx + 1 >= activeQuiz.length) {
      setQuizScore(newScore);
      setQuizDone(true);
    } else {
      setQuizScore(newScore);
      setQuizIdx(quizIdx + 1);
      setQuizSelected(null);
    }
  };

  const resetQuiz = () => {
    setQuizIdx(0);
    setQuizSelected(null);
    setQuizScore(0);
    setQuizDone(false);
    setQuizStarted(false);
    setQuizCountPreset(10);
    setQuizCount(10);
    setQuizCustomInput("10");
  };

  const TOOLS: { id: StudioView; label: string; sub: string; icon: string }[] = [
    { id: "flashcards", label: "Flashcards", sub: "Auto-generate flashcards from your sources to memorise key terms.",  icon: "M19 3H5a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2V5a2 2 0 00-2-2zM9 9h6M9 13h4" },
    { id: "mindmap",    label: "Mind Map",   sub: "Visualise connections between concepts in your documents.",          icon: "M12 12m-2 0a2 2 0 104 0 2 2 0 10-4 0M5 6a1.5 1.5 0 103 0 1.5 1.5 0 10-3 0M16 6a1.5 1.5 0 103 0 1.5 1.5 0 10-3 0M5 18a1.5 1.5 0 103 0 1.5 1.5 0 10-3 0M16 18a1.5 1.5 0 103 0 1.5 1.5 0 10-3 0M6.5 6.5L10 10M17.5 6.5L14 10M6.5 17.5L10 14M17.5 17.5L14 14" },
    { id: "summary",    label: "Summary",    sub: "Get a concise summary of key concepts from your uploaded material.", icon: "M3 6h18M3 10h14M3 14h10M3 18h7" },
    { id: "quiz",       label: "Quiz",       sub: "Test your knowledge with AI-generated questions from your sources.", icon: "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" },
  ];

  const sidebarContent = (
    <>
      {/* ── Header ── */}
      <div style={{ padding: "0 14px", borderBottom: "1px solid #1a1a1a", display: "flex", alignItems: "center", justifyContent: "space-between", height: 52, flexShrink: 0 }}>
        {view !== "home" ? (
          <button
            onClick={() => { setView("home"); setCardAnswerShown(false); resetQuiz(); setFullscreen(false); }}
            className="back-btn"
            style={{ display: "flex", alignItems: "center", gap: 6, background: "none", border: "none", color: "rgba(140,175,255,0.6)", cursor: "pointer", fontSize: "0.78rem", fontFamily: "inherit", padding: 0, transition: "color 0.15s" }}
          >
            <Icon d="M19 12H5M5 12l7 7M5 12l7-7" size={13} />
            <span style={{ fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase", fontSize: "0.72rem" }}>Studio</span>
          </button>
        ) : (
          <span style={{ fontSize: "0.95rem", fontWeight: 700, color: "rgba(255,255,255,0.85)", letterSpacing: "-0.01em" }}>Studio</span>
        )}

        {/* panel icon */}
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" style={{ opacity: 0.2 }}>
          <rect x="3" y="3" width="18" height="18" rx="2" stroke="currentColor" strokeWidth="1.8" />
          <line x1="15" y1="3" x2="15" y2="21" stroke="currentColor" strokeWidth="1.8" />
        </svg>
      </div>

      {/* ── Body ── */}
      <div style={{ flex: 1, overflowY: (fullscreen && view === "mindmap") || view === "quiz" ? (fullscreen ? "auto" : "hidden") : "auto", padding: 14, display: "flex", flexDirection: "column" }}>
        <div key={view} className="studio-view-enter" style={{ display: "flex", flexDirection: "column", flex: 1 }}>

        {/* ── Home grid ── */}
        {view === "home" && (
          <div className="studio-view-enter" style={{ display: "flex", flexDirection: "column" }}>
            {/* promo banner */}
            <div style={{
              borderRadius: 8,
              background: "#0a0a0a",
              border: "1px solid #1f1f1f",
              padding: "12px",
              marginBottom: 14,
            }}>
              <p style={{ fontSize: "0.78rem", color: "rgba(255,255,255,0.45)", lineHeight: 1.55, margin: 0 }}>
                Generate study materials instantly from your uploaded sources.
              </p>
            </div>

            {/* Tool grid */}
            <ToolGrid tools={TOOLS} onSelect={handleToolSelect} generating={generating} />

            {/* Error message */}
            {generateError && (
              <div style={{ marginTop: 12, padding: "10px 12px", borderRadius: 8, border: "1px solid rgba(239,68,68,0.3)", background: "rgba(239,68,68,0.06)", fontSize: "0.75rem", color: "rgba(252,165,165,0.9)", lineHeight: 1.5 }}>
                {generateError}
              </div>
            )}

            {/* ── Generated result previews ── */}
            {(generatedResults.size > 0 || generating) && (
              <div style={{ marginTop: 16, display: "flex", flexDirection: "column", gap: 8 }}>
                {/* Divider */}
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <div style={{ flex: 1, height: 1, background: "#1a1a1a" }} />
                  <span style={{ fontSize: "0.65rem", fontWeight: 600, color: "rgba(255,255,255,0.25)", letterSpacing: "0.08em", textTransform: "uppercase" }}>Generated</span>
                  <div style={{ flex: 1, height: 1, background: "#1a1a1a" }} />
                </div>

                {/* In-progress skeleton row */}
                {generating && (
                  <div style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    padding: "10px 12px",
                    borderRadius: 8,
                    border: "1px solid #1f1f1f",
                    background: "#0a0a0a",
                    position: "relative",
                    overflow: "hidden",
                  }}>
                    {/* Traveling bar */}
                    <div style={{
                      position: "absolute",
                      top: 0,
                      height: "100%",
                      background: "linear-gradient(90deg, transparent, rgba(140,175,255,0.12), transparent)",
                      borderRadius: 8,
                      animation: "skeletonBar 1.4s cubic-bezier(0.4,0,0.6,1) infinite",
                      pointerEvents: "none",
                    }} />

                    {/* Bottom edge pulse line */}
                    <div style={{
                      position: "absolute",
                      bottom: 0,
                      left: 0,
                      right: 0,
                      height: 1,
                      background: "linear-gradient(90deg, transparent, rgba(140,175,255,0.4), transparent)",
                      animation: "skeletonBar 1.4s cubic-bezier(0.4,0,0.6,1) infinite",
                      pointerEvents: "none",
                    }} />

                    {/* Spinning icon box */}
                    <div style={{ width: 28, height: 28, borderRadius: 7, background: "#111", border: "1px solid #222", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" style={{ animation: "spin 0.9s linear infinite" }}>
                        <circle cx="12" cy="12" r="9" stroke="rgba(255,255,255,0.1)" strokeWidth="2" />
                        <path d="M12 3a9 9 0 019 9" stroke="rgba(140,175,255,0.6)" strokeWidth="2" strokeLinecap="round" />
                      </svg>
                    </div>

                    {/* Label */}
                    <span style={{ fontSize: "0.82rem", fontWeight: 500, color: "rgba(255,255,255,0.35)", flex: 1, animation: "skeletonGlow 1.4s ease-in-out infinite" }}>
                      {generating === "flashcards" ? "Flashcards" : generating === "mindmap" ? "Mind Map" : generating === "summary" ? "Summary" : "Quiz"}
                    </span>

                    {/* Animated dots */}
                    <div style={{ display: "flex", gap: 3, flexShrink: 0 }}>
                      {[0, 1, 2].map(i => (
                        <span key={i} className={`dot dot-${i}`} style={{ width: 4, height: 4, borderRadius: "50%", background: "rgba(140,175,255,0.4)", display: "inline-block" }} />
                      ))}
                    </div>
                  </div>
                )}

                {/* Completed rows */}
                {(["flashcards", "mindmap", "summary", "quiz"] as StudioView[])
                  .filter(v => generatedResults.has(v))
                  .map(result => {
                    const meta: Record<StudioView, { label: string; icon: string }> = {
                      home:       { label: "Home",       icon: "M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z" },
                      flashcards: { label: "Flashcards", icon: "M19 3H5a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2V5a2 2 0 00-2-2zM9 9h6M9 13h4" },
                      mindmap:    { label: "Mind Map",   icon: "M12 12m-2 0a2 2 0 104 0 2 2 0 10-4 0M5 6a1.5 1.5 0 103 0 1.5 1.5 0 10-3 0M16 6a1.5 1.5 0 103 0 1.5 1.5 0 10-3 0M5 18a1.5 1.5 0 103 0 1.5 1.5 0 10-3 0M16 18a1.5 1.5 0 103 0 1.5 1.5 0 10-3 0M6.5 6.5L10 10M17.5 6.5L14 10M6.5 17.5L10 14M17.5 17.5L14 14" },
                      summary:    { label: "Summary",    icon: "M3 6h18M3 10h14M3 14h10M3 18h7" },
                      quiz:       { label: "Quiz",       icon: "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" },
                    };
                    const { label, icon } = meta[result];
                    return (
                      <button
                        key={result}
                        onClick={() => {
                          setTappedResult(result);
                          setTimeout(() => { setTappedResult(null); setView(result); }, 280);
                        }}
                        className="studio-result-enter action-btn"
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 10,
                          padding: "10px 12px",
                          borderRadius: 8,
                          border: `1px solid ${tappedResult === result ? "rgba(91,138,240,0.35)" : "#1f1f1f"}`,
                          background: tappedResult === result ? "rgba(91,138,240,0.08)" : "#0a0a0a",
                          cursor: "pointer",
                          fontFamily: "inherit",
                          transition: "border-color 0.15s, background 0.15s",
                          width: "100%",
                          textAlign: "left",
                          animation: tappedResult === result ? "resultTap 0.28s cubic-bezier(0.22,1,0.36,1) both" : undefined,
                        }}
                      >
                        <div style={{
                          width: 28, height: 28, borderRadius: 7,
                          background: tappedResult === result ? "rgba(91,138,240,0.15)" : "#111",
                          border: `1px solid ${tappedResult === result ? "rgba(91,138,240,0.3)" : "#222"}`,
                          display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
                          color: tappedResult === result ? "rgba(140,175,255,0.9)" : "rgba(255,255,255,0.5)",
                          transition: "background 0.15s, border-color 0.15s, color 0.15s",
                        }}>
                          <Icon d={icon} size={14} />
                        </div>
                        <span style={{ fontSize: "0.82rem", fontWeight: 500, color: tappedResult === result ? "rgba(140,175,255,0.9)" : "rgba(255,255,255,0.7)", flex: 1, transition: "color 0.15s" }}>{label}</span>
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" style={{ opacity: tappedResult === result ? 0.7 : 0.3, flexShrink: 0, transition: "opacity 0.15s, transform 0.15s", transform: tappedResult === result ? "translateX(3px)" : "none" }}>
                          <path d="M5 12h14M13 5l7 7-7 7" stroke={tappedResult === result ? "rgba(140,175,255,0.9)" : "currentColor"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      </button>
                    );
                  })
                }
              </div>
            )}
          </div>
        )}

        {/* ── Flashcards ── */}
        {view === "flashcards" && (
          <div className="studio-view-enter" style={{ display: "flex", flexDirection: "column", gap: 16, ...(fullscreen ? { maxWidth: 680, width: "100%", margin: "0 auto", padding: "32px 0" } : {}) }}>
            {isNew ? (
              <div style={{ borderRadius: 10, border: "1px solid rgba(255,255,255,0.07)", background: "rgba(255,255,255,0.02)", padding: "32px 14px", textAlign: "center" }}>
                <Icon d="M19 3H5a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2V5a2 2 0 00-2-2z" size={28} />
                <p style={{ fontSize: "0.78rem", color: "rgba(255,255,255,0.35)", marginTop: 12, lineHeight: 1.6 }}>
                  Flashcards will be generated once you add sources.
                </p>
              </div>
            ) : (
              <>
                {/* Title */}
                <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
                  <div>
                    <p style={{ fontSize: fullscreen ? "1.6rem" : "1.15rem", fontWeight: 700, color: "rgba(255,255,255,0.88)", margin: "0 0 2px" }}>Flashcards</p>
                    <p style={{ fontSize: fullscreen ? "0.9rem" : "0.78rem", color: "rgba(255,255,255,0.3)", margin: 0 }}>{(realFlashcards.length > 0 ? realFlashcards : CARDS).length} cards</p>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                    <button
                      onClick={() => {
                        const activeCards = realFlashcards.length > 0 ? realFlashcards : CARDS;
                        const lines = activeCards.map((c, i) => `Q${i+1}: ${c.question}\nA: ${c.answer}`).join("\n\n");
                        const blob = new Blob([lines], { type: "text/plain" });
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement("a"); a.href = url; a.download = "flashcards.txt"; a.click(); URL.revokeObjectURL(url);
                      }}
                      title="Download flashcards"
                      style={{ background: "none", border: "none", cursor: "pointer", padding: 4, color: "rgba(255,255,255,0.25)", transition: "color 0.15s", flexShrink: 0, display: "flex" }}
                      className="action-btn"
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/></svg>
                    </button>
                    <button onClick={toggleFullscreen} title={fullscreen ? "Exit fullscreen" : "Fullscreen"} style={{ background: "none", border: "none", cursor: "pointer", padding: 4, color: fullscreen ? "rgba(255,255,255,0.6)" : "rgba(255,255,255,0.25)", transition: "color 0.15s", flexShrink: 0, display: "flex", alignItems: "center" }} className="action-btn">
                      {fullscreen
                        ? <><svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M9 21H3m0 0v-6m0 6l7-7M15 3h6m0 0v6m0-6l-7 7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/></svg></>
                        : <svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M15 3h6m0 0v6m0-6L14 10M9 21H3m0 0v-6m0 6l7-7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/></svg>
                      }
                    </button>
                  </div>
                </div>

                {/* Card */}
                <div style={{
                  borderRadius: 16,
                  border: "1px solid rgba(255,255,255,0.12)",
                  background: "rgba(255,255,255,0.03)",
                  padding: fullscreen ? "44px 40px" : "28px 24px",
                  minHeight: fullscreen ? 360 : 260,
                  display: "flex",
                  flexDirection: "column",
                  gap: 14,
                  position: "relative",
                }}>
                  {/* Counter */}
                  <span style={{ fontSize: fullscreen ? "0.9rem" : "0.78rem", color: "rgba(255,255,255,0.25)" }}>{cardIdx + 1} / {(realFlashcards.length > 0 ? realFlashcards : CARDS).length}</span>

                  {/* Question */}
                  <p style={{ fontSize: fullscreen ? "1.65rem" : "1.25rem", fontWeight: 600, color: "rgba(255,255,255,0.9)", lineHeight: 1.6, margin: 0, flex: 1 }}>
                    {front}
                  </p>

                  {/* Answer (revealed) */}
                  {cardAnswerShown && (
                    <div style={{
                      borderTop: "1px solid rgba(255,255,255,0.1)",
                      paddingTop: fullscreen ? 20 : 14,
                      display: "flex",
                      flexDirection: "column",
                      gap: 8,
                    }}>
                      <span style={{ fontSize: fullscreen ? "0.78rem" : "0.68rem", letterSpacing: "0.1em", textTransform: "uppercase", color: "rgba(255,255,255,0.4)", fontWeight: 700 }}>Answer</span>
                      <p style={{ fontSize: fullscreen ? "1.2rem" : "1rem", color: "rgba(255,255,255,0.8)", lineHeight: 1.65, margin: 0 }}>{back}</p>
                    </div>
                  )}

                  {/* See answer button */}
                  {!cardAnswerShown && (
                    <button
                      onClick={() => setCardAnswerShown(true)}
                      style={{
                        alignSelf: "center",
                        padding: fullscreen ? "11px 36px" : "8px 24px",
                        borderRadius: 20,
                        border: "1px solid rgba(255,255,255,0.12)",
                        background: "rgba(255,255,255,0.04)",
                        backdropFilter: "blur(6px)",
                        color: "rgba(255,255,255,0.45)",
                        fontSize: fullscreen ? "1rem" : "0.85rem",
                        cursor: "pointer",
                        fontFamily: "inherit",
                        transition: "color 0.2s, border-color 0.2s, background 0.2s",
                      }}
                      className="action-btn"
                    >
                      See answer
                    </button>
                  )}
                </div>

                {/* Bottom controls */}
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                  {/* Back */}
                  <button
                    onClick={() => { setCardIdx(i => Math.max(0, i - 1)); setCardAnswerShown(false); }}
                    disabled={cardIdx === 0}
                    style={{ width: fullscreen ? 56 : 44, height: fullscreen ? 56 : 44, borderRadius: "50%", border: "1px solid rgba(255,255,255,0.1)", background: "rgba(255,255,255,0.04)", cursor: cardIdx === 0 ? "not-allowed" : "pointer", display: "flex", alignItems: "center", justifyContent: "center", opacity: cardIdx === 0 ? 0.3 : 1, transition: "opacity 0.15s" }}
                  >
                    <svg width={fullscreen ? 20 : 16} height={fullscreen ? 20 : 16} viewBox="0 0 24 24" fill="none"><path d="M19 12H5M5 12l7 7M5 12l7-7" stroke="#6B9FFF" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" /></svg>
                  </button>

                  {/* Wrong counter */}
                  <button
                    onClick={() => { if (cardAnswerShown) { setCardWrong(w => w + 1); setCardIdx(i => Math.min((realFlashcards.length > 0 ? realFlashcards : CARDS).length - 1, i + 1)); setCardAnswerShown(false); } }}
                    style={{ flex: 1, height: fullscreen ? 56 : 44, borderRadius: 28, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(255,255,255,0.04)", cursor: cardAnswerShown ? "pointer" : "default", display: "flex", alignItems: "center", justifyContent: "center", gap: 6, opacity: cardAnswerShown ? 1 : 0.4, transition: "opacity 0.15s, background 0.15s" }}
                  >
                    <svg width={fullscreen ? 18 : 14} height={fullscreen ? 18 : 14} viewBox="0 0 24 24" fill="none"><path d="M9 21H3m0 0v-6m0 6l7-7M15 3h6m0 0v6m0-6l-7 7" stroke="#F87171" strokeWidth="2.5" strokeLinecap="round" /></svg>
                    <span style={{ fontSize: fullscreen ? "1rem" : "0.82rem", fontWeight: 600, color: "#F87171" }}>{cardWrong}</span>
                  </button>

                  {/* Right counter */}
                  <button
                    onClick={() => { if (cardAnswerShown) { setCardRight(r => r + 1); setCardIdx(i => Math.min((realFlashcards.length > 0 ? realFlashcards : CARDS).length - 1, i + 1)); setCardAnswerShown(false); } }}
                    style={{ flex: 1, height: fullscreen ? 56 : 44, borderRadius: 28, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(255,255,255,0.04)", cursor: cardAnswerShown ? "pointer" : "default", display: "flex", alignItems: "center", justifyContent: "center", gap: 6, opacity: cardAnswerShown ? 1 : 0.4, transition: "opacity 0.15s, background 0.15s" }}
                  >
                    <span style={{ fontSize: fullscreen ? "1rem" : "0.82rem", fontWeight: 600, color: "#4ADE80" }}>{cardRight}</span>
                    <svg width={fullscreen ? 18 : 14} height={fullscreen ? 18 : 14} viewBox="0 0 24 24" fill="none"><path d="M20 6L9 17l-5-5" stroke="#4ADE80" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
                  </button>

                  {/* Forward */}
                  <button
                    onClick={() => { setCardIdx(i => Math.min((realFlashcards.length > 0 ? realFlashcards : CARDS).length - 1, i + 1)); setCardAnswerShown(false); }}
                    disabled={cardIdx === (realFlashcards.length > 0 ? realFlashcards : CARDS).length - 1}
                    style={{ width: fullscreen ? 56 : 44, height: fullscreen ? 56 : 44, borderRadius: "50%", border: "1px solid rgba(255,255,255,0.1)", background: "rgba(255,255,255,0.04)", cursor: cardIdx === (realFlashcards.length > 0 ? realFlashcards : CARDS).length - 1 ? "not-allowed" : "pointer", display: "flex", alignItems: "center", justifyContent: "center", opacity: cardIdx === (realFlashcards.length > 0 ? realFlashcards : CARDS).length - 1 ? 0.3 : 1, transition: "opacity 0.15s" }}
                  >
                    <svg width={fullscreen ? 20 : 16} height={fullscreen ? 20 : 16} viewBox="0 0 24 24" fill="none"><path d="M5 12h14M13 5l7 7-7 7" stroke="#6B9FFF" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" /></svg>
                  </button>
                </div>

                {/* Score summary */}
                <div style={{ display: "flex", gap: 8 }}>
                  <div style={{ flex: 1, borderRadius: 10, border: "1px solid rgba(248,113,113,0.2)", background: "rgba(248,113,113,0.06)", padding: fullscreen ? "14px 10px" : "8px 10px", textAlign: "center" }}>
                    <p style={{ fontSize: fullscreen ? "1.4rem" : "1rem", fontWeight: 700, color: "#F87171", margin: "0 0 2px" }}>{cardWrong}</p>
                    <p style={{ fontSize: fullscreen ? "0.75rem" : "0.62rem", color: "rgba(255,255,255,0.3)", margin: 0 }}>Still learning</p>
                  </div>
                  <div style={{ flex: 1, borderRadius: 10, border: "1px solid rgba(74,222,128,0.2)", background: "rgba(74,222,128,0.06)", padding: fullscreen ? "14px 10px" : "8px 10px", textAlign: "center" }}>
                    <p style={{ fontSize: fullscreen ? "1.4rem" : "1rem", fontWeight: 700, color: "#4ADE80", margin: "0 0 2px" }}>{cardRight}</p>
                    <p style={{ fontSize: fullscreen ? "0.75rem" : "0.62rem", color: "rgba(255,255,255,0.3)", margin: 0 }}>Know it</p>
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        {/* ── Mind Map ── */}
        {view === "mindmap" && (
          isNew ? (
            <div className="studio-view-enter" style={{ borderRadius: 10, border: "1px solid rgba(255,255,255,0.07)", background: "rgba(255,255,255,0.02)", padding: "32px 14px", textAlign: "center" }}>
              <Icon d="M12 12m-2 0a2 2 0 104 0 2 2 0 10-4 0" size={28} />
              <p style={{ fontSize: "0.78rem", color: "rgba(255,255,255,0.35)", marginTop: 12, lineHeight: 1.6 }}>
                Add sources to visualise your mind map.
              </p>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 10, height: fullscreen ? "100%" : "auto" }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <span style={{ fontSize: "0.68rem", fontWeight: 600, color: "rgba(255,255,255,0.4)", textTransform: "uppercase", letterSpacing: "0.08em" }}>Mind Map</span>
                <button onClick={toggleFullscreen} title={fullscreen ? "Exit fullscreen" : "Fullscreen"} style={{ background: "none", border: "none", cursor: "pointer", padding: 4, color: fullscreen ? "rgba(255,255,255,0.6)" : "rgba(255,255,255,0.25)", transition: "color 0.15s", display: "flex", alignItems: "center" }} className="action-btn">
                  {fullscreen
                    ? <><svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M9 21H3m0 0v-6m0 6l7-7M15 3h6m0 0v6m0-6l-7 7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/></svg></>
                    : <svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M15 3h6m0 0v6m0-6L14 10M9 21H3m0 0v-6m0 6l7-7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/></svg>
                  }
                </button>
              </div>
              <MindMap fullscreen={fullscreen} data={realMindMap || undefined} />
            </div>
          )
        )}

        {/* ── Summary ── */}
        {view === "summary" && (
          <div className="studio-view-enter" style={{ borderRadius: 10, border: "1px solid rgba(255,255,255,0.07)", background: "rgba(255,255,255,0.02)", padding: "16px 14px" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
              <p style={{ fontSize: "0.68rem", fontWeight: 600, color: "rgba(255,255,255,0.4)", textTransform: "uppercase", letterSpacing: "0.08em", margin: 0 }}>Key Concepts</p>
              {!isNew && (
                <button onClick={toggleFullscreen} title={fullscreen ? "Exit fullscreen" : "Fullscreen"} style={{ background: "none", border: "none", cursor: "pointer", padding: 4, color: fullscreen ? "rgba(255,255,255,0.6)" : "rgba(255,255,255,0.25)", transition: "color 0.15s", display: "flex", alignItems: "center" }} className="action-btn">
                  {fullscreen
                    ? <><svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M9 21H3m0 0v-6m0 6l7-7M15 3h6m0 0v6m0-6l-7 7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/></svg></>
                    : <svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M15 3h6m0 0v6m0-6L14 10M9 21H3m0 0v-6m0 6l7-7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/></svg>
                  }
                </button>
              )}
            </div>
            {isNew ? (
              <p style={{ fontSize: "0.8rem", color: "rgba(255,255,255,0.35)", lineHeight: 1.75, margin: 0, textAlign: "center", padding: "10px 0" }}>
                No sources available to summarise.
              </p>
            ) : (
              <p style={{ fontSize: "0.8rem", color: "rgba(255,255,255,0.65)", lineHeight: 1.75, margin: 0, whiteSpace: "pre-wrap" }}>
                {realSummary || "Click the Summary button on the home screen to generate a summary from your sources."}
              </p>
            )}
          </div>
        )}

        {/* ── Quiz ── */}
        {view === "quiz" && (
          <div style={{ display: "flex", flexDirection: "column", height: "100%", gap: 0 }}>
            {isNew ? (
              <div style={{ borderRadius: 10, border: "1px solid rgba(255,255,255,0.07)", background: "rgba(255,255,255,0.02)", padding: "32px 14px", textAlign: "center" }}>
                <Icon d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" size={28} />
                <p style={{ fontSize: "0.78rem", color: "rgba(255,255,255,0.35)", marginTop: 12, lineHeight: 1.6 }}>
                  Quiz will be generated once you add sources.
                </p>
              </div>

            ) : !quizStarted ? (
              /* ── Setup screen ── */
              <div style={{ display: "flex", flexDirection: "column", gap: 24, ...(fullscreen ? { maxWidth: 640, width: "100%", margin: "0 auto", padding: "40px 0" } : {}) }}>

                {/* Header */}
                <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
                  <div>
                    <p style={{ fontSize: fullscreen ? "1.9rem" : "1.3rem", fontWeight: 700, color: "rgba(255,255,255,0.92)", margin: "0 0 4px" }}>Quiz</p>
                    <p style={{ fontSize: fullscreen ? "0.9rem" : "0.75rem", color: "rgba(255,255,255,0.3)", margin: 0 }}>Customise your quiz before starting</p>
                  </div>
                  <button onClick={toggleFullscreen} title={fullscreen ? "Exit fullscreen" : "Fullscreen"} style={{ background: "none", border: "none", cursor: "pointer", padding: 4, color: fullscreen ? "rgba(255,255,255,0.6)" : "rgba(255,255,255,0.25)", transition: "color 0.15s", display: "flex", alignItems: "center", marginTop: 2 }} className="action-btn">
                    {fullscreen
                      ? <><svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M9 21H3m0 0v-6m0 6l7-7M15 3h6m0 0v6m0-6l-7 7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/></svg></>
                      : <svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M15 3h6m0 0v6m0-6L14 10M9 21H3m0 0v-6m0 6l7-7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/></svg>
                    }
                  </button>
                </div>

                {/* Difficulty */}
                <div>
                  <p style={{ fontSize: fullscreen ? "0.8rem" : "0.68rem", fontWeight: 600, color: "rgba(255,255,255,0.35)", textTransform: "uppercase", letterSpacing: "0.09em", margin: "0 0 10px" }}>Difficulty</p>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                    {(["easy", "medium", "hard", "mixed"] as const).map(d => {
                      const active = quizDifficulty === d;
                      const colors: Record<string, string> = { easy: "rgba(74,222,128,0.8)", medium: "rgba(251,191,36,0.8)", hard: "rgba(248,113,113,0.8)", mixed: "rgba(255,255,255,0.75)" };
                      const bgs: Record<string, string> = { easy: "rgba(74,222,128,0.08)", medium: "rgba(251,191,36,0.08)", hard: "rgba(248,113,113,0.08)", mixed: "rgba(255,255,255,0.06)" };
                      const borders: Record<string, string> = { easy: "rgba(74,222,128,0.3)", medium: "rgba(251,191,36,0.3)", hard: "rgba(248,113,113,0.3)", mixed: "rgba(255,255,255,0.2)" };
                      return (
                        <button
                          key={d}
                          onClick={() => setQuizDifficulty(d)}
                          className="action-btn"
                          style={{
                            padding: fullscreen ? "16px 12px" : "10px 12px",
                            borderRadius: 12,
                            border: `1px solid ${active ? borders[d] : "rgba(255,255,255,0.08)"}`,
                            background: active ? bgs[d] : "rgba(255,255,255,0.03)",
                            color: active ? colors[d] : "rgba(255,255,255,0.4)",
                            fontSize: fullscreen ? "1rem" : "0.82rem", fontWeight: active ? 600 : 400,
                            cursor: "pointer", fontFamily: "inherit",
                            transition: "all 0.15s",
                            textTransform: "capitalize",
                          }}
                        >
                          {d.charAt(0).toUpperCase() + d.slice(1)}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Number of questions */}
                <div>
                  <p style={{ fontSize: fullscreen ? "0.8rem" : "0.68rem", fontWeight: 600, color: "rgba(255,255,255,0.35)", textTransform: "uppercase", letterSpacing: "0.09em", margin: "0 0 10px" }}>Questions</p>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 10 }}>
                    {([10, 20, 30, "custom"] as const).map(preset => {
                      const active = quizCountPreset === preset;
                      return (
                        <button
                          key={String(preset)}
                          onClick={() => {
                            setQuizCountPreset(preset);
                            if (preset !== "custom") {
                              setQuizCount(preset);
                              setQuizCustomInput(String(preset));
                            }
                          }}
                          className="action-btn"
                          style={{
                            padding: fullscreen ? "14px 6px" : "9px 6px",
                            borderRadius: 12,
                            border: `1px solid ${active ? "rgba(255,255,255,0.3)" : "rgba(255,255,255,0.08)"}`,
                            background: active ? "rgba(255,255,255,0.1)" : "rgba(255,255,255,0.03)",
                            color: active ? "rgba(255,255,255,0.9)" : "rgba(255,255,255,0.4)",
                            fontSize: fullscreen ? "1rem" : "0.8rem", fontWeight: active ? 700 : 400,
                            cursor: "pointer", fontFamily: "inherit",
                            transition: "all 0.15s",
                            textAlign: "center",
                          }}
                        >
                          {preset === "custom" ? "Custom" : `${preset}`}
                        </button>
                      );
                    })}
                  </div>
                  {quizCountPreset === "custom" && (
                    <div style={{ marginTop: 10, display: "flex", alignItems: "center", gap: 8 }}>
                      <input
                        type="number"
                        min={1}
                        max={50}
                        value={quizCustomInput}
                        onChange={e => {
                          setQuizCustomInput(e.target.value);
                          const n = parseInt(e.target.value);
                          if (!isNaN(n) && n >= 1) setQuizCount(n);
                        }}
                        placeholder="e.g. 15"
                        style={{
                          flex: 1,
                          padding: fullscreen ? "12px 16px" : "8px 12px",
                          borderRadius: 8,
                          border: "1px solid rgba(255,255,255,0.15)",
                          background: "rgba(255,255,255,0.05)",
                          color: "rgba(255,255,255,0.85)",
                          fontSize: fullscreen ? "1rem" : "0.85rem",
                          fontFamily: "inherit",
                          outline: "none",
                        }}
                      />
                      <span style={{ fontSize: "0.72rem", color: "rgba(255,255,255,0.3)", whiteSpace: "nowrap" }}>questions</span>
                    </div>
                  )}
                </div>

                {/* Summary card */}
                <div style={{ borderRadius: 12, border: "1px solid rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.03)", padding: fullscreen ? "20px 24px" : "12px 14px", display: "flex", gap: 16 }}>
                  <div style={{ textAlign: "center", flex: 1 }}>
                    <p style={{ fontSize: fullscreen ? "1.6rem" : "1.1rem", fontWeight: 700, color: "rgba(255,255,255,0.85)", margin: "0 0 4px" }}>{quizCount}</p>
                    <p style={{ fontSize: fullscreen ? "0.78rem" : "0.65rem", color: "rgba(255,255,255,0.3)", margin: 0 }}>Questions</p>
                  </div>
                  <div style={{ width: 1, background: "rgba(255,255,255,0.07)" }} />
                  <div style={{ textAlign: "center", flex: 1 }}>
                    <p style={{ fontSize: fullscreen ? "1.6rem" : "1.1rem", fontWeight: 700, color: "rgba(255,255,255,0.85)", margin: "0 0 4px", textTransform: "capitalize" }}>{quizDifficulty}</p>
                    <p style={{ fontSize: fullscreen ? "0.78rem" : "0.65rem", color: "rgba(255,255,255,0.3)", margin: 0 }}>Difficulty</p>
                  </div>
                  <div style={{ width: 1, background: "rgba(255,255,255,0.07)" }} />
                  <div style={{ textAlign: "center", flex: 1 }}>
                    <p style={{ fontSize: fullscreen ? "1.6rem" : "1.1rem", fontWeight: 700, color: "rgba(255,255,255,0.85)", margin: "0 0 4px" }}>MCQ</p>
                    <p style={{ fontSize: fullscreen ? "0.78rem" : "0.65rem", color: "rgba(255,255,255,0.3)", margin: 0 }}>Type</p>
                  </div>
                </div>

                {/* Start button */}
                <button
                  onClick={() => setQuizStarted(true)}
                  style={{ padding: fullscreen ? "18px" : "13px", borderRadius: 12, border: "1px solid rgba(255,255,255,0.15)", background: "rgba(255,255,255,0.08)", color: "white", fontSize: fullscreen ? "1.05rem" : "0.92rem", fontWeight: 700, cursor: "pointer", fontFamily: "inherit", transition: "opacity 0.15s" }}
                >
                  Start Quiz →
                </button>
              </div>
            ) : quizDone ? (
              /* ── Results screen ── */
              <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 20, padding: "32px 14px", textAlign: "center", ...(fullscreen ? { maxWidth: 520, width: "100%", margin: "0 auto" } : {}) }}>
                <div style={{ width: fullscreen ? 88 : 64, height: fullscreen ? 88 : 64, borderRadius: "50%", background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.12)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                  <svg width={fullscreen ? 38 : 28} height={fullscreen ? 38 : 28} viewBox="0 0 24 24" fill="none">
                    <path d="M20 6L9 17l-5-5" stroke="rgba(255,255,255,0.7)" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </div>
                <div>
                  <p style={{ fontSize: fullscreen ? "2rem" : "1.3rem", fontWeight: 700, color: "white", margin: "0 0 8px" }}>Quiz Complete</p>
                  <p style={{ fontSize: fullscreen ? "1.05rem" : "0.88rem", color: "rgba(255,255,255,0.4)", margin: 0 }}>
                    You scored <span style={{ color: "rgba(255,255,255,0.9)", fontWeight: 700 }}>{quizScore}</span> out of <span style={{ color: "rgba(255,255,255,0.9)", fontWeight: 700 }}>{activeQuiz.length}</span>
                  </p>
                </div>
                {/* Score bar */}
                <div style={{ width: "100%", maxWidth: fullscreen ? 400 : 280 }}>
                  <div style={{ height: fullscreen ? 10 : 6, borderRadius: 5, background: "rgba(255,255,255,0.07)", overflow: "hidden" }}>
                    <div style={{ height: "100%", width: `${(quizScore / activeQuiz.length) * 100}%`, background: "rgba(255,255,255,0.5)", borderRadius: 5, transition: "width 0.6s ease" }} />
                  </div>
                  <p style={{ fontSize: fullscreen ? "0.85rem" : "0.68rem", color: "rgba(255,255,255,0.25)", marginTop: 8, textAlign: "center" }}>{Math.round((quizScore / activeQuiz.length) * 100)}% correct</p>
                </div>
                <button
                  onClick={resetQuiz}
                  style={{ padding: fullscreen ? "14px 48px" : "10px 28px", borderRadius: 24, border: "1px solid rgba(255,255,255,0.15)", background: "rgba(255,255,255,0.07)", color: "rgba(255,255,255,0.8)", fontSize: fullscreen ? "1rem" : "0.85rem", fontWeight: 600, cursor: "pointer", fontFamily: "inherit", transition: "background 0.15s" }}
                >
                  Retry Quiz
                </button>
              </div>
            ) : (
              /* ── Active question ── */
              <div style={{ flex: 1, display: "flex", flexDirection: "column", ...(fullscreen ? { maxWidth: 720, width: "100%", margin: "0 auto", padding: "32px 0" } : {}) }}>

                {/* Title block */}
                <div style={{ padding: "4px 0 20px", borderBottom: "1px solid rgba(255,255,255,0.06)", marginBottom: 20 }}>
                  <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
                    <div>
                      <p style={{ fontSize: fullscreen ? "1.7rem" : "1.3rem", fontWeight: 700, color: "rgba(255,255,255,0.92)", margin: "0 0 4px" }}>Quiz</p>
                      <p style={{ fontSize: fullscreen ? "0.9rem" : "0.75rem", color: "rgba(255,255,255,0.3)", margin: 0 }}>Based on 3 sources</p>
                    </div>
                    <button onClick={toggleFullscreen} title={fullscreen ? "Exit fullscreen" : "Fullscreen"} style={{ background: "none", border: "none", cursor: "pointer", padding: 4, color: fullscreen ? "rgba(255,255,255,0.6)" : "rgba(255,255,255,0.25)", transition: "color 0.15s", display: "flex", alignItems: "center", marginTop: 2 }} className="action-btn">
                      {fullscreen
                        ? <><svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M9 21H3m0 0v-6m0 6l7-7M15 3h6m0 0v6m0-6l-7 7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/></svg></>
                        : <svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M15 3h6m0 0v6m0-6L14 10M9 21H3m0 0v-6m0 6l7-7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/></svg>
                      }
                    </button>
                  </div>
                </div>

                {/* Counter row */}
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: fullscreen ? 24 : 16 }}>
                  <span style={{ fontSize: fullscreen ? "1rem" : "0.82rem", color: "rgba(255,255,255,0.35)", fontWeight: 500 }}>{quizIdx + 1} / {activeQuiz.length}</span>
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" style={{ opacity: 0.25 }}>
                    <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                </div>

                {/* Question text */}
                <p style={{ fontSize: fullscreen ? "1.35rem" : "1.05rem", fontWeight: 700, color: "rgba(255,255,255,0.9)", lineHeight: 1.65, margin: `0 0 ${fullscreen ? 36 : 28}px` }}>
                  {quizQ.q}
                </p>

                {/* Options */}
                <div style={{ display: "flex", flexDirection: "column", gap: fullscreen ? 14 : 10, flex: 1 }}>
                  {quizQ.options.map((opt, i) => {
                    const isSelected = quizSelected === i;
                    const isAnswer = i === quizQ.answer;
                    const revealed = quizSelected !== null;

                    let bg = "rgba(255,255,255,0.04)";
                    let border = "rgba(255,255,255,0.09)";
                    let labelColor = "rgba(255,255,255,0.55)";
                    let textColor = "rgba(255,255,255,0.75)";

                    if (revealed && isAnswer) {
                      bg = "rgba(34,197,94,0.08)"; border = "rgba(34,197,94,0.35)";
                      labelColor = "rgba(134,239,172,0.8)"; textColor = "rgba(134,239,172,0.95)";
                    } else if (revealed && isSelected && !isAnswer) {
                      bg = "rgba(239,68,68,0.08)"; border = "rgba(239,68,68,0.35)";
                      labelColor = "rgba(252,165,165,0.7)"; textColor = "rgba(252,165,165,0.9)";
                    } else if (isSelected) {
                      bg = "rgba(255,255,255,0.08)"; border = "rgba(255,255,255,0.3)";
                      labelColor = "rgba(255,255,255,0.6)"; textColor = "rgba(255,255,255,0.9)";
                    }

                    return (
                      <button
                        key={i}
                        onClick={() => !revealed && setQuizSelected(i)}
                        className="action-btn"
                        style={{
                          padding: fullscreen ? "18px 20px" : "14px 16px",
                          borderRadius: 12,
                          border: `1px solid ${border}`,
                          background: bg,
                          textAlign: "left",
                          cursor: revealed ? "default" : "pointer",
                          fontFamily: "inherit",
                          transition: "background 0.18s, border-color 0.18s",
                          display: "flex",
                          alignItems: "center",
                          gap: 14,
                        }}
                      >
                        <span style={{ fontSize: fullscreen ? "1rem" : "0.82rem", fontWeight: 600, color: labelColor, minWidth: 24, flexShrink: 0, transition: "color 0.18s" }}>
                          {String.fromCharCode(65 + i)}.
                        </span>
                        <span style={{ fontSize: fullscreen ? "1.05rem" : "0.88rem", color: textColor, lineHeight: 1.5, transition: "color 0.18s" }}>{opt}</span>
                      </button>
                    );
                  })}
                </div>

                {/* Next button */}
                {quizSelected !== null && (
                  <button
                    onClick={handleQuizNext}
                    style={{ marginTop: fullscreen ? 24 : 16, padding: fullscreen ? "16px" : "11px", borderRadius: 12, border: "1px solid rgba(255,255,255,0.15)", background: "rgba(255,255,255,0.08)", color: "white", fontSize: fullscreen ? "1rem" : "0.88rem", fontWeight: 600, cursor: "pointer", fontFamily: "inherit", transition: "opacity 0.15s" }}
                  >
                    {quizIdx + 1 >= activeQuiz.length ? "See Results" : "Next →"}
                  </button>
                )}

                {/* Feedback row */}
                <div style={{ display: "flex", gap: 8, marginTop: fullscreen ? 28 : 20, paddingTop: fullscreen ? 20 : 16, borderTop: "1px solid rgba(255,255,255,0.06)" }}>
                  <button style={{ flex: 1, padding: fullscreen ? "12px 16px" : "9px 12px", borderRadius: 20, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(255,255,255,0.04)", color: "rgba(255,255,255,0.45)", fontSize: fullscreen ? "0.9rem" : "0.78rem", cursor: "pointer", fontFamily: "inherit", display: "flex", alignItems: "center", justifyContent: "center", gap: 7, transition: "background 0.15s, color 0.15s" }} className="action-btn">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none"><path d="M14 9V5a3 3 0 00-3-3l-4 9v11h11.28a2 2 0 002-1.7l1.38-9a2 2 0 00-2-2.3H14zM7 22H4a2 2 0 01-2-2v-7a2 2 0 012-2h3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/></svg>
                    Good content
                  </button>
                  <button style={{ flex: 1, padding: fullscreen ? "12px 16px" : "9px 12px", borderRadius: 20, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(255,255,255,0.04)", color: "rgba(255,255,255,0.45)", fontSize: fullscreen ? "0.9rem" : "0.78rem", cursor: "pointer", fontFamily: "inherit", display: "flex", alignItems: "center", justifyContent: "center", gap: 7, transition: "background 0.15s, color 0.15s" }} className="action-btn">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none"><path d="M10 15v4a3 3 0 003 3l4-9V2H5.72a2 2 0 00-2 1.7l-1.38 9a2 2 0 002 2.3H10zM17 2h2.67A2.31 2.31 0 0122 4v7a2.31 2.31 0 01-2.33 2H17" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/></svg>
                    Bad content
                  </button>
                </div>

              </div>
            )}
          </div>
        )}

      </div>  {/* end keyed animation wrapper */}
      </div>
    </>
  );

  const sidebarWidth = (view === "flashcards" || view === "mindmap" || view === "summary" || view === "quiz") ? 560 : 280;

  return (
    <>
      {/* Always-present sidebar — visible when not fullscreen */}
      <aside style={{ width: sidebarWidth, background: "#0a0a0a", border: "1px solid #1f1f1f", borderRadius: 10, display: fullscreen ? "none" : "flex", flexDirection: "column", overflow: "hidden", flexShrink: 0, transition: "width 0.2s ease" }}>
        {sidebarContent}
      </aside>

      {/* Fullscreen overlay — rendered on top when active */}
      {(fullscreen || fsClosing) && (
        <div
          className={fsClosing ? "fs-overlay-exit" : "fs-overlay-enter"}
          style={{
            position: "fixed", inset: 0, zIndex: 200,
            background: "#000",
            display: "flex", alignItems: "stretch", justifyContent: "stretch",
          }}
          onClick={closeFullscreen}
        >
          <div
            className={fsClosing ? "fs-panel-exit" : "fs-panel-enter"}
            onClick={e => e.stopPropagation()}
            style={{
              flex: 1,
              background: "#000",
              borderLeft: "1px solid #1a1a1a",
              display: "flex",
              flexDirection: "column",
              overflow: "hidden",
              fontFamily: "var(--font-inria), 'Inria Sans', sans-serif",
            }}
          >
            {sidebarContent}
          </div>
        </div>
      )}
    </>
  );
}

/* ─── Source Upload Modal ─── */
function SourceUploadModal({
  onClose,
  onUploadFiles,
  onPasteText,
}: {
  onClose: () => void;
  onUploadFiles: (files: File[]) => void;
  onPasteText: (text: string) => void;
}) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [pasteMode, setPasteMode] = useState(false);
  const [pasteText, setPasteText] = useState("");

  const handleFiles = (files: FileList | null) => {
    if (!files || files.length === 0) return;
    onUploadFiles(Array.from(files));
    onClose();
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    handleFiles(e.dataTransfer.files);
  };

  const handlePasteSubmit = () => {
    if (!pasteText.trim()) return;
    onPasteText(pasteText.trim());
    onClose();
  };

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, zIndex: 100,
        background: "rgba(0,0,0,0.35)",
        backdropFilter: "blur(2px)",
        display: "flex", alignItems: "center", justifyContent: "center",
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          width: 460,
          background: "#0a0a0a",
          border: "1px solid #222",
          borderRadius: 12,
          padding: "24px 24px 20px",
          boxShadow: "0 24px 60px rgba(0,0,0,0.6)",
          display: "flex",
          flexDirection: "column",
          gap: 18,
        }}
      >
        {/* Header */}
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
          <div>
            <p style={{ fontSize: "1.05rem", fontWeight: 700, color: "rgba(255,255,255,0.9)", margin: "0 0 4px" }}>Add sources to your notebook</p>
            <p style={{ fontSize: "0.78rem", color: "rgba(255,255,255,0.35)", margin: 0 }}>Sources let MindSync base its responses on your material.</p>
          </div>
          <button
            onClick={onClose}
            style={{ background: "none", border: "none", color: "rgba(255,255,255,0.3)", cursor: "pointer", padding: 4, marginTop: -2, transition: "color 0.15s" }}
            className="back-btn"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
              <path d="M9 21H3m0 0v-6m0 6l7-7M15 3h6m0 0v6m0-6l-7 7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        {/* Drop zone */}
        {!pasteMode ? (
          <div
            onDragOver={e => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            style={{
              border: `1px dashed ${dragging ? "#444" : "#2a2a2a"}`,
              borderRadius: 8,
              padding: "32px 20px",
              textAlign: "center",
              cursor: "pointer",
              background: dragging ? "#111" : "transparent",
              transition: "border-color 0.1s, background 0.1s",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 8,
            }}
          >
            <div style={{ width: 40, height: 40, borderRadius: 8, background: "#111", border: "1px solid #222", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M17 8l-5-5-5 5M12 3v13" stroke="rgba(255,255,255,0.4)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <div>
              <p style={{ fontSize: "0.85rem", fontWeight: 500, color: "rgba(255,255,255,0.65)", margin: "0 0 3px" }}>Drop files here or click to browse</p>
              <p style={{ fontSize: "0.72rem", color: "rgba(255,255,255,0.25)", margin: 0 }}>pdf, images, docs, audio, and more</p>
            </div>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <textarea
              autoFocus
              value={pasteText}
              onChange={e => setPasteText(e.target.value)}
              placeholder="Paste your text here…"
              rows={6}
              style={{
                background: "rgba(255,255,255,0.03)",
                border: "1px solid rgba(255,255,255,0.1)",
                borderRadius: 10,
                padding: "12px 14px",
                color: "rgba(255,255,255,0.8)",
                fontSize: "0.82rem",
                fontFamily: "inherit",
                resize: "vertical",
                outline: "none",
                lineHeight: 1.6,
              }}
            />
            <div style={{ display: "flex", gap: 8 }}>
              <button
                onClick={() => setPasteMode(false)}
                style={{ flex: 1, padding: "9px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.1)", background: "transparent", color: "rgba(255,255,255,0.4)", fontSize: "0.78rem", cursor: "pointer", fontFamily: "inherit" }}
              >
                Back
              </button>
              <button
                onClick={handlePasteSubmit}
                disabled={!pasteText.trim()}
                style={{ flex: 2, padding: "9px", borderRadius: 8, border: "none", background: pasteText.trim() ? "rgba(255,255,255,0.12)" : "rgba(255,255,255,0.07)", color: pasteText.trim() ? "white" : "rgba(255,255,255,0.25)", fontSize: "0.82rem", fontWeight: 600, cursor: pasteText.trim() ? "pointer" : "not-allowed", fontFamily: "inherit" }}
              >
                Add text
              </button>
            </div>
          </div>
        )}

        {/* Action buttons */}
        {!pasteMode && (
          <>
            <input type="file" ref={fileInputRef} style={{ display: "none" }} multiple accept=".pdf,.doc,.docx,.txt,.png,.jpg,.jpeg,.mp3,.mp4" onChange={e => handleFiles(e.target.files)} />
            <div style={{ display: "flex", gap: 10 }}>
              <button
                onClick={() => fileInputRef.current?.click()}
                style={{
                  flex: 1, padding: "10px 14px", borderRadius: 9,
                  border: "1px solid rgba(255,255,255,0.14)",
                  background: "rgba(255,255,255,0.06)",
                  color: "rgba(255,255,255,0.8)",
                  fontSize: "0.82rem", fontWeight: 500, cursor: "pointer", fontFamily: "inherit",
                  display: "flex", alignItems: "center", justifyContent: "center", gap: 7,
                  transition: "background 0.15s",
                }}
                className="action-btn"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                  <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M17 8l-5-5-5 5M12 3v13" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                Upload files
              </button>
              <button
                onClick={() => setPasteMode(true)}
                style={{
                  flex: 1, padding: "10px 14px", borderRadius: 9,
                  border: "1px solid rgba(255,255,255,0.1)",
                  background: "rgba(255,255,255,0.04)",
                  color: "rgba(255,255,255,0.55)",
                  fontSize: "0.82rem", fontWeight: 500, cursor: "pointer", fontFamily: "inherit",
                  display: "flex", alignItems: "center", justifyContent: "center", gap: 7,
                  transition: "background 0.15s",
                }}
                className="action-btn"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                  <path d="M9 12h6M9 16h4M17 3H7a2 2 0 00-2 2v16l3-2 2 2 2-2 2 2 2-2 3 2V5a2 2 0 00-2-2z" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                Copied text
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/* ─── Main Dashboard ─── */
function DashboardInner() {
  const searchParams = useSearchParams();
  const notebookId = searchParams.get("notebook");
  const isNew = !notebookId || searchParams.get("new") === "1";
  const [title, setTitle] = useState(isNew ? "Untitled notebook" : "Loading…");
  const [shareText, setShareText] = useState("Share");
  const [showExport, setShowExport] = useState(false);
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [studioView, setStudioView] = useState<StudioView>("home");
  const [studioFullscreen, setStudioFullscreen] = useState(false);
  const { success: toastSuccess, error: toastError } = useToast();

  /* ─── Lifted sources state ─── */
  const [sources, setSources] = useState<ClientSource[]>([]);
  const prevStatusRef = useRef<Record<string, string>>({});

  const fetchSources = useCallback(async () => {
    if (!notebookId) return;
    try {
      const list = await listSources(notebookId);
      setSources(prev => {
        const optimistic = prev.filter(s => s._isOptimistic);
        const serverIds = new Set(list.map(s => s.id));
        const keep = optimistic.filter(o => !serverIds.has(o.id));
        return [...list, ...keep];
      });
    } catch { /* ignore */ }
  }, [notebookId]);

  useEffect(() => { fetchSources(); }, [fetchSources]);

  useEffect(() => {
    const hasActive = sources.some(s => !isTerminalStatus(s.status) && !s._isOptimistic);
    if (!hasActive) return;
    const interval = setInterval(fetchSources, 2000);
    return () => clearInterval(interval);
  }, [sources, fetchSources]);

  useEffect(() => {
    const prev = prevStatusRef.current;
    for (const s of sources) {
      const oldStatus = prev[s.id];
      if (oldStatus && oldStatus !== s.status) {
        if (s.status === "ready") toastSuccess(`"${s.name}" processed successfully`);
        else if (s.status === "error") toastError(`"${s.name}" failed to process`);
      }
    }
    const next: Record<string, string> = {};
    for (const s of sources) next[s.id] = s.status;
    prevStatusRef.current = next;
  }, [sources, toastSuccess, toastError]);

  /**
   * Upload files with optimistic UI + real progress.
   * Files appear in sidebar immediately and progress bar tracks each stage.
   */
  const handleUploadFiles = useCallback((files: File[]) => {
    if (!notebookId) return;

    const optimistics: ClientSource[] = files.map((file, i) => ({
      id: `temp-${Date.now()}-${i}-${file.name}`,
      notebook_id: notebookId,
      name: file.name,
      source_type: "file",
      status: "uploading",
      error_message: null,
      chunk_count: 0,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      _uploadProgress: 0,
      _isOptimistic: true,
    }));

    setSources(prev => [...prev, ...optimistics]);

    Promise.allSettled(
      files.map(async (file, i) => {
        const tempId = optimistics[i].id;
        try {
          const real = await uploadSourceWithProgress(
            notebookId,
            file,
            (percent) => {
              setSources(prev =>
                prev.map(s => s.id === tempId ? { ...s, _uploadProgress: percent } : s)
              );
            },
          );
          setSources(prev =>
            prev.map(s => s.id === tempId ? { ...real, _isOptimistic: false } : s)
          );
        } catch {
          setSources(prev => prev.filter(s => s.id !== tempId));
          toastError(`Failed to upload "${file.name}"`);
        }
      })
    );
  }, [notebookId, toastError]);

  /**
   * Handle pasted text source — add optimistic entry, submit, then swap.
   */
  const handlePasteText = useCallback(async (text: string) => {
    if (!notebookId) return;
    const tempId = `temp-paste-${Date.now()}`;
    const optimistic: ClientSource = {
      id: tempId,
      notebook_id: notebookId,
      name: "Pasted text",
      source_type: "text",
      status: "uploading",
      error_message: null,
      chunk_count: 0,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      _uploadProgress: 50,
      _isOptimistic: true,
    };
    setSources(prev => [...prev, optimistic]);
    try {
      const real = await addTextSource(notebookId, "Pasted text", text);
      setSources(prev => prev.map(s => s.id === tempId ? { ...real, _isOptimistic: false } : s));
      toastSuccess("Text source added — processing");
    } catch {
      setSources(prev => prev.filter(s => s.id !== tempId));
      toastError("Failed to add text source");
    }
  }, [notebookId, toastSuccess, toastError]);

  const handleDeleteSource = useCallback(async (sourceId: string) => {
    if (!notebookId) return;
    const name = sources.find(s => s.id === sourceId)?.name ?? "Source";
    try {
      await deleteSourceApi(notebookId, sourceId);
      setSources(prev => prev.filter(s => s.id !== sourceId));
      toastSuccess(`"${name}" removed`);
    } catch {
      toastError(`Failed to delete "${name}"`);
    }
  }, [notebookId, sources, toastSuccess, toastError]);

  useEffect(() => {
    if (!notebookId) return;
    import("@/lib/api").then(({ getNotebook }) =>
      getNotebook(notebookId).then(nb => setTitle(nb.title)).catch(() => {})
    );
  }, [notebookId]);

  const handleTitleBlur = () => {
    if (notebookId && title.trim()) {
      updateNotebookTitle(notebookId, title.trim())
        .then(() => toastSuccess("Notebook title updated"))
        .catch(() => toastError("Failed to update title"));
    }
  };

  // Escape key closes fullscreen
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setStudioFullscreen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const handleShare = () => {
    navigator.clipboard.writeText(window.location.href);
    setShareText("Copied!");
    setTimeout(() => setShareText("Share"), 2000);
  };

  const handleExport = (format: string) => {
    let base64 = "";
    let mimeType = "";

    if (format === "pdf") {
      base64 = "JVBERi0xLjEKJcKlwrHDqwoKMSAwIG9iago8PAovVHlwZSAvQ2F0YWxvZwovUGFnZXMgMiAwIFIKPj4KZW5kb2JqCgoyIDAgb2JqCjw8Ci9UeXBlIC9QYWdlcwovS2lkcyBbMyAwIFJdCi9Db3VudCAxCj4+CmVuZG9iagoKMyAwIG9iago8PAovVHlwZSAvUGFnZQovUGFyZW50IDIgMCBSCi9NZWRpYUJveCBbMCAwIDYxMiA3OTJdCj4+CmVuZG9iagoKeHJlZgowIDQKMDAwMDAwMDAwMCA2NTUzNSBmIAowMDAwMDAwMDE4IDAwMDAwIG4gCjAwMDAwMDAwNzMgMDAwMDAgbiAKMDAwMDAwMDEyOSAwMDAwMCBuIAp0cmFpbGVyCjw8Ci9TaXplIDQKL1Jvb3QgMSAwIFIKPj4Kc3RhcnR4cmVmCjIzMAolJUVPRgo=";
      mimeType = "application/pdf";
    } else {
      base64 = "UEsDBBQABgAIAAAAIQA+W1M/rgEAABcJAAATAAgCW0NvbnRlbnRfVHlwZXNdLnhtbCCiBAIooAACAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACslE1vozAQhu8r9R8g3xVMSLVKVeVQtZcedtuq/QGOMyEWsI1s0vTf1yaENmmk9lD1xosfn3m/Yy/X2y4zDkLqKOsVGy1yxiC0csqeK/bx+Z7dcqapEEJbpDhhFxr2LefP1y1Z0AEEHajYnNijEPcxHkEwTzHghL6T4jC1uHkMQ1/KjTz/Z32Y5mO+x2C2M+DCIbK1fITjXbANQ1t53/L29+KzM02r0gVjI+25J17pBfK4r0M0a6Xl4Fofl5a7Y0ZOKd48q3Lz0A0t1Iq7rD2x+u9xR2f7/41u68X7s9aOaF6DofXb0v+sL15q0wKtnIfS3C9zI0R06Z+5fUvjU5oX6/d2DfrR+h7MvKk0r7N/zC4A51fob2I9R3o1P01+sR/R4A3t1R8QvDqR3f7rIuEXAAD//wMAUEsDBBQABgAIAAAAIQBCG/RTOAEAAIIEAAALAAgCX3JlbHMvLnJlbHMgogQCKKAAAgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAArJLRSsMwFIbvBd9hyP02b0cR0dlLCd7IjY1eQ5P2QpOmSQy+vRlXqGxrB5vXkPPy/znn5MvNrrNmgzHKqRVsuCqZgdaOKe0VfD1+Ht4zA4nQSmvHFDxwwhZ3d5eP1LKeQuxb2aI2gZOCrSjuaZ7HGIyvVMIGo1+kVByGFjePUfhKruT5V77Pq7rOtB+MOweKlzBlt/O7F8xXQeMv81F3zSppd9E340tqXo42XkK4X+R+oOUi7Eft5Z/7x3F1/Iex3hX0b4h2eJ16k28K814197+gO/xU3wMAAP//AwBQSwMEFAAGAAgAAAAhAKWbTz4CAgAABwcAABwACAF3b3JkL19yZWxzL2RvY3VtZW50LnhtbC5yZWxzIKIEASigAAEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAALSUzW7aMBDH7yv1HSDfvceh0CA1UhVK22OP2+wDnBgL+B/Zk0LTp+/YIRUq2jRA1R58ZuyZ3/yemV2/PNWm+wA21M5Iloc0wUCR1qV2R/LvzcPkCgOFp7W2znEkedDgevH0ZXXzYyvBwXkLrcsQz2QksfVOSZ5gXG8x1h50xR/m1hNnffE1mBvX5V+M+1R1zXp8Nl/tSNDrWvXhQ9Jvg9q17R55P5Z3W2xT+M99f6Lgdzx/Nxyx0H1/cE/9W2Lz54nt/41s/wAIfQ3xJj3Xp6p7v1s+1v7C5HkK6e2W4Ww/rX1Q9A4Qvg2xH3O8N8U/9r8L1L6b5nS6yX7wFwAA//8DAFBLAwQUAAYACAAAACEA2uD49wABAADBBAAAEQAAAHdvcmQvZG9jdW1lbnQueG1spJLNbtswDIDvgT0HQXd5SNO0S8sA02HXw7B2R13vAZqyKZEsmbLjdB097Sjd09hTj213tO1hYCAQ9EeKomhR8e79eSnsgIlaM02L4yzngCjTCi2rQv/+slz95sBRYSRVWDCF/oKdvZ9cXVmzhZlZ4wEAgY6U7RpdS8+G1pY+n0/M2tAaqYfW+rB0kFh47Q0sV6pQoBstYn/SNHHGzT6n//cWzXQy+xT11K22sUOrKDSUlsY9aOQ0cUBZ+b0VpS/oU3wG9DIfA6T9v+jO+/w7e5T/AQXo3mRj+vYgP4i+p15t0fR1Xm0w//vT+xAAAP//AwBQSwEGAQANAAAABv/8//AAAAv/AAQAAAAAAAAAAAAAAAAAAAAAAHdvcmRzdHlsZXMueG1sUEsHBNKxO5oIAAAAHAMAAFBLBgAFAAAAAAAAAAAAAAAAAgAAAAAAAAAAAAEAAAAcAAAAKAUAAFBLBQAFAwAAAAAAAAAAAAAAAgAAAAkAAAAAAAAAAIAFAAAoBQAAAAAA";
      mimeType = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
    }

    try {
      const byteCharacters = atob(base64);
      const byteNumbers = new Array(byteCharacters.length);
      for (let i = 0; i < byteCharacters.length; i++) {
        byteNumbers[i] = byteCharacters.charCodeAt(i);
      }
      const byteArray = new Uint8Array(byteNumbers);
      const blob = new Blob([byteArray], { type: mimeType });
      const url = URL.createObjectURL(blob);

      const element = document.createElement("a");
      element.href = url;
      element.download = `${title.replace(/\s+/g, "_")}.${format}`;
      element.style.display = "none";
      document.body.appendChild(element);

      // Defers click to next tick to avoid React event blocking
      setTimeout(() => {
        element.click();
        document.body.removeChild(element);
        URL.revokeObjectURL(url);
      }, 0);
    } catch (e) {
      console.error("Export failed:", e);
    }

    setShowExport(false);
  };

  // Close dropdown on click outside
  useEffect(() => {
    const handleClick = () => setShowExport(false);
    document.addEventListener("click", handleClick);
    return () => document.removeEventListener("click", handleClick);
  }, []);

  return (
    <div style={{ height: "100vh", display: "flex", flexDirection: "column", background: "#000", color: "white", fontFamily: "var(--font-inria), 'Inria Sans', sans-serif", overflow: "hidden" }}>

      {/* Header */}
      <header style={{ height: 54, background: "#000", borderBottom: "1px solid #1a1a1a", display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 18px", flexShrink: 0, zIndex: 20 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <Link href="/books" style={{ display: "flex", alignItems: "center", gap: 7, color: "rgba(140,175,255,0.6)", textDecoration: "none", fontSize: "0.78rem", transition: "color 0.15s" }} className="back-btn">
            <Icon d="M19 12H5M5 12l7 7M5 12l7-7" size={13} />
            Books
          </Link>
          <span style={{ color: "rgba(255,255,255,0.12)", fontSize: "0.8rem" }}>/</span>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{ width: 24, height: 24, borderRadius: 7, background: "linear-gradient(135deg, rgba(91,138,240,0.25), rgba(91,138,240,0.15))", border: "1px solid rgba(91,138,240,0.28)", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <Icon d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8zM14 2v6h6" size={11} />
            </div>
            <input
              value={title}
              onChange={e => setTitle(e.target.value)}
              onBlur={handleTitleBlur}
              style={{ background: "transparent", border: "none", outline: "none", color: "rgba(255,255,255,0.85)", fontSize: "0.88rem", fontWeight: 600, width: 210, fontFamily: "inherit", letterSpacing: "-0.01em" }}
            />
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          
          {/* Share Button */}
          <button 
            onClick={handleShare}
            className="action-btn" 
            style={{ 
              padding: "5px 13px", 
              borderRadius: 8, 
              border: "1px solid rgba(255,255,255,0.08)", 
              background: shareText === "Copied!" ? "rgba(91,138,240,0.15)" : "rgba(255,255,255,0.04)", 
              color: shareText === "Copied!" ? "rgba(140,175,255,0.9)" : "rgba(255,255,255,0.45)", 
              cursor: "pointer", 
              fontSize: "0.78rem", 
              fontFamily: "inherit", 
              transition: "all 0.15s",
              display: "flex",
              alignItems: "center",
              gap: 6
            }}
          >
            {shareText === "Copied!" ? (
              <Icon d="M5 13l4 4L19 7" size={12} />
            ) : (
              <Icon d="M4 12v8a2 2 0 002 2h12a2 2 0 002-2v-8M16 6l-4-4-4 4M12 2v13" size={12} />
            )}
            {shareText}
          </button>

          {/* Export Dropdown */}
          <div style={{ position: "relative" }} onClick={(e) => e.stopPropagation()}>
            <button 
              onClick={() => setShowExport(!showExport)}
              className="action-btn" 
              style={{ 
                padding: "5px 13px", 
                borderRadius: 8, 
                border: "1px solid rgba(255,255,255,0.08)", 
                background: showExport ? "rgba(255,255,255,0.06)" : "rgba(255,255,255,0.04)", 
                color: showExport ? "rgba(255,255,255,0.8)" : "rgba(255,255,255,0.45)", 
                cursor: "pointer", 
                fontSize: "0.78rem", 
                fontFamily: "inherit", 
                transition: "all 0.15s",
                display: "flex",
                alignItems: "center",
                gap: 6
              }}
            >
              <Icon d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3" size={12} />
              Export
            </button>

            {/* Dropdown Menu */}
            {showExport && (
              <div style={{
                position: "absolute",
                top: "100%",
                right: 0,
                marginTop: 8,
                background: "rgba(14,14,22,0.95)",
                border: "1px solid rgba(255,255,255,0.08)",
                borderRadius: 12,
                padding: "4px",
                width: 148,
                boxShadow: "0 16px 40px rgba(0,0,0,0.6), 0 0 0 1px rgba(91,138,240,0.08)",
                backdropFilter: "blur(16px)",
                zIndex: 50,
                display: "flex",
                flexDirection: "column",
                gap: 2
              }}>
                <button
                  onClick={() => handleExport("pdf")}
                  className="dropdown-item"
                  style={{
                    padding: "8px 10px",
                    background: "transparent",
                    border: "none",
                    color: "rgba(255,255,255,0.7)",
                    fontSize: "0.78rem",
                    textAlign: "left",
                    cursor: "pointer",
                    borderRadius: 8,
                    fontFamily: "inherit",
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    transition: "background 0.15s, color 0.15s"
                  }}
                >
                  <Icon d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8zM14 2v6h6" size={12} />
                  Download PDF
                </button>
                <button
                  onClick={() => handleExport("docx")}
                  className="dropdown-item"
                  style={{
                    padding: "8px 10px",
                    background: "transparent",
                    border: "none",
                    color: "rgba(255,255,255,0.7)",
                    fontSize: "0.78rem",
                    textAlign: "left",
                    cursor: "pointer",
                    borderRadius: 8,
                    fontFamily: "inherit",
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    transition: "background 0.15s, color 0.15s"
                  }}
                >
                  <Icon d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8zM14 2v6h6" size={12} />
                  Download DOCX
                </button>
              </div>
            )}
          </div>

          <div style={{ width: 30, height: 30, borderRadius: "50%", background: "linear-gradient(135deg, #3A6AD4, #5B8AF0)", border: "1.5px solid rgba(91,138,240,0.4)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "0.68rem", fontWeight: 700, color: "white", cursor: "pointer", marginLeft: 4, boxShadow: "0 0 10px rgba(91,138,240,0.3)" }}>U</div>
        </div>
      </header>

      {/* Body */}
      <div style={{ flex: 1, display: "flex", overflow: "hidden", gap: 8, padding: "8px", background: "#000" }}>
        {/* Sources box */}
        <div style={{ display: "flex", flexDirection: "column", flexShrink: 0, border: "1px solid #1f1f1f", borderRadius: 10, overflow: "hidden", background: "#0a0a0a" }}>
          <SourcesSidebar sources={sources} onAdd={() => setShowUploadModal(true)} onDelete={handleDeleteSource} />
        </div>
        {/* Chat box */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", minWidth: 0, border: "1px solid #1f1f1f", borderRadius: 10, background: "#0a0a0a" }}>
          <ChatArea isNew={isNew} notebookId={notebookId} onUploadFiles={handleUploadFiles} />
        </div>
        {/* Studio box */}
        <div style={{ display: "contents" }}>
          <StudioSidebar isNew={isNew} view={studioView} onViewChange={(v) => { setStudioView(v); if (v === "home") setStudioFullscreen(false); }} fullscreen={studioFullscreen} onFullscreenChange={setStudioFullscreen} notebookId={notebookId} />
        </div>
      </div>

      {showUploadModal && notebookId && (
        <SourceUploadModal
          onClose={() => setShowUploadModal(false)}
          onUploadFiles={handleUploadFiles}
          onPasteText={handlePasteText}
        />
      )}
    </div>
  );
}

export default function Dashboard() {
  return (
    <Suspense fallback={<div style={{ height: "100vh", background: "#0D0E14" }} />}>
      <DashboardInner />
    </Suspense>
  );
}










