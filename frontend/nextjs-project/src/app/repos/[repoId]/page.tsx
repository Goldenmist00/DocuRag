"use client";

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  getRepo,
  getRepoContext,
  queryRepo,
  listSessions,
  createSession,
  listNotebooks,
  listRepoFiles,
  getFileContent,
  reindexRepo,
  refreshRepoContext,
  getGitHubStatus,
  getGitHubAuthUrl,
  disconnectGitHub,
  type Repo,
  type RepoContext,
  type AgentSession,
  type RepoQueryResult,
  type RepoFile,
  type FileContent,
  type Notebook,
  type GitHubStatus,
} from "@/lib/api";
import MarkdownAnswer from "@/components/ui/markdown-answer";

/* ── Tiny Icon Helpers ─────────────────────────────────── */

const LANG_COLORS: Record<string, string> = {
  typescript: "#3178c6", javascript: "#f7df1e", python: "#3572a5",
  rust: "#dea584", go: "#00add8", java: "#b07219", ruby: "#701516",
  css: "#563d7c", html: "#e34c26", json: "#292929", yaml: "#cb171e",
  markdown: "#083fa1", shell: "#89e051", sql: "#e38c00",
  dockerfile: "#384d54", toml: "#9c4221",
};

function langColor(lang: string | null): string {
  if (!lang) return "rgba(255,255,255,0.15)";
  return LANG_COLORS[lang.toLowerCase()] || "rgba(255,255,255,0.25)";
}

function fileIcon(name: string) {
  const ext = name.split(".").pop()?.toLowerCase() || "";
  const isConfig = ["json", "yaml", "yml", "toml", "env", "ini", "cfg"].includes(ext);
  const isDoc = ["md", "txt", "rst", "adoc"].includes(ext);
  if (isConfig) return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="rgba(255,255,255,0.3)" strokeWidth="1.5">
      <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  );
  if (isDoc) return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="rgba(255,255,255,0.3)" strokeWidth="1.5">
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
    </svg>
  );
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="rgba(255,255,255,0.3)" strokeWidth="1.5">
      <path strokeLinecap="round" strokeLinejoin="round" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
    </svg>
  );
}

/* ── File Tree Builder ──────────────────────────────────── */

type TreeNode = {
  name: string;
  path: string;
  isDir: boolean;
  children: TreeNode[];
  file?: RepoFile;
};

function buildTree(files: RepoFile[]): TreeNode[] {
  const root: TreeNode = { name: "", path: "", isDir: true, children: [] };
  for (const f of files) {
    const parts = f.path.replace(/\\/g, "/").split("/");
    let node = root;
    for (let i = 0; i < parts.length; i++) {
      const name = parts[i];
      const isLast = i === parts.length - 1;
      const pathSoFar = parts.slice(0, i + 1).join("/");
      let child = node.children.find((c) => c.name === name);
      if (!child) {
        child = { name, path: pathSoFar, isDir: !isLast, children: [], file: isLast ? f : undefined };
        node.children.push(child);
      }
      node = child;
    }
  }
  const sortNodes = (nodes: TreeNode[]) => {
    nodes.sort((a, b) => {
      if (a.isDir !== b.isDir) return a.isDir ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
    nodes.forEach((n) => sortNodes(n.children));
  };
  sortNodes(root.children);
  return root.children;
}

/* ── File Tree Item ─────────────────────────────────────── */

function TreeItem({ node, depth, selected, onSelect }: {
  node: TreeNode;
  depth: number;
  selected: string | null;
  onSelect: (path: string, file?: RepoFile) => void;
}) {
  const [expanded, setExpanded] = useState(depth < 1);
  const [hov, setHov] = useState(false);
  const isSelected = selected === node.path;

  if (node.isDir) {
    return (
      <>
        <div
          onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}
          onClick={() => setExpanded(!expanded)}
          style={{
            display: "flex", alignItems: "center", gap: 4,
            padding: "3px 8px 3px " + (8 + depth * 14) + "px",
            cursor: "pointer", userSelect: "none",
            background: hov ? "rgba(255,255,255,0.04)" : "transparent",
            transition: "background 0.1s",
          }}
        >
          <svg width="10" height="10" fill="none" stroke="rgba(255,255,255,0.3)" viewBox="0 0 24 24"
            style={{ transform: expanded ? "rotate(90deg)" : "none", transition: "transform 0.12s", flexShrink: 0 }}>
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M9 5l7 7-7 7" />
          </svg>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="rgba(255,255,255,0.35)" strokeWidth="1.5" style={{ flexShrink: 0 }}>
            <path strokeLinecap="round" strokeLinejoin="round"
              d={expanded
                ? "M5 19a2 2 0 01-2-2V7a2 2 0 012-2h4l2 2h4a2 2 0 012 2v1M5 19h14a2 2 0 002-2v-5a2 2 0 00-2-2H9a2 2 0 00-2 2v5a2 2 0 01-2 2z"
                : "M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"
              } />
          </svg>
          <span style={{
            fontSize: 12, color: hov ? "rgba(255,255,255,0.8)" : "rgba(255,255,255,0.5)",
            overflow: "hidden", whiteSpace: "nowrap", textOverflow: "ellipsis",
            transition: "color 0.1s",
          }}>
            {node.name}
          </span>
        </div>
        {expanded && node.children.map((c) => (
          <TreeItem key={c.path} node={c} depth={depth + 1} selected={selected} onSelect={onSelect} />
        ))}
      </>
    );
  }

  return (
    <div
      onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}
      onClick={() => onSelect(node.path, node.file)}
      style={{
        display: "flex", alignItems: "center", gap: 6,
        padding: "3px 8px 3px " + (22 + depth * 14) + "px",
        cursor: "pointer", userSelect: "none",
        background: isSelected ? "rgba(255,255,255,0.07)" : hov ? "rgba(255,255,255,0.03)" : "transparent",
        borderLeft: isSelected ? "2px solid rgba(255,255,255,0.4)" : "2px solid transparent",
        transition: "background 0.1s",
      }}
    >
      {fileIcon(node.name)}
      <span style={{
        fontSize: 12,
        color: isSelected ? "#fff" : hov ? "rgba(255,255,255,0.7)" : "rgba(255,255,255,0.45)",
        overflow: "hidden", whiteSpace: "nowrap", textOverflow: "ellipsis",
        transition: "color 0.1s",
      }}>
        {node.name}
      </span>
      {node.file?.language && (
        <div style={{
          width: 6, height: 6, borderRadius: "50%", flexShrink: 0, marginLeft: "auto",
          background: langColor(node.file.language), opacity: 0.6,
        }} />
      )}
    </div>
  );
}

/* ── Phase Labels ───────────────────────────────────────── */

const PHASE_LABELS: Record<string, string> = {
  cloning: "Cloning",
  scanning: "Scanning",
  parsing: "Parsing",
  ingesting: "Analyzing",
  building_graph: "Building graph",
  embedding: "Embedding",
  consolidating: "Consolidating",
  complete: "Complete",
};

/* ── Status Dot ─────────────────────────────────────────── */

function StatusDot({ status, phase }: { status: string; phase?: string }) {
  const isActive = status === "indexing" || status === "consolidating";
  const label = isActive && phase && PHASE_LABELS[phase] ? PHASE_LABELS[phase] : status;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <div style={{
        width: 6, height: 6, borderRadius: "50%",
        background: status === "ready" ? "rgba(255,255,255,0.6)" : status === "failed" ? "rgba(255,80,80,0.6)" : "rgba(255,255,255,0.25)",
        ...(isActive ? { animation: "dotPulse 1.2s ease-in-out infinite" } : {}),
      }} />
      <span style={{
        fontFamily: "var(--font-hero-mono)", fontSize: "0.6rem", fontWeight: 500,
        letterSpacing: "0.12em", textTransform: "uppercase",
        color: status === "failed" ? "rgba(255,80,80,0.5)" : "rgba(255,255,255,0.3)",
      }}>
        {label}
      </span>
    </div>
  );
}

/* ── Progress Bar ──────────────────────────────────────── */

function IndexingProgress({ repo }: { repo: Repo }) {
  const isActive = repo.indexing_status === "indexing" || repo.indexing_status === "consolidating";
  if (!isActive) return null;
  const phase = repo.indexing_phase || "";
  const progress = repo.indexing_progress || 0;
  const detail = repo.indexing_detail || "";
  const phaseLabel = PHASE_LABELS[phase] || phase;

  return (
    <div style={{
      padding: "10px 12px", display: "flex", flexDirection: "column", gap: 6,
      borderBottom: "1px solid #141414",
    }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <div style={{ display: "flex", gap: 3 }}>
            {[0, 1, 2].map((i) => (
              <div key={i} style={{
                width: 3, height: 3, borderRadius: "50%", background: "rgba(255,255,255,0.3)",
                animation: `dotPulse 1.2s ease-in-out ${i * 0.2}s infinite`,
              }} />
            ))}
          </div>
          <span style={{
            fontSize: 10, color: "rgba(255,255,255,0.35)",
            fontFamily: "var(--font-hero-mono)", letterSpacing: "0.08em",
            textTransform: "uppercase", fontWeight: 600,
          }}>
            {phaseLabel}
          </span>
        </div>
        <span style={{
          fontFamily: "var(--font-hero-mono)", fontSize: "0.55rem",
          color: "rgba(255,255,255,0.2)",
        }}>
          {progress > 0 ? `${Math.round(progress)}%` : ""}
        </span>
      </div>
      {progress > 0 && (
        <div style={{
          height: 2, borderRadius: 1,
          background: "rgba(255,255,255,0.06)", overflow: "hidden",
        }}>
          <div style={{
            height: "100%", borderRadius: 1,
            background: "rgba(255,255,255,0.25)",
            width: `${Math.min(progress, 100)}%`,
            transition: "width 0.4s ease-out",
          }} />
        </div>
      )}
      {detail && (
        <span style={{
          fontSize: "0.6rem", color: "rgba(255,255,255,0.18)",
          fontFamily: "var(--font-hero-mono)", letterSpacing: "0.02em",
          overflow: "hidden", whiteSpace: "nowrap", textOverflow: "ellipsis",
        }}>
          {detail}
        </span>
      )}
    </div>
  );
}

/* ── Context Renderer ───────────────────────────────────── */

function ContextValue({ value, depth = 0 }: { value: unknown; depth?: number }) {
  if (value === null || value === undefined) return null;
  if (typeof value === "string") return (
    <span style={{ fontSize: 12, color: "rgba(255,255,255,0.55)", lineHeight: 1.65, wordBreak: "break-word" }}>{value}</span>
  );
  if (typeof value === "number" || typeof value === "boolean") return (
    <span style={{
      fontFamily: "var(--font-hero-mono)", fontSize: "0.72rem",
      color: "rgba(255,255,255,0.5)", padding: "1px 6px", borderRadius: 4,
      background: "rgba(255,255,255,0.04)",
    }}>{String(value)}</span>
  );
  if (Array.isArray(value)) {
    if (value.length === 0) return null;
    if (value.every((v) => typeof v === "string")) {
      return (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
          {value.map((item, i) => (
            <span key={i} style={{
              fontSize: 11, padding: "3px 9px", borderRadius: 4,
              background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.06)",
              color: "rgba(255,255,255,0.5)", lineHeight: 1.5,
            }}>{item as string}</span>
          ))}
        </div>
      );
    }
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {value.map((item, i) => (
          <div key={i} style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
            <span style={{
              fontFamily: "var(--font-hero-mono)", fontSize: "0.6rem",
              color: "rgba(255,255,255,0.15)", marginTop: 3, flexShrink: 0,
              width: 16, textAlign: "right",
            }}>{i + 1}.</span>
            <div style={{ flex: 1, minWidth: 0 }}><ContextValue value={item} depth={depth + 1} /></div>
          </div>
        ))}
      </div>
    );
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as unknown as Record<string, unknown>).filter(
      ([, v]) => v !== null && v !== undefined &&
        !(Array.isArray(v) && v.length === 0) &&
        !(typeof v === "object" && !Array.isArray(v) && Object.keys(v as object).length === 0)
    );
    if (entries.length === 0) return null;
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: depth > 0 ? 6 : 8 }}>
        {entries.map(([key, val]) => {
          const label = key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
          const isNested = typeof val === "object" && val !== null;
          return (
            <div key={key}>
              <div style={{
                fontSize: 11, fontWeight: 600, letterSpacing: "0.04em", textTransform: "uppercase",
                color: depth === 0 ? "rgba(255,255,255,0.35)" : "rgba(255,255,255,0.25)",
                marginBottom: isNested ? 6 : 4,
              }}>{label}</div>
              {isNested ? (
                <div style={{ paddingLeft: depth < 2 ? 12 : 0, borderLeft: depth < 2 ? "1px solid rgba(255,255,255,0.06)" : "none" }}>
                  <ContextValue value={val} depth={depth + 1} />
                </div>
              ) : <ContextValue value={val} depth={depth + 1} />}
            </div>
          );
        })}
      </div>
    );
  }
  return <span style={{ fontSize: 12, color: "rgba(255,255,255,0.4)" }}>{String(value)}</span>;
}

function ContextSection({ label, data }: { label: string; data: unknown }) {
  const [open, setOpen] = useState(true);
  const isEmpty = !data || (typeof data === "object" && Object.keys(data as object).length === 0) ||
    (Array.isArray(data) && data.length === 0);
  if (isEmpty) return null;
  const itemCount = Array.isArray(data) ? data.length : (typeof data === "object" && data ? Object.keys(data).length : 0);

  return (
    <div style={{
      borderRadius: 8, border: open ? "1px solid #252525" : "1px solid #1f1f1f",
      background: "#0a0a0a", overflow: "hidden", transition: "border-color 0.15s",
    }}>
      <button onClick={() => setOpen(!open)} style={{
          width: "100%", padding: "12px 14px", display: "flex", alignItems: "center",
          justifyContent: "space-between", background: "none", border: "none",
          cursor: "pointer", color: "rgba(255,255,255,0.7)", fontFamily: "inherit",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 12, fontWeight: 500, letterSpacing: "-0.01em" }}>{label}</span>
          {itemCount > 0 && (
            <span style={{
              fontFamily: "var(--font-hero-mono)", fontSize: "0.58rem",
              color: "rgba(255,255,255,0.2)", letterSpacing: "0.06em",
            }}>{itemCount}</span>
          )}
        </div>
        <svg width="10" height="10" fill="none" stroke="currentColor" viewBox="0 0 24 24"
          style={{ opacity: 0.3, transform: open ? "rotate(180deg)" : "none", transition: "transform 0.15s" }}>
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {open && (
        <div style={{ padding: "0 14px 14px", maxHeight: 400, overflow: "auto" }}>
          <ContextValue value={data} />
        </div>
      )}
    </div>
  );
}

/* ── Session Row ────────────────────────────────────────── */

function SessionRow({ session, repoId }: { session: AgentSession; repoId: string }) {
  const [hov, setHov] = useState(false);
  const router = useRouter();
  return (
    <div
      onClick={() => router.push(`/repos/${repoId}/sessions/${session.id}`)}
      onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}
      style={{
        padding: "10px 12px", borderRadius: 6, cursor: "pointer",
        border: hov ? "1px solid #333" : "1px solid #1f1f1f",
        background: hov ? "#111" : "#0a0a0a",
        transition: "border-color 0.15s, background 0.15s",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 3 }}>
        <p style={{
          fontSize: 12, fontWeight: 500, margin: 0,
          color: hov ? "#fff" : "rgba(255,255,255,0.7)",
          overflow: "hidden", whiteSpace: "nowrap", textOverflow: "ellipsis",
          maxWidth: "75%", letterSpacing: "-0.01em",
        }}>{session.task_description}</p>
        <span style={{
          fontFamily: "var(--font-hero-mono)", fontSize: "0.55rem", fontWeight: 500,
          letterSpacing: "0.12em", textTransform: "uppercase",
          color: session.status === "completed" ? "rgba(255,255,255,0.5)" : "rgba(255,255,255,0.25)",
        }}>{session.status}</span>
      </div>
      {session.current_step && (
        <p style={{ fontSize: 11, color: "rgba(255,255,255,0.2)", margin: 0, overflow: "hidden", whiteSpace: "nowrap", textOverflow: "ellipsis" }}>
          {session.current_step}
        </p>
      )}
    </div>
  );
}

/* ── Mode Toggle (Ask / Agent) ──────────────────────────── */

function ModeToggle({ mode, onChange }: { mode: "ask" | "agent"; onChange: (m: "ask" | "agent") => void }) {
  return (
    <div style={{
      display: "inline-flex", borderRadius: 6, border: "1px solid #1f1f1f",
      background: "#0a0a0a", overflow: "hidden",
    }}>
      {(["ask", "agent"] as const).map((m) => (
    <button
          key={m}
          onClick={() => onChange(m)}
      style={{
            padding: "6px 16px", border: "none", cursor: "pointer",
            fontFamily: "inherit", fontSize: 12, fontWeight: 500,
            letterSpacing: "0.02em",
            background: mode === m ? "rgba(255,255,255,0.08)" : "transparent",
            color: mode === m ? "#fff" : "rgba(255,255,255,0.3)",
            transition: "all 0.15s",
          }}
        >
          {m === "ask" ? (
            <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <svg width="12" height="12" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01" />
              </svg>
              Ask
            </span>
          ) : (
            <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <svg width="12" height="12" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
              Agent
            </span>
          )}
        </button>
      ))}
    </div>
  );
}

/* ── File Content Viewer ────────────────────────────────── */

function FileViewer({ content, loading, error }: {
  content: FileContent | null;
  loading: boolean;
  error: string | null;
}) {
  if (loading) {
    return (
      <div style={{
        borderRadius: 8, border: "1px solid #1f1f1f", background: "#0a0a0a",
        padding: "24px", display: "flex", alignItems: "center", justifyContent: "center",
      }}>
        <div style={{ display: "flex", gap: 5 }}>
          {[0, 1, 2].map((i) => (
            <div key={i} style={{
              width: 3, height: 3, borderRadius: "50%", background: "rgba(255,255,255,0.3)",
              animation: `dotPulse 1.2s ease-in-out ${i * 0.2}s infinite`,
            }} />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{
        borderRadius: 8, border: "1px solid rgba(255,80,80,0.15)", background: "rgba(255,60,60,0.04)",
        padding: "12px 16px", fontSize: 12, color: "rgba(255,80,80,0.6)",
      }}>
        {error}
      </div>
    );
  }

  if (!content) return null;

  const lines = content.content.split("\n");

  return (
    <div style={{
      borderRadius: 8, border: "1px solid #1f1f1f", background: "#0c0c0c",
      overflow: "hidden",
    }}>
      {content.truncated && (
        <div style={{
          padding: "6px 14px", background: "rgba(255,200,50,0.06)",
          borderBottom: "1px solid rgba(255,200,50,0.1)",
          fontSize: 11, color: "rgba(255,200,50,0.5)",
        }}>
          File truncated — showing first 2 MB of {(content.size_bytes / 1024 / 1024).toFixed(1)} MB
        </div>
      )}
      <div style={{ overflow: "auto", maxHeight: "60vh" }}>
        <table style={{ borderCollapse: "collapse", width: "100%", fontFamily: "var(--font-hero-mono)", fontSize: "0.72rem", lineHeight: 1.65 }}>
          <tbody>
            {lines.map((line, i) => (
              <tr key={i} style={{ background: i % 2 === 0 ? "transparent" : "rgba(255,255,255,0.01)" }}>
                <td style={{
                  padding: "0 12px 0 14px", textAlign: "right", userSelect: "none",
                  color: "rgba(255,255,255,0.12)", whiteSpace: "nowrap",
                  borderRight: "1px solid #1a1a1a", width: 1,
                  verticalAlign: "top",
                }}>
                  {i + 1}
                </td>
                <td style={{
                  padding: "0 14px", color: "rgba(255,255,255,0.55)",
                  whiteSpace: "pre", wordBreak: "keep-all",
                }}>
                  {line || " "}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div style={{
        padding: "5px 14px", borderTop: "1px solid #1a1a1a",
        display: "flex", alignItems: "center", justifyContent: "space-between",
        fontSize: "0.62rem", fontFamily: "var(--font-hero-mono)",
        color: "rgba(255,255,255,0.15)",
      }}>
        <span>{lines.length} lines</span>
        <span>{(content.size_bytes / 1024).toFixed(1)} KB</span>
      </div>
    </div>
  );
}

/* ── Main Page ──────────────────────────────────────────── */

export default function RepoDashboard() {
  const params = useParams();
  const searchParams = useSearchParams();
  const repoId = params.repoId as string;

  const notebookParam = searchParams.get("notebook");
  const modeParam = searchParams.get("mode");

  const [repo, setRepo] = useState<Repo | null>(null);
  const [context, setContext] = useState<RepoContext | null>(null);
  const [files, setFiles] = useState<RepoFile[]>([]);
  const [sessions, setSessions] = useState<AgentSession[]>([]);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [selectedFileData, setSelectedFileData] = useState<RepoFile | null>(null);

  const [mode, setMode] = useState<"ask" | "agent">(modeParam === "agent" ? "agent" : "ask");
  const [question, setQuestion] = useState("");
  const [querying, setQuerying] = useState(false);
  const [queryResult, setQueryResult] = useState<RepoQueryResult | null>(null);

  const [newTask, setNewTask] = useState("");
  const [notebooks, setNotebooks] = useState<Notebook[]>([]);
  const [importNotebook, setImportNotebook] = useState(!!notebookParam);
  const [selectedNotebook, setSelectedNotebook] = useState<string | null>(notebookParam);
  const [nbPickerOpen, setNbPickerOpen] = useState(false);
  const nbPickerRef = useRef<HTMLDivElement>(null);

  const [fileContent, setFileContent] = useState<FileContent | null>(null);
  const [fileContentLoading, setFileContentLoading] = useState(false);
  const [fileContentError, setFileContentError] = useState<string | null>(null);

  const [retrying, setRetrying] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [sidebarTab, setSidebarTab] = useState<"files" | "context">("files");

  const [ghStatus, setGhStatus] = useState<GitHubStatus>({ connected: false });
  useEffect(() => {
    getGitHubStatus().then(setGhStatus).catch(() => {});
    const onFocus = () => { getGitHubStatus().then(setGhStatus).catch(() => {}); };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, []);

  const loadData = useCallback(async () => {
    try {
      const [r, s] = await Promise.all([getRepo(repoId), listSessions(repoId)]);
      setRepo(r);
      setSessions(s);
      if (r.indexing_status === "ready") {
        try { setContext(await getRepoContext(repoId)); } catch { /* */ }
        try { setFiles(await listRepoFiles(repoId)); } catch { /* */ }
      }
    } catch { /* API may not be running */ }
  }, [repoId]);

  useEffect(() => { loadData(); }, [loadData]);
  useEffect(() => {
    if (repo && repo.indexing_status !== "ready" && repo.indexing_status !== "failed") {
      const iv = setInterval(loadData, 1500);
      return () => clearInterval(iv);
    }
  }, [repo, loadData]);
  useEffect(() => { listNotebooks().then(setNotebooks).catch(() => {}); }, []);
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (nbPickerRef.current && !nbPickerRef.current.contains(e.target as Node)) setNbPickerOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const tree = useMemo(() => buildTree(files), [files]);

  useEffect(() => {
    if (!selectedFile || !selectedFileData) {
      setFileContent(null);
      setFileContentError(null);
      return;
    }
    let cancelled = false;
    setFileContentLoading(true);
    setFileContentError(null);
    setFileContent(null);
    getFileContent(repoId, selectedFile)
      .then((fc) => { if (!cancelled) setFileContent(fc); })
      .catch((err) => { if (!cancelled) setFileContentError(err.message || "Failed to load file"); })
      .finally(() => { if (!cancelled) setFileContentLoading(false); });
    return () => { cancelled = true; };
  }, [repoId, selectedFile, selectedFileData]);

  const handleQuery = async () => {
    if (!question.trim()) return;
    setQuerying(true);
    try { setQueryResult(await queryRepo(repoId, question)); } finally { setQuerying(false); }
  };

  const handleRetry = async () => {
    setRetrying(true);
    setRepo((prev) => prev ? {
      ...prev, indexing_status: "indexing", indexing_phase: "scanning",
      indexing_progress: 0, indexing_detail: "Starting…", error_message: null,
    } : prev);
    try { await reindexRepo(repoId); } catch {
      try { await refreshRepoContext(repoId); } catch { /* */ }
    }
    loadData();
    setRetrying(false);
  };

  const handleNewSession = async () => {
    if (!newTask.trim()) return;
    try {
      const nb = importNotebook ? (selectedNotebook || undefined) : undefined;
      await createSession(repoId, newTask, nb);
      setNewTask("");
      setSelectedNotebook(null);
      setImportNotebook(false);
      loadData();
    } catch { /* */ }
  };

  const handleFileSelect = (path: string, file?: RepoFile) => {
    if (path === selectedFile) return;
    setSelectedFile(path);
    setSelectedFileData(file || null);
  };

  const handleFileClose = () => {
    setSelectedFile(null);
    setSelectedFileData(null);
  };

  const selectedNbTitle = selectedNotebook
    ? notebooks.find((n) => n.id === selectedNotebook)?.title || "Notebook"
    : null;

  if (!repo) {
    return (
      <div style={{ minHeight: "100vh", paddingTop: 52, background: "#000", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div style={{ display: "flex", gap: 5 }}>
          {[0, 1, 2].map((i) => (
            <div key={i} style={{
              width: 4, height: 4, borderRadius: "50%", background: "rgba(255,255,255,0.4)",
              animation: `dotPulse 1.2s ease-in-out ${i * 0.2}s infinite`,
            }} />
          ))}
        </div>
      </div>
    );
  }

  const ctxAny = context as unknown as Record<string, unknown> | null;
  const contextSections = context ? [
    { label: "Architecture", data: context.architecture },
    { label: "Tech Stack", data: context.tech_stack },
    { label: "Entry Points", data: ctxAny?.entry_points },
    { label: "File Responsibility Map", data: ctxAny?.file_responsibility_map },
    { label: "API Routes", data: ctxAny?.api_routes },
    { label: "Data Flow", data: ctxAny?.data_flow },
    { label: "Features", data: context.features },
    { label: "API Surface", data: context.api_surface },
    { label: "Dependency Graph", data: context.dependency_graph },
    { label: "Security Findings", data: context.security_findings },
    { label: "Tech Debt", data: context.tech_debt },
    { label: "Test Coverage", data: context.test_coverage },
    { label: "Future Scope", data: context.future_scope },
    { label: "Key Files", data: context.key_files },
  ] : [];

  return (
    <div style={{ height: "calc(100vh - 52px)", marginTop: 52, display: "flex", flexDirection: "column", background: "#000", color: "#fff", fontFamily: "var(--font-inria), 'Inria Sans', sans-serif", overflow: "hidden" }}>

      {/* ── Title Bar ─────────────────────────────────────── */}
      <header style={{
        height: 40, background: "#0a0a0a", borderBottom: "1px solid #1a1a1a",
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "0 12px", flexShrink: 0,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <Link href="/repos" style={{
            fontSize: 11, color: "rgba(255,255,255,0.3)", textDecoration: "none",
            display: "flex", alignItems: "center", gap: 4, transition: "color 0.15s",
        }}>
            <svg width="10" height="10" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
          Repos
        </Link>
          <span style={{ color: "rgba(255,255,255,0.1)", fontSize: 11 }}>/</span>
          <span style={{ fontSize: 12, fontWeight: 500, color: "rgba(255,255,255,0.85)", letterSpacing: "-0.01em" }}>{repo.name}</span>
          <StatusDot status={repo.indexing_status} phase={repo.indexing_phase} />
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          {ghStatus.connected ? (
            <span style={{
              fontSize: 10, color: "rgba(80,255,120,0.5)", display: "flex",
              alignItems: "center", gap: 4, letterSpacing: "0.02em",
            }}>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.374 0 0 5.373 0 12c0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23A11.509 11.509 0 0112 5.803c1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576C20.566 21.797 24 17.3 24 12c0-6.627-5.373-12-12-12z"/></svg>
              @{ghStatus.github_user}
            </span>
          ) : (
            <button
              onClick={async () => { const url = await getGitHubAuthUrl(); window.open(url, "github-auth", "width=600,height=700"); }}
              style={{
                fontSize: 10, color: "rgba(255,255,255,0.3)", background: "none",
                border: "1px solid rgba(255,255,255,0.08)", borderRadius: 4,
                padding: "3px 8px", cursor: "pointer", fontFamily: "inherit",
                display: "flex", alignItems: "center", gap: 4, transition: "all 0.15s",
              }}
            >
              <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.374 0 0 5.373 0 12c0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23A11.509 11.509 0 0112 5.803c1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576C20.566 21.797 24 17.3 24 12c0-6.627-5.373-12-12-12z"/></svg>
              Connect GitHub
            </button>
          )}
        <span style={{
            fontFamily: "var(--font-hero-mono)", fontSize: "0.58rem",
            color: "rgba(255,255,255,0.2)", letterSpacing: "0.08em",
        }}>
          {repo.indexed_files}/{repo.total_files} FILES
          {repo.indexing_status === "indexing" && repo.indexing_phase === "ingesting" && repo.indexing_progress > 0 && (
            <span style={{ marginLeft: 6, color: "rgba(255,255,255,0.3)" }}>
              ({Math.round(repo.indexing_progress)}%)
            </span>
          )}
        </span>
          {repo.indexing_status === "failed" && (
            <button onClick={handleRetry} disabled={retrying} style={{
              display: "flex", alignItems: "center", gap: 5, padding: "4px 10px",
              borderRadius: 4, border: "1px solid rgba(255,80,80,0.2)",
              background: "rgba(255,60,60,0.08)", fontSize: 11, fontWeight: 500,
              color: "rgba(255,80,80,0.7)", cursor: retrying ? "default" : "pointer",
              fontFamily: "inherit", transition: "all 0.15s",
            }}>
              <svg width="10" height="10" fill="none" stroke="currentColor" viewBox="0 0 24 24"
                style={retrying ? { animation: "spin 1s linear infinite" } : {}}>
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M4 4v5h5M20 20v-5h-5M20.49 9A9 9 0 005.64 5.64L4 4m16 16l-1.64-1.64A9 9 0 014.51 15" />
              </svg>
              {retrying ? "Retrying…" : "Retry"}
            </button>
          )}
      </div>
      </header>

      {/* ── Main IDE Layout ───────────────────────────────── */}
      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>

        {/* ── Activity Bar ──────────────────────────────────── */}
        <div style={{
          width: 40, background: "#0a0a0a", borderRight: "1px solid #1a1a1a",
          display: "flex", flexDirection: "column", alignItems: "center", gap: 2,
          paddingTop: 8, flexShrink: 0,
        }}>
          {([
            { id: "files" as const, icon: (
              <svg width="18" height="18" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                  d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
              </svg>
            )},
            { id: "context" as const, icon: (
              <svg width="18" height="18" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                  d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
              </svg>
            )},
          ]).map(({ id, icon }) => (
            <button
              key={id}
              onClick={() => { if (sidebarTab === id && sidebarOpen) setSidebarOpen(false); else { setSidebarTab(id); setSidebarOpen(true); } }}
              style={{
                width: 36, height: 36, display: "flex", alignItems: "center", justifyContent: "center",
                background: "none", border: "none", borderRadius: 4, cursor: "pointer",
                color: sidebarTab === id && sidebarOpen ? "rgba(255,255,255,0.8)" : "rgba(255,255,255,0.25)",
                borderLeft: sidebarTab === id && sidebarOpen ? "2px solid rgba(255,255,255,0.6)" : "2px solid transparent",
                transition: "all 0.15s",
              }}
            >{icon}</button>
          ))}
        </div>

        {/* ── Sidebar (Files / Context) ─────────────────────── */}
        {sidebarOpen && (
          <div style={{
            width: 260, background: "#0a0a0a", borderRight: "1px solid #1a1a1a",
            display: "flex", flexDirection: "column", flexShrink: 0, overflow: "hidden",
          }}>
            <div style={{
              padding: "10px 12px 8px", borderBottom: "1px solid #141414",
              display: "flex", alignItems: "center", justifyContent: "space-between",
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{
                  fontSize: 11, fontWeight: 600, letterSpacing: "0.08em",
                  textTransform: "uppercase", color: "rgba(255,255,255,0.35)",
                }}>
                  {sidebarTab === "files" ? "Explorer" : "Project Context"}
                </span>
                {sidebarTab === "context" && context && (context as unknown as Record<string, unknown>).last_consolidated_at && (
                  <span style={{
                    fontFamily: "var(--font-hero-mono)", fontSize: "0.52rem",
                    color: "rgba(255,255,255,0.15)", letterSpacing: "0.04em",
                  }}>
                    {new Date(String((context as unknown as Record<string, unknown>).last_consolidated_at)).toLocaleDateString()}
                  </span>
                )}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                {sidebarTab === "context" && (
                  <>
                    <button
                      onClick={async () => {
                        setRetrying(true);
                        setRepo((prev) => prev ? {
                          ...prev, indexing_status: "consolidating", indexing_phase: "consolidating",
                          indexing_progress: 0, indexing_detail: "Starting consolidation…",
                        } : prev);
                        try { await refreshRepoContext(repoId); } catch { /* */ }
                        loadData();
                        setRetrying(false);
                      }}
                      disabled={retrying}
                      title="Regenerate Context"
                      style={{
                        background: "none", border: "none", cursor: retrying ? "default" : "pointer",
                        padding: 3, color: "rgba(255,255,255,0.25)", display: "flex",
                        transition: "color 0.15s",
                      }}
                    >
                      <svg width="12" height="12" fill="none" stroke="currentColor" viewBox="0 0 24 24"
                        style={retrying ? { animation: "spin 1s linear infinite" } : {}}>
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                          d="M4 4v5h5M20 20v-5h-5M20.49 9A9 9 0 005.64 5.64L4 4m16 16l-1.64-1.64A9 9 0 014.51 15" />
                      </svg>
                    </button>
                    <button
                      onClick={async () => {
                        setRetrying(true);
                        setRepo((prev) => prev ? {
                          ...prev, indexing_status: "indexing", indexing_phase: "scanning",
                          indexing_progress: 0, indexing_detail: "Starting reindex…",
                        } : prev);
                        try { await reindexRepo(repoId); } catch { /* */ }
                        loadData();
                        setRetrying(false);
                      }}
                      disabled={retrying}
                      title="Full Reindex + Context"
                      style={{
                        background: "none", border: "none", cursor: retrying ? "default" : "pointer",
                        padding: 3, color: "rgba(255,255,255,0.25)", display: "flex",
                        transition: "color 0.15s",
                      }}
                    >
                      <svg width="12" height="12" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                          d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                      </svg>
                    </button>
                  </>
                )}
                <button onClick={() => setSidebarOpen(false)} style={{
                  background: "none", border: "none", cursor: "pointer", padding: 2,
                  color: "rgba(255,255,255,0.2)", display: "flex",
                }}>
                  <svg width="12" height="12" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            </div>

            <div style={{ flex: 1, overflow: "auto", paddingTop: 4, paddingBottom: 8 }}>
              {sidebarTab === "files" ? (
                files.length === 0 ? (
                  <div>
                    {(repo.indexing_status === "indexing" || repo.indexing_status === "consolidating") && (
                      <IndexingProgress repo={repo} />
                    )}
                    <p style={{ fontSize: 11, color: "rgba(255,255,255,0.2)", textAlign: "center", padding: "24px 12px" }}>
                      {repo.indexing_status === "ready" ? "No files indexed" : repo.indexing_status === "failed" ? "Indexing failed" : "Waiting for indexing…"}
                    </p>
                  </div>
                ) : (
                  tree.map((node) => (
                    <TreeItem key={node.path} node={node} depth={0} selected={selectedFile} onSelect={handleFileSelect} />
                  ))
                )
              ) : (
                <>
                  <IndexingProgress repo={repo} />
                  {context ? (
                    <div style={{ padding: "4px 8px", display: "flex", flexDirection: "column", gap: 6 }}>
                      {contextSections.map(({ label, data }) => (
                        <ContextSection key={label} label={label} data={data} />
                      ))}
                    </div>
                  ) : (
                    <p style={{ fontSize: 11, color: "rgba(255,255,255,0.2)", textAlign: "center", padding: "24px 12px" }}>
                      {repo.indexing_status === "ready" ? "No context yet" : repo.indexing_status === "failed" ? "Context generation failed" : "Waiting for indexing…"}
                    </p>
                  )}
                </>
              )}
            </div>
          </div>
        )}

        {/* ── Main Content ──────────────────────────────────── */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>

          {/* ── Tab bar with mode toggle ──────────────────── */}
          <div style={{
            height: 38, background: "#0a0a0a", borderBottom: "1px solid #1a1a1a",
            display: "flex", alignItems: "center", justifyContent: "space-between",
            padding: "0 12px", flexShrink: 0,
          }}>
            <ModeToggle mode={mode} onChange={setMode} />

            {selectedFileData && (
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                {fileIcon(selectedFileData.path)}
                <span style={{
                  fontFamily: "var(--font-hero-mono)", fontSize: "0.7rem",
                  color: "rgba(255,255,255,0.45)",
                }}>
                  {selectedFileData.path}
                </span>
                <button onClick={handleFileClose} style={{
                  background: "none", border: "none", cursor: "pointer", padding: 2,
                  color: "rgba(255,255,255,0.2)", display: "flex",
                }}>
                  <svg width="10" height="10" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
              </div>
            )}
          </div>

          {/* ── Content Area ──────────────────────────────── */}
          <div style={{ flex: 1, overflow: "auto", display: "flex" }}>

            {/* ── Left: interactive panel ──────────────────── */}
            <div style={{ flex: 1, padding: "20px 24px", overflow: "auto" }}>

              {/* File detail card when file selected */}
              {selectedFileData && (
                <div style={{
                  marginBottom: 20, padding: "14px 16px", borderRadius: 8,
                  border: "1px solid #1f1f1f", background: "#0a0a0a",
                }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                    <div style={{ width: 8, height: 8, borderRadius: "50%", background: langColor(selectedFileData.language) }} />
                    <span style={{
                      fontFamily: "var(--font-hero-mono)", fontSize: "0.72rem",
                      color: "rgba(255,255,255,0.5)",
                    }}>
                      {selectedFileData.language || "unknown"}
                    </span>
                    {selectedFileData.importance_score !== null && (
                      <span style={{
                        marginLeft: "auto", fontFamily: "var(--font-hero-mono)",
                        fontSize: "0.65rem", padding: "2px 8px", borderRadius: 4,
                        background: "rgba(255,255,255,0.04)", color: "rgba(255,255,255,0.35)",
                      }}>
                        score {selectedFileData.importance_score}
                      </span>
                    )}
                  </div>
                  {selectedFileData.summary && (
                    <p style={{
                      fontSize: 12, color: "rgba(255,255,255,0.5)", lineHeight: 1.7,
                      margin: 0, whiteSpace: "pre-wrap",
                    }}>
                      {selectedFileData.summary}
                    </p>
                  )}
        </div>
      )}

              {/* File content viewer */}
              {selectedFileData && (
                <div style={{ marginBottom: 20 }}>
                  <FileViewer content={fileContent} loading={fileContentLoading} error={fileContentError} />
                </div>
              )}

              {/* ── ASK MODE ──────────────────────────────── */}
              {mode === "ask" && (
            <div>
              <p style={{
                    fontSize: 11, fontWeight: 600, color: "rgba(255,255,255,0.3)",
                letterSpacing: "0.08em", textTransform: "uppercase", margin: "0 0 10px",
                  }}>Ask about this repository</p>
              <div style={{ display: "flex", gap: 8 }}>
                <input
                  type="text" value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleQuery()}
                  placeholder="How does authentication work?"
                  style={{
                        flex: 1, padding: "10px 14px", borderRadius: 6,
                        background: "#111", border: "1px solid #1f1f1f",
                    outline: "none", color: "#fff", fontSize: 13, fontFamily: "inherit",
                    transition: "border-color 0.15s",
                  }}
                />
                <button
                  onClick={handleQuery}
                  disabled={querying || !question.trim()}
                  style={{
                        padding: "10px 20px", borderRadius: 6, border: "none",
                        background: !question.trim() || querying ? "rgba(255,255,255,0.06)" : "#fff",
                    color: !question.trim() || querying ? "rgba(255,255,255,0.2)" : "#000",
                    fontSize: 12, fontWeight: 600, fontFamily: "inherit",
                    cursor: !question.trim() || querying ? "default" : "pointer",
                    transition: "background 0.15s",
                  }}
                >
                  {querying ? "…" : "Ask"}
                </button>
              </div>

              {queryResult && (
                <div style={{
                      marginTop: 16, padding: "16px", borderRadius: 8,
                  border: "1px solid #1f1f1f", background: "#0a0a0a",
                }}>
                      <MarkdownAnswer content={queryResult.answer} />
                  {queryResult.cited_files.length > 0 && (
                        <div style={{ borderTop: "1px solid #1a1a1a", paddingTop: 12 }}>
                      <span style={{
                            fontFamily: "var(--font-hero-mono)", fontSize: "0.58rem",
                        letterSpacing: "0.15em", textTransform: "uppercase", color: "rgba(255,255,255,0.2)",
                          }}>Cited files</span>
                          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
                        {queryResult.cited_files.map((f) => (
                              <span key={f} onClick={() => handleFileSelect(f)} style={{
                                fontFamily: "var(--font-hero-mono)", fontSize: "0.68rem",
                                padding: "3px 8px", borderRadius: 4, cursor: "pointer",
                            background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.06)",
                                color: "rgba(255,255,255,0.45)", transition: "border-color 0.15s",
                              }}>{f}</span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
              )}

              {/* ── AGENT MODE ────────────────────────────── */}
              {mode === "agent" && (
          <div>
            <p style={{
                    fontSize: 11, fontWeight: 600, color: "rgba(255,255,255,0.3)",
              letterSpacing: "0.08em", textTransform: "uppercase", margin: "0 0 10px",
                  }}>Create agent task</p>

                  <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
                <input
                  type="text" value={newTask}
                  onChange={(e) => setNewTask(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleNewSession()}
                      placeholder="Describe a task for the AI agent…"
                  style={{
                        flex: 1, padding: "10px 14px", borderRadius: 6,
                        background: "#111", border: "1px solid #1f1f1f",
                        outline: "none", color: "#fff", fontSize: 13, fontFamily: "inherit",
                    transition: "border-color 0.15s",
                  }}
                />
                <button
                  onClick={handleNewSession}
                  disabled={!newTask.trim()}
                  style={{
                        padding: "10px 18px", borderRadius: 6, border: "none",
                        background: !newTask.trim() ? "rgba(255,255,255,0.06)" : "#fff",
                    color: !newTask.trim() ? "rgba(255,255,255,0.2)" : "#000",
                    fontSize: 12, fontWeight: 600, fontFamily: "inherit",
                    cursor: !newTask.trim() ? "default" : "pointer",
                        transition: "background 0.15s",
                  }}
                >
                  Start
                </button>
              </div>

                  {/* Notebook import toggle */}
                  <div style={{
                    display: "flex", alignItems: "center", gap: 10,
                    padding: "10px 14px", borderRadius: 6,
                    border: "1px solid #1a1a1a", background: "#0a0a0a",
                    marginBottom: 16,
                  }}>
                    <svg width="14" height="14" fill="none" stroke={importNotebook ? "rgba(255,255,255,0.6)" : "rgba(255,255,255,0.2)"} viewBox="0 0 24 24" style={{ flexShrink: 0, transition: "stroke 0.15s" }}>
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
                        d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
                    </svg>
                    <span style={{
                      flex: 1, fontSize: 12,
                      color: importNotebook ? "rgba(255,255,255,0.6)" : "rgba(255,255,255,0.3)",
                      transition: "color 0.15s",
                    }}>
                      Import notebook context
                    </span>
                    <button
                      onClick={() => { setImportNotebook(!importNotebook); if (importNotebook) { setSelectedNotebook(null); setNbPickerOpen(false); } }}
                      style={{
                        width: 36, height: 20, borderRadius: 10, border: "none", cursor: "pointer",
                        background: importNotebook ? "rgba(255,255,255,0.3)" : "rgba(255,255,255,0.08)",
                        position: "relative", transition: "background 0.2s",
                      }}
                    >
                      <div style={{
                        width: 14, height: 14, borderRadius: "50%", background: "#fff",
                        position: "absolute", top: 3,
                        left: importNotebook ? 19 : 3,
                        transition: "left 0.2s",
                      }} />
                    </button>
                  </div>

                  {importNotebook && (
                    <div ref={nbPickerRef} style={{ position: "relative", marginBottom: 16 }}>
                  <button
                    onClick={() => setNbPickerOpen(!nbPickerOpen)}
                    style={{
                      width: "100%", display: "flex", alignItems: "center", justifyContent: "space-between",
                          padding: "9px 12px", borderRadius: 6, fontFamily: "inherit",
                          background: "#111", border: "1px solid #1f1f1f",
                          color: selectedNotebook ? "rgba(255,255,255,0.7)" : "rgba(255,255,255,0.3)",
                          fontSize: 12, cursor: "pointer", transition: "all 0.15s", textAlign: "left",
                        }}
                      >
                      <span style={{ overflow: "hidden", whiteSpace: "nowrap", textOverflow: "ellipsis" }}>
                          {selectedNbTitle || "Select a notebook…"}
                    </span>
                    <svg width="10" height="10" fill="none" stroke="currentColor" viewBox="0 0 24 24"
                          style={{ opacity: 0.3, transform: nbPickerOpen ? "rotate(180deg)" : "none", transition: "transform 0.15s", flexShrink: 0 }}>
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M19 9l-7 7-7-7" />
                    </svg>
                  </button>
                  {nbPickerOpen && (
                    <div style={{
                      position: "absolute", top: "calc(100% + 4px)", left: 0, right: 0, zIndex: 100,
                      background: "#111", border: "1px solid #222", borderRadius: 8,
                      padding: 4, boxShadow: "0 8px 24px rgba(0,0,0,0.5)",
                      maxHeight: 200, overflowY: "auto",
                    }}>
                      {notebooks.length === 0 ? (
                        <p style={{ fontSize: 11, color: "rgba(255,255,255,0.2)", padding: "12px 10px", margin: 0, textAlign: "center" }}>
                          No notebooks found
                        </p>
                          ) : notebooks.map((nb) => {
                            const isSel = selectedNotebook === nb.id;
                            return (
                              <button
                            key={nb.id}
                            onClick={() => { setSelectedNotebook(nb.id); setNbPickerOpen(false); }}
                                style={{
                                  display: "flex", alignItems: "center", justifyContent: "space-between",
                                  width: "100%", textAlign: "left", gap: 8, background: isSel ? "#1a1a1a" : "none",
                                  border: "none", cursor: "pointer", padding: "7px 10px", fontSize: 11,
                                  borderRadius: 6, fontFamily: "inherit",
                                  color: isSel ? "#fff" : "rgba(255,255,255,0.5)", transition: "all 0.1s",
                                }}
                              >
                                <span style={{ overflow: "hidden", whiteSpace: "nowrap", textOverflow: "ellipsis" }}>{nb.title}</span>
                                <span style={{ fontSize: 10, color: "rgba(255,255,255,0.2)", flexShrink: 0 }}>
                                  {nb.source_count || 0} sources
                                </span>
                              </button>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Sessions list */}
                  <div style={{ marginTop: 8 }}>
                    <p style={{
                      fontSize: 11, fontWeight: 600, color: "rgba(255,255,255,0.25)",
                      letterSpacing: "0.08em", textTransform: "uppercase", margin: "0 0 8px",
                    }}>Sessions</p>
                    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                      {sessions.length === 0 ? (
                        <p style={{ fontSize: 12, color: "rgba(255,255,255,0.15)", textAlign: "center", padding: "24px 0" }}>
                          No sessions yet — describe a task above to start one
                        </p>
                      ) : sessions.map((s) => (
                        <SessionRow key={s.id} session={s} repoId={repoId} />
                      ))}
                </div>
              </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
