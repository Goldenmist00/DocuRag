"use client";

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  getSession,
  getSessionDiff,
  sendSessionMessage,
  commitSession,
  cancelSession,
  retrySession,
  revertSession,
  getSessionCheckpoints,
  restoreCheckpoint,
  createPullRequest,
  stopSession,
  getSessionStreamUrl,
  getGitHubStatus,
  getGitHubAuthUrl,
  disconnectGitHub,
  type AgentSession,
  type SessionDiff,
  type CommitResult,
  type PullRequestResult,
  type Checkpoint,
  type GitHubStatus,
} from "@/lib/api";

/* ================================================================
   Types
   ================================================================ */

type ToolEntry = {
  entry: Record<string, unknown>;
  stepIndex: number;
  checkpointStep: number | null;
};

type TimelineEntry =
  | { kind: "user"; text: string; isInitial: boolean; lastCheckpoint: number | null }
  | { kind: "agent_turn"; tools: ToolEntry[] }
  | { kind: "agent_text"; text: string }
  | { kind: "summary"; text: string }
  | { kind: "retry_separator" };

/* ================================================================
   Timeline builder — groups consecutive tool calls into agent turns
   ================================================================ */

function buildTimeline(session: AgentSession): TimelineEntry[] {
  const items: TimelineEntry[] = [];
  const history = session.conversation_history || [];
  const log = session.agent_log || [];

  items.push({
    kind: "user",
    text: session.task_description,
    isInitial: true,
    lastCheckpoint: null,
  });

  const userFollowUps = history.filter(
    (m) => m.role === "user" && m.content && m.content !== session.task_description
  );
  const assistantTexts = history.filter(
    (m) => m.role === "assistant" && m.content && !m.tool_calls?.length
  );

  const checkpointMap = new Map<number, number>();
  let cpCounter = 0;
  for (let i = 0; i < log.length; i++) {
    const t = (log[i].tool as string) || "";
    if ((t === "edit_file" || t === "write_file" || t === "patch_file") && log[i].success) {
      cpCounter++;
      checkpointMap.set(i, cpCounter);
    }
  }

  let logIdx = 0;
  let userIdx = 0;
  let assistIdx = 0;

  const totalToolCalls = log.length;
  const totalUsers = userFollowUps.length;
  const totalAssist = assistantTexts.length;
  const toolsPerBatch =
    totalUsers > 0 ? Math.ceil(totalToolCalls / (totalUsers + 1)) : totalToolCalls;

  let batchCount = 0;

  while (logIdx < totalToolCalls || userIdx < totalUsers || assistIdx < totalAssist) {
    const turnTools: ToolEntry[] = [];
    while (logIdx < totalToolCalls && batchCount < toolsPerBatch) {
      turnTools.push({
        entry: log[logIdx],
        stepIndex: logIdx,
        checkpointStep: checkpointMap.get(logIdx) ?? null,
      });
      logIdx++;
      batchCount++;
    }

    if (turnTools.length > 0) {
      items.push({ kind: "agent_turn", tools: turnTools });
    }
    batchCount = 0;

    if (assistIdx < totalAssist) {
      items.push({ kind: "agent_text", text: assistantTexts[assistIdx].content! });
      assistIdx++;
    }

    if (userIdx < totalUsers) {
      const content = userFollowUps[userIdx].content!;
      if (content.startsWith("[RETRY]") || content.startsWith("[RERUN]")) {
        items.push({ kind: "retry_separator" });
      } else {
        const latestCp =
          logIdx > 0
            ? Array.from(checkpointMap.entries())
                .filter(([idx]) => idx < logIdx)
                .sort((a, b) => b[1] - a[1])[0]?.[1] ?? null
            : null;
        items.push({ kind: "user", text: content, isInitial: false, lastCheckpoint: latestCp });
      }
      userIdx++;
    }
  }

  if (session.result_summary && (session.status === "completed" || session.status === "failed")) {
    items.push({ kind: "summary", text: session.result_summary });
  }

  return items;
}

/* ================================================================
   Markdown summary renderer
   ================================================================ */

function renderSummaryMarkdown(raw: string, color: string) {
  const lines = raw.split("\n");
  const elements: React.ReactNode[] = [];
  let listBuf: string[] = [];

  const flushList = () => {
    if (!listBuf.length) return;
    elements.push(
      <ul
        key={`ul-${elements.length}`}
        style={{ margin: "4px 0 8px 16px", padding: 0, listStyle: "disc", color }}
      >
        {listBuf.map((l, j) => (
          <li key={j} style={{ fontSize: 12, lineHeight: 1.55, marginBottom: 2 }}>
            {l.replace(/\*\*(.*?)\*\*/g, "$1")}
          </li>
        ))}
      </ul>
    );
    listBuf = [];
  };

  for (const line of lines) {
    if (/^##\s/.test(line)) {
      flushList();
      elements.push(
        <p
          key={`h-${elements.length}`}
          style={{
            fontSize: 11,
            fontWeight: 600,
            letterSpacing: "0.06em",
            textTransform: "uppercase",
            color: "rgba(255,255,255,0.3)",
            margin: elements.length ? "12px 0 4px" : "0 0 4px",
          }}
        >
          {line.replace(/^##\s+/, "")}
        </p>
      );
    } else if (/^[-*]\s/.test(line.trim())) {
      listBuf.push(line.trim().replace(/^[-*]\s+/, ""));
    } else if (line.trim()) {
      flushList();
      elements.push(
        <p key={`p-${elements.length}`} style={{ fontSize: 12, color, margin: "2px 0", lineHeight: 1.55 }}>
          {line}
        </p>
      );
    }
  }
  flushList();
  return <>{elements}</>;
}

/* ================================================================
   Sub-components
   ================================================================ */

function RetrySeparator() {
  return (
    <div className="session-entry" style={{ display: "flex", alignItems: "center", gap: 12, margin: "20px 0" }}>
      <div style={{ flex: 1, height: 1, background: "rgba(255,200,60,0.1)" }} />
      <span
        style={{
          fontFamily: "var(--font-hero-mono)",
          fontSize: 9,
          fontWeight: 600,
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          color: "rgba(255,200,60,0.3)",
        }}
      >
        retried
      </span>
      <div style={{ flex: 1, height: 1, background: "rgba(255,200,60,0.1)" }} />
    </div>
  );
}

/* ── User message bubble ─────────────────────────────── */

function UserMessage({
  text,
  isInitial,
  lastCheckpoint,
  onRetry,
  onEditRetry,
  onRestore,
}: {
  text: string;
  isInitial: boolean;
  lastCheckpoint: number | null;
  onRetry?: () => void;
  onEditRetry?: (editedText: string) => void;
  onRestore?: (step: number) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState(text);

  const handleEditSubmit = () => {
    if (editText.trim() && onEditRetry) {
      onEditRetry(editText.trim());
      setEditing(false);
    }
  };

  const hasActions = !editing && (onRetry || onEditRetry || (onRestore && lastCheckpoint !== null));

  return (
    <div
      className="session-entry session-user-msg"
      style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", margin: "14px 0", gap: 4 }}
    >
      {isInitial && (
        <span
          style={{
            fontSize: 9,
            fontWeight: 600,
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            color: "rgba(255,255,255,0.18)",
            marginBottom: 2,
            marginRight: 2,
          }}
        >
          Task
          </span>
        )}

      <div
        style={{
          maxWidth: "82%",
          padding: "11px 15px",
          borderRadius: "16px 16px 4px 16px",
          background: "rgba(255,255,255,0.065)",
          border: "1px solid rgba(255,255,255,0.06)",
        }}
      >
        {!editing ? (
          <p
            style={{
              fontSize: 13,
              color: "rgba(255,255,255,0.82)",
              margin: 0,
              lineHeight: 1.65,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
            }}
          >
            {text}
          </p>
        ) : (
          <div style={{ minWidth: 300 }}>
            <textarea
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleEditSubmit();
                }
              }}
              className="session-input"
              style={{
                width: "100%",
                minHeight: 72,
                padding: "10px 12px",
                borderRadius: 8,
                background: "#111",
                border: "1px solid #222",
                color: "rgba(255,255,255,0.85)",
                fontSize: 13,
                lineHeight: "1.55",
                resize: "vertical",
                outline: "none",
                fontFamily: "inherit",
                boxSizing: "border-box",
              }}
            />
            <div style={{ display: "flex", gap: 6, marginTop: 8, justifyContent: "flex-end" }}>
              <button
                onClick={() => {
                  setEditing(false);
                  setEditText(text);
                }}
                className="session-btn"
                style={{
                  padding: "5px 14px",
                  borderRadius: 6,
                  border: "1px solid #222",
                  background: "transparent",
                  color: "rgba(255,255,255,0.4)",
                  fontSize: 11,
                  fontFamily: "inherit",
                  cursor: "pointer",
                  transition: "color 0.12s",
                }}
              >
                Cancel
              </button>
              <button
                onClick={handleEditSubmit}
                className="session-btn-primary"
                style={{
                  padding: "5px 14px",
                  borderRadius: 6,
                  border: "none",
                  background: "#fff",
                  color: "#000",
                  fontSize: 11,
                  fontWeight: 600,
                  fontFamily: "inherit",
                  cursor: "pointer",
                  transition: "background 0.12s",
                }}
              >
                Send
              </button>
            </div>
          </div>
        )}
      </div>

      {hasActions && (
        <div
          className="session-hover-actions"
          style={{ display: "flex", gap: 1, alignItems: "center", marginRight: 4 }}
        >
          {onRetry && (
            <button
              onClick={onRetry}
              className="session-btn"
              style={{
                padding: "2px 8px",
                borderRadius: 4,
                border: "none",
                background: "transparent",
                color: "rgba(255,255,255,0.25)",
                fontSize: 10,
                fontFamily: "var(--font-hero-mono)",
                cursor: "pointer",
                transition: "color 0.12s",
              }}
            >
              ↻ Retry
            </button>
          )}
          {onEditRetry && (
            <button
              onClick={() => setEditing(true)}
              className="session-btn"
              style={{
                padding: "2px 8px",
                borderRadius: 4,
                border: "none",
                background: "transparent",
                color: "rgba(255,255,255,0.25)",
                fontSize: 10,
                fontFamily: "var(--font-hero-mono)",
                cursor: "pointer",
                transition: "color 0.12s",
              }}
            >
              Edit
            </button>
          )}
          {onRestore && lastCheckpoint !== null && (
            <button
              onClick={() => onRestore(lastCheckpoint)}
              className="session-btn"
              style={{
                padding: "2px 8px",
                borderRadius: 4,
                border: "none",
                background: "transparent",
                color: "rgba(80,200,255,0.3)",
                fontSize: 10,
                fontFamily: "var(--font-hero-mono)",
                cursor: "pointer",
                transition: "color 0.12s",
              }}
            >
              Restore
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Agent turn block (grouped tool calls) ───────────── */

function AgentTurnBlock({ tools }: { tools: ToolEntry[] }) {
  const [expanded, setExpanded] = useState(false);
  const count = tools.length;
  const uniqueTools = Array.from(new Set(tools.map((t) => (t.entry.tool as string) || "unknown")));
  const allSuccess = tools.every((t) => t.entry.success !== false);
  const failedCount = tools.filter((t) => !t.entry.success && (t.entry.tool as string) !== "done").length;
  const checkpointCount = tools.filter((t) => t.checkpointStep !== null).length;

  return (
    <div
      className="session-entry session-turn"
      style={{
        margin: "8px 0",
        borderRadius: 10,
        border: "1px solid rgba(255,255,255,0.055)",
        background: "rgba(255,255,255,0.015)",
        overflow: "hidden",
        transition: "border-color 0.15s",
      }}
    >
      <button
        onClick={() => setExpanded(!expanded)}
        className="session-turn-header"
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "10px 14px",
          border: "none",
          background: "transparent",
          cursor: "pointer",
          textAlign: "left",
          transition: "background 0.1s",
        }}
      >
        <div
          style={{
            width: 24,
            height: 24,
            borderRadius: 7,
            background: allSuccess ? "rgba(255,255,255,0.05)" : "rgba(255,80,80,0.07)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
            overflow: "hidden",
          }}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/Group 39.svg"
            alt=""
            width={16}
            height={16}
            style={{ opacity: allSuccess ? 0.6 : 0.35 }}
          />
        </div>

        <span
          style={{
            fontFamily: "var(--font-hero-mono)",
            fontSize: 11,
            fontWeight: 600,
            color: "rgba(255,255,255,0.45)",
            letterSpacing: "0.02em",
          }}
        >
          Agent
        </span>

        <span
          style={{
            fontSize: 10,
            color: "rgba(255,255,255,0.2)",
            fontFamily: "var(--font-hero-mono)",
          }}
        >
          {count} action{count !== 1 ? "s" : ""}
        </span>

        {failedCount > 0 && (
          <span
            style={{
              fontSize: 9,
              fontWeight: 600,
              color: "rgba(255,80,80,0.45)",
              fontFamily: "var(--font-hero-mono)",
            }}
          >
            {failedCount} failed
        </span>
        )}

        {checkpointCount > 0 && (
          <span
            style={{
              fontSize: 9,
              color: "rgba(80,200,255,0.3)",
              fontFamily: "var(--font-hero-mono)",
            }}
          >
            {checkpointCount} cp
          </span>
        )}

        <div style={{ flex: 1 }} />

        {!expanded && (
          <div style={{ display: "flex", gap: 6, alignItems: "center", flexShrink: 0, overflow: "hidden" }}>
            {uniqueTools.slice(0, 5).map((name) => (
              <span
                key={name}
                style={{
                  fontSize: 9,
                  fontFamily: "var(--font-hero-mono)",
                  color: "rgba(255,255,255,0.18)",
                  whiteSpace: "nowrap",
                }}
              >
                {name}
              </span>
            ))}
            {uniqueTools.length > 5 && (
              <span style={{ fontSize: 9, color: "rgba(255,255,255,0.12)" }}>+{uniqueTools.length - 5}</span>
            )}
      </div>
        )}

        <svg
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="rgba(255,255,255,0.18)"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{
            transition: "transform 0.15s",
            flexShrink: 0,
            transform: expanded ? "rotate(180deg)" : "rotate(0deg)",
          }}
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      {expanded && (
        <div style={{ padding: "2px 14px 10px", borderTop: "1px solid rgba(255,255,255,0.035)" }}>
          {tools.map(({ entry, stepIndex, checkpointStep }) => {
            const tool = (entry.tool as string) || "unknown";
            const args = (entry.arguments as Record<string, unknown>) || {};
            const success = entry.success as boolean;
            const error = (entry.error as string) || "";
            const output = (entry.output as string) || "";
            const filePath =
              (args.path as string) || (args.pattern as string) || (args.command as string) || "";
            const detail = error || (output.length > 120 ? output.slice(0, 120) + "…" : output);

            return (
              <div
                key={stepIndex}
                className="session-tool-row"
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 10,
                  padding: "7px 6px",
                  borderRadius: 6,
                  transition: "background 0.1s",
                }}
              >
                <div
                  style={{
                    width: 5,
                    height: 5,
                    borderRadius: "50%",
                    marginTop: 6,
                    flexShrink: 0,
                    background: success ? "rgba(80,255,120,0.4)" : "rgba(255,80,80,0.5)",
                  }}
                />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span
                      style={{
                        fontFamily: "var(--font-hero-mono)",
                        fontSize: 11,
                        fontWeight: 500,
                        color: success ? "rgba(255,255,255,0.45)" : "rgba(255,80,80,0.55)",
                      }}
                    >
                      {tool}
                    </span>
                    {checkpointStep !== null && (
                      <span
                        style={{
                          fontSize: 9,
                          fontWeight: 500,
                          color: "rgba(80,200,255,0.35)",
                          fontFamily: "var(--font-hero-mono)",
                          padding: "1px 5px",
                          borderRadius: 3,
                          background: "rgba(80,200,255,0.06)",
                        }}
                      >
                        cp {checkpointStep}
                      </span>
                    )}
                  </div>
                  {filePath && (
                    <p
                      style={{
                        fontFamily: "var(--font-hero-mono)",
                        fontSize: 10,
                        color: "rgba(255,255,255,0.2)",
                        margin: "2px 0 0",
                        overflow: "hidden",
                        whiteSpace: "nowrap",
                        textOverflow: "ellipsis",
                      }}
                    >
                      {filePath}
                    </p>
                  )}
                  {detail && !filePath && (
                    <p
                      style={{
                        fontSize: 10,
                        margin: "2px 0 0",
                        lineHeight: 1.4,
                        color: error ? "rgba(255,80,80,0.4)" : "rgba(255,255,255,0.13)",
                        overflow: "hidden",
                        whiteSpace: "nowrap",
                        textOverflow: "ellipsis",
                      }}
                    >
                      {detail}
                    </p>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/* ── Agent text message ──────────────────────────────── */

function AgentTextMessage({ text }: { text: string }) {
  return (
    <div className="session-entry" style={{ display: "flex", justifyContent: "flex-start", margin: "12px 0" }}>
      <div
        style={{
          maxWidth: "82%",
          padding: "11px 15px",
          borderRadius: "16px 16px 16px 4px",
          background: "rgba(255,255,255,0.02)",
          border: "1px solid rgba(255,255,255,0.05)",
        }}
      >
        <p
          style={{
            fontSize: 13,
            color: "rgba(255,255,255,0.55)",
          margin: 0,
            lineHeight: 1.65,
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}
        >
          {text}
        </p>
      </div>
    </div>
  );
}

/* ── Summary block ───────────────────────────────────── */

function SummaryBlock({ text, failed }: { text: string; failed: boolean }) {
  const hasStructure = text.includes("## ");
  const baseColor = failed ? "rgba(255,80,80,0.55)" : "rgba(255,255,255,0.5)";

  return (
    <div
      className="session-entry"
      style={{
        margin: "16px 0",
        padding: "14px 16px",
        borderRadius: 10,
        background: failed ? "rgba(255,60,60,0.025)" : "rgba(255,255,255,0.018)",
        border: `1px solid ${failed ? "rgba(255,80,80,0.08)" : "rgba(255,255,255,0.055)"}`,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
        <svg
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke={failed ? "rgba(255,80,80,0.4)" : "rgba(80,255,120,0.35)"}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          {failed ? (
            <>
              <circle cx="12" cy="12" r="10" />
              <line x1="15" y1="9" x2="9" y2="15" />
              <line x1="9" y1="9" x2="15" y2="15" />
            </>
          ) : (
            <polyline points="20 6 9 17 4 12" />
          )}
        </svg>
        <span
          style={{
            fontSize: 9,
            fontWeight: 600,
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            color: failed ? "rgba(255,80,80,0.35)" : "rgba(255,255,255,0.22)",
          }}
        >
          {failed ? "Failed" : "Summary"}
        </span>
      </div>
      {hasStructure ? (
        <div style={{ wordBreak: "break-word" }}>{renderSummaryMarkdown(text, baseColor)}</div>
      ) : (
        <p
          style={{
            fontSize: 12.5,
            color: baseColor,
            margin: 0,
            lineHeight: 1.65,
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}
        >
          {text}
        </p>
      )}
    </div>
  );
}

/* ── File accordion for diff viewer ──────────────────── */

function FileAccordion({ file }: { file: SessionDiff["files"][number] }) {
  const [open, setOpen] = useState(false);
  return (
    <div
      style={{
        borderRadius: 6,
        border: "1px solid rgba(255,255,255,0.04)",
        overflow: "hidden",
        marginBottom: 4,
      }}
    >
      <button
        onClick={() => setOpen(!open)}
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "8px 10px",
          border: "none",
          background: open ? "rgba(255,255,255,0.025)" : "transparent",
          cursor: "pointer",
          transition: "background 0.1s",
        }}
      >
        <svg
          width="10"
          height="10"
          viewBox="0 0 24 24"
          fill="none"
          stroke="rgba(255,255,255,0.2)"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ transition: "transform 0.12s", transform: open ? "rotate(90deg)" : "rotate(0deg)" }}
        >
          <polyline points="9 6 15 12 9 18" />
        </svg>
        <span
          style={{
            fontFamily: "var(--font-hero-mono)",
            fontSize: 11,
            color: "rgba(255,255,255,0.5)",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            textAlign: "left",
          }}
        >
          {file.path}
        </span>
        <div style={{ flex: 1 }} />
        {file.insertions > 0 && (
          <span style={{ fontFamily: "var(--font-hero-mono)", fontSize: 10, color: "rgba(80,255,120,0.4)" }}>
            +{file.insertions}
          </span>
        )}
        {file.deletions > 0 && (
          <span style={{ fontFamily: "var(--font-hero-mono)", fontSize: 10, color: "rgba(255,80,80,0.4)" }}>
            -{file.deletions}
          </span>
        )}
      </button>

      {open && file.diff && (
        <pre
          style={{
            margin: 0,
            padding: "10px 12px",
            fontSize: 10,
            lineHeight: 1.6,
            fontFamily: "var(--font-hero-mono)",
            color: "rgba(255,255,255,0.35)",
            overflow: "auto",
            maxHeight: 260,
            borderTop: "1px solid rgba(255,255,255,0.04)",
            background: "rgba(0,0,0,0.25)",
          }}
        >
          {file.diff.split("\n").map((ln, i) => (
            <div
              key={i}
              style={{
                color: ln.startsWith("+")
                  ? "rgba(80,255,120,0.5)"
                  : ln.startsWith("-")
                    ? "rgba(255,80,80,0.5)"
                    : "rgba(255,255,255,0.2)",
              }}
            >
              {ln || " "}
            </div>
          ))}
      </pre>
      )}
    </div>
  );
}

/* ── Diff panel ──────────────────────────────────────── */

function DiffPanel({ diff }: { diff: SessionDiff }) {
  const [showRaw, setShowRaw] = useState(false);
  if (!diff.files?.length) {
    return <p style={{ fontSize: 12, color: "rgba(255,255,255,0.25)", margin: 0 }}>No file changes detected.</p>;
  }
  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
        <span style={{ fontFamily: "var(--font-hero-mono)", fontSize: 10, color: "rgba(255,255,255,0.25)" }}>
          {diff.files.length} file{diff.files.length !== 1 ? "s" : ""}
        </span>
        <button
          onClick={() => setShowRaw(!showRaw)}
          className="session-btn"
          style={{
            fontSize: 9,
            fontFamily: "var(--font-hero-mono)",
            color: "rgba(255,255,255,0.2)",
            background: "transparent",
            border: "none",
            cursor: "pointer",
            transition: "color 0.12s",
          }}
        >
          {showRaw ? "Files" : "Raw"}
        </button>
      </div>

      {showRaw ? (
        <pre
          style={{
            margin: 0,
            padding: 12,
            fontSize: 10,
            lineHeight: 1.6,
            fontFamily: "var(--font-hero-mono)",
            color: "rgba(255,255,255,0.3)",
            overflow: "auto",
            maxHeight: 350,
            borderRadius: 6,
            background: "rgba(0,0,0,0.3)",
            border: "1px solid rgba(255,255,255,0.04)",
          }}
        >
          {diff.raw_diff || "No raw diff available."}
        </pre>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          {diff.files.map((f) => (
            <FileAccordion key={f.path} file={f} />
          ))}
        </div>
      )}
    </div>
  );
}

/* ================================================================
   Main page
   ================================================================ */

export default function SessionPage() {
  const params = useParams();
  const repoId = params.repoId as string;
  const sessionId = params.sessionId as string;

  const [session, setSession] = useState<AgentSession | null>(null);
  const [diff, setDiff] = useState<SessionDiff | null>(null);
  const [loading, setLoading] = useState(true);

  const [followUp, setFollowUp] = useState("");
  const [followFocused, setFollowFocused] = useState(false);
  const [sending, setSending] = useState(false);

  const [commitMsg, setCommitMsg] = useState("");
  const [branchMode, setBranchMode] = useState<"current" | "new">("current");
  const [newBranchName, setNewBranchName] = useState("");
  const [committing, setCommitting] = useState(false);
  const [commitResult, setCommitResult] = useState<CommitResult | null>(null);
  const [commitError, setCommitError] = useState("");

  const [creatingPr, setCreatingPr] = useState(false);
  const [prResult, setPrResult] = useState<PullRequestResult | null>(null);
  const [prError, setPrError] = useState("");
  const [prTitle, setPrTitle] = useState("");
  const [prBody, setPrBody] = useState("");

  const [ghStatus, setGhStatus] = useState<GitHubStatus>({ connected: false });
  const [ghLoading, setGhLoading] = useState(true);

  useEffect(() => {
    getGitHubStatus().then(s => { setGhStatus(s); setGhLoading(false); }).catch(() => setGhLoading(false));
    const onFocus = () => { getGitHubStatus().then(s => setGhStatus(s)).catch(() => {}); };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, []);

  const handleConnectGitHub = () => {
    window.open(getGitHubAuthUrl(), "github-auth", "width=600,height=700");
  };

  const handleDisconnectGitHub = async () => {
    await disconnectGitHub();
    setGhStatus({ connected: false });
  };

  const [userAnswer, setUserAnswer] = useState("");
  const [answerFocused, setAnswerFocused] = useState(false);
  const [answering, setAnswering] = useState(false);

  const [reverting, setReverting] = useState(false);
  const [revertMsg, setRevertMsg] = useState("");
  const [checkpoints, setCheckpoints] = useState<Checkpoint[]>([]);
  const [restoring, setRestoring] = useState(false);

  const [liveActivity, setLiveActivity] = useState<string | null>(null);
  const [stopping, setStopping] = useState(false);

  const chatEndRef = useRef<HTMLDivElement>(null);
  const prevTimelineLenRef = useRef(0);
  const sseRef = useRef<EventSource | null>(null);

  /* ── Fetching ───────────────────────────────────────── */

  const fetchSession = useCallback(async () => {
    try {
      const s = await getSession(repoId, sessionId);
      setSession(s);
      if (s.status === "completed" || s.status === "reviewing" || s.status === "failed") {
        const d = await getSessionDiff(repoId, sessionId);
        setDiff(d);
      }
    } catch {
      /* handled by loading state */
    } finally {
      setLoading(false);
    }
  }, [repoId, sessionId]);

  useEffect(() => {
    fetchSession();
  }, [fetchSession]);

  useEffect(() => {
    if (!session) return;
    const active = ["pending", "running", "awaiting_input"].includes(session.status);
    if (!active) {
      setLiveActivity(null);
      return;
    }

    const url = getSessionStreamUrl(repoId, sessionId);
    const source = new EventSource(url);
    sseRef.current = source;
    let debounceTimer: ReturnType<typeof setTimeout> | null = null;

    source.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data);
        if (data.type === "heartbeat") return;

        if (data.type === "thinking") {
          setLiveActivity(`Thinking (turn ${data.turn || "?"})…`);
        } else if (data.type === "tool_start") {
          const names = (data.tools || []).join(", ");
          setLiveActivity(`Running ${names}…`);
        } else if (data.type === "tool_result") {
          setLiveActivity(data.success ? `${data.tool} ✓` : `${data.tool} ✗`);
        } else if (data.type === "lint_error") {
          setLiveActivity("Lint errors detected");
        } else if (data.type === "done" || data.type === "error" || data.type === "ask_user" || data.type === "stopped") {
          setLiveActivity(null);
          setStopping(false);
          fetchSession();
          source.close();
          return;
        }

        if (debounceTimer) clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => fetchSession(), 800);
      } catch {
        /* malformed SSE data */
      }
    };

    source.onerror = () => {
      source.close();
      sseRef.current = null;
      setLiveActivity(null);
    };

    const fallbackId = setInterval(() => {
      if (source.readyState === EventSource.CLOSED) fetchSession();
    }, 5000);

    return () => {
      source.close();
      sseRef.current = null;
      clearInterval(fallbackId);
      if (debounceTimer) clearTimeout(debounceTimer);
    };
  }, [session?.status, repoId, sessionId, fetchSession]);

  const loadCheckpoints = useCallback(async () => {
    try {
      const cps = await getSessionCheckpoints(repoId, sessionId);
      setCheckpoints(cps);
    } catch {
      /* ignore */
    }
  }, [repoId, sessionId]);

  useEffect(() => {
    if (session && (session.status === "completed" || session.status === "reviewing" || session.status === "failed")) {
      loadCheckpoints();
    }
  }, [session, loadCheckpoints]);

  /* ── Handlers ───────────────────────────────────────── */

  const handleSendFollowUp = async () => {
    if (!followUp.trim() || sending) return;
    setSending(true);
    try {
      await sendSessionMessage(repoId, sessionId, followUp.trim());
      setFollowUp("");
      await fetchSession();
    } catch {
      /* swallow */
    } finally {
      setSending(false);
    }
  };

  const handleAnswer = async () => {
    if (!userAnswer.trim() || answering) return;
    setAnswering(true);
    try {
      await sendSessionMessage(repoId, sessionId, userAnswer.trim());
      setUserAnswer("");
      await fetchSession();
    } catch {
      /* swallow */
    } finally {
      setAnswering(false);
    }
  };

  const handleCommit = async () => {
    if (!commitMsg.trim() || committing) return;
    setCommitting(true);
    setCommitError("");
    try {
      const r = await commitSession(repoId, sessionId, commitMsg.trim(), branchMode === "new" ? newBranchName.trim() : undefined);
      setCommitResult(r);
      setPrTitle(commitMsg.trim());
      if (session?.result_summary) setPrBody(session.result_summary);
    } catch (e: unknown) {
      setCommitError(e instanceof Error ? e.message : "Commit failed");
    } finally {
      setCommitting(false);
    }
  };

  const handleCreatePr = async () => {
    if (creatingPr || !prTitle.trim()) return;
    setCreatingPr(true);
    setPrError("");
    try {
      const r = await createPullRequest(repoId, sessionId, prTitle.trim(), prBody.trim());
      setPrResult(r);
    } catch (e: unknown) {
      setPrError(e instanceof Error ? e.message : "Failed to create PR");
    } finally {
      setCreatingPr(false);
    }
  };

  const handleDiscard = async () => {
    try {
      await cancelSession(repoId, sessionId);
      await fetchSession();
    } catch {
      /* swallow */
    }
  };

  const handleStop = async () => {
    if (stopping) return;
    setStopping(true);
    setLiveActivity("Stopping…");
    try {
      await stopSession(repoId, sessionId);
      await fetchSession();
    } catch {
      /* swallow */
    } finally {
      setStopping(false);
      setLiveActivity(null);
    }
  };

  const handleUserRetry = async () => {
    try {
      await retrySession(repoId, sessionId);
      await fetchSession();
    } catch {
      /* swallow */
    }
  };

  const handleEditRetry = async (editedText: string) => {
    try {
      await sendSessionMessage(repoId, sessionId, `[RETRY] ${editedText}`);
      await fetchSession();
    } catch {
      /* swallow */
    }
  };

  const handleRevert = async () => {
    setReverting(true);
    setRevertMsg("");
    try {
      const r = await revertSession(repoId, sessionId);
      setRevertMsg(r.message || "Changes reverted.");
      await fetchSession();
    } catch {
      setRevertMsg("Revert failed.");
    } finally {
      setReverting(false);
    }
  };

  const handleRestore = async (step: number) => {
    setRestoring(true);
    try {
      await restoreCheckpoint(repoId, sessionId, step);
      await fetchSession();
      await loadCheckpoints();
    } catch {
      /* swallow */
    } finally {
      setRestoring(false);
    }
  };

  /* ── Derived state ──────────────────────────────────── */

  const timeline = useMemo(() => (session ? buildTimeline(session) : []), [session]);

  useEffect(() => {
    if (timeline.length > prevTimelineLenRef.current) {
      chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
    prevTimelineLenRef.current = timeline.length;
  }, [timeline.length]);

  if (loading || !session) {
    return (
      <div style={{ minHeight: "100vh", paddingTop: 52, background: "#000", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <p style={{ fontFamily: "var(--font-hero-mono)", fontSize: 11, color: "rgba(255,255,255,0.2)", letterSpacing: "0.15em", textTransform: "uppercase" }}>
          Loading session…
        </p>
      </div>
    );
  }

  const isActive = ["pending", "running"].includes(session.status);
  const isDone = session.status === "completed" || session.status === "reviewing";
  const isAwaitingInput = session.status === "awaiting_input";
  const canRetry = isDone || session.status === "failed";

  const diffStats = diff?.files?.reduce(
    (acc, f) => ({ ins: acc.ins + (f.insertions || 0), del: acc.del + (f.deletions || 0) }),
    { ins: 0, del: 0 }
  ) || { ins: 0, del: 0 };

  /* ── Status badge ───────────────────────────────────── */

  const statusBadge = (() => {
    const map: Record<string, { label: string; color: string; bg: string }> = {
      running: { label: "Running", color: "rgba(80,255,120,0.6)", bg: "rgba(80,255,120,0.06)" },
      pending: { label: "Pending", color: "rgba(255,255,255,0.4)", bg: "rgba(255,255,255,0.04)" },
      completed: { label: "Completed", color: "rgba(80,255,120,0.5)", bg: "rgba(80,255,120,0.05)" },
      reviewing: { label: "Reviewing", color: "rgba(80,200,255,0.5)", bg: "rgba(80,200,255,0.05)" },
      failed: { label: "Failed", color: "rgba(255,80,80,0.55)", bg: "rgba(255,80,80,0.05)" },
      cancelled: { label: "Cancelled", color: "rgba(255,255,255,0.3)", bg: "rgba(255,255,255,0.03)" },
      awaiting_input: { label: "Awaiting input", color: "rgba(255,200,60,0.55)", bg: "rgba(255,200,60,0.05)" },
    };
    return map[session.status] || map.pending;
  })();

  /* ── Render ─────────────────────────────────────────── */

  return (
    <div style={{ minHeight: "100vh", background: "#000", paddingTop: 52 }}>
      {/* ── PR success banner ── */}
      {prResult && (
        <div
          style={{
            position: "fixed",
            top: 52,
            left: 0,
            right: 0,
            zIndex: 50,
            padding: "14px 24px",
            background: "rgba(80,255,120,0.06)",
            borderBottom: "1px solid rgba(80,255,120,0.1)",
            textAlign: "center",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 8,
          }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="rgba(80,255,120,0.7)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="18" cy="18" r="3" />
            <circle cx="6" cy="6" r="3" />
            <path d="M13 6h3a2 2 0 012 2v7" />
            <line x1="6" y1="9" x2="6" y2="21" />
          </svg>
          <p style={{ fontSize: 13, color: "rgba(80,255,120,0.7)", margin: 0, fontWeight: 500 }}>
            PR #{prResult.pr_number} created
          </p>
          <a
            href={prResult.pr_url}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              fontSize: 12,
              color: "rgba(80,200,255,0.7)",
              textDecoration: "underline",
              fontFamily: "var(--font-hero-mono)",
            }}
          >
            View on GitHub
          </a>
          </div>
      )}

      {/* ── Header ── */}
      <header
        style={{
          position: "sticky",
          top: prResult ? 100 : 52,
          zIndex: 40,
          padding: "14px 24px",
          borderBottom: "1px solid #111",
          background: "rgba(0,0,0,0.85)",
          backdropFilter: "blur(16px)",
          display: "flex",
          alignItems: "center",
          gap: 16,
        }}
      >
        <Link
          href={`/repos/${repoId}`}
          className="session-btn"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            color: "rgba(255,255,255,0.3)",
            textDecoration: "none",
            fontSize: 12,
            fontFamily: "inherit",
            transition: "color 0.12s",
          }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="15 18 9 12 15 6" />
          </svg>
          Back
        </Link>

        <div style={{ width: 1, height: 18, background: "#1a1a1a" }} />

        <div style={{ flex: 1, minWidth: 0 }}>
          <p
            style={{
              fontSize: 13,
              fontWeight: 500,
              color: "rgba(255,255,255,0.7)",
              margin: 0,
              overflow: "hidden",
              whiteSpace: "nowrap",
              textOverflow: "ellipsis",
            }}
          >
            {session.task_description.length > 80
              ? session.task_description.slice(0, 80) + "…"
              : session.task_description}
          </p>
        </div>

        <div
          style={{
            padding: "4px 10px",
            borderRadius: 20,
            background: statusBadge.bg,
            border: "1px solid transparent",
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          {isActive && (
            <div
              style={{
                width: 5,
                height: 5,
                borderRadius: "50%",
                background: statusBadge.color,
                animation: "dotPulse 1.2s ease-in-out infinite",
              }}
            />
          )}
          <span
            style={{
              fontSize: 10,
              fontWeight: 600,
              fontFamily: "var(--font-hero-mono)",
              letterSpacing: "0.04em",
              color: statusBadge.color,
            }}
          >
            {statusBadge.label}
          </span>
        </div>

        {isActive && (
          <button
            onClick={handleStop}
            disabled={stopping}
            className="session-danger"
            style={{
              display: "flex",
              alignItems: "center",
              gap: 5,
              padding: "5px 14px",
              borderRadius: 8,
              border: "1px solid rgba(255,80,80,0.15)",
              background: "rgba(255,60,60,0.06)",
              color: "rgba(255,80,80,0.65)",
              fontSize: 11,
              fontWeight: 600,
              fontFamily: "var(--font-hero-mono)",
              letterSpacing: "0.02em",
              cursor: stopping ? "default" : "pointer",
              transition: "all 0.15s",
              opacity: stopping ? 0.5 : 1,
            }}
          >
            <svg
              width="10"
              height="10"
              viewBox="0 0 24 24"
              fill="currentColor"
              stroke="none"
            >
              <rect x="4" y="4" width="16" height="16" rx="2" />
            </svg>
            {stopping ? "Stopping…" : "Stop"}
          </button>
        )}
      </header>

      {/* ── Main grid ── */}
      <main style={{ padding: "20px 24px", maxWidth: 1360, margin: "0 auto" }}>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: isDone || isAwaitingInput || session.status === "failed" ? "1fr 380px" : "1fr",
            gap: 20,
            alignItems: "start",
          }}
        >
          {/* ─── Left: Chat panel ─────────────────────── */}
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              borderRadius: 12,
              border: "1px solid #141414",
              background: "#080808",
              overflow: "hidden",
              maxHeight: "calc(100vh - 192px)",
            }}
          >
            {/* Chat header */}
            <div
              style={{
                padding: "10px 16px",
                borderBottom: "1px solid #111",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
              }}
            >
              <span
                style={{
                  fontSize: 10,
                  fontWeight: 600,
                  letterSpacing: "0.1em",
                  textTransform: "uppercase",
                  color: "rgba(255,255,255,0.2)",
                }}
              >
                Conversation
              </span>
              {isActive && (liveActivity || session.current_step) && (
                <span
                  style={{
                    fontSize: 10,
                    color: liveActivity ? "rgba(80,255,120,0.4)" : "rgba(255,255,255,0.2)",
                    fontFamily: "var(--font-hero-mono)",
                    overflow: "hidden",
                    whiteSpace: "nowrap",
                    textOverflow: "ellipsis",
                    maxWidth: "50%",
                    transition: "color 0.2s",
                  }}
                >
                  {liveActivity || session.current_step}
                </span>
              )}
            </div>

            {/* Chat body */}
            <div style={{ flex: 1, overflow: "auto", padding: "12px 16px" }}>
              {timeline.map((item, i) => {
                switch (item.kind) {
                  case "user":
                    return (
                      <UserMessage
                        key={`u-${i}`}
                        text={item.text}
                        isInitial={item.isInitial}
                        lastCheckpoint={item.lastCheckpoint}
                        onRetry={canRetry ? handleUserRetry : undefined}
                        onEditRetry={canRetry ? handleEditRetry : undefined}
                        onRestore={canRetry ? handleRestore : undefined}
                      />
                    );
                  case "agent_turn":
                    return <AgentTurnBlock key={`t-${i}`} tools={item.tools} />;
                  case "agent_text":
                    return <AgentTextMessage key={`at-${i}`} text={item.text} />;
                  case "summary":
                    return <SummaryBlock key={`s-${i}`} text={item.text} failed={session.status === "failed"} />;
                  case "retry_separator":
                    return <RetrySeparator key={`rs-${i}`} />;
                  default:
                    return null;
                }
              })}

              {/* Loading dots */}
              {isActive && (
                <div style={{ display: "flex", alignItems: "center", gap: 5, padding: "16px 4px" }}>
                  {[0, 1, 2].map((d) => (
                    <div
                      key={d}
                      className="dot"
                      style={{
                        width: 4,
                        height: 4,
                        borderRadius: "50%",
                        background: "rgba(255,255,255,0.3)",
                        animationDelay: `${d * 0.2}s`,
                      }}
                    />
                      ))}
                    </div>
              )}

              <div ref={chatEndRef} />
            </div>

            {/* Chat input footer */}
            <div
              style={{
                padding: "10px 16px",
                borderTop: "1px solid #111",
                background: "rgba(0,0,0,0.4)",
              }}
            >
              {isAwaitingInput ? (
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <input
                    type="text"
                    value={userAnswer}
                    onChange={(e) => setUserAnswer(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleAnswer()}
                    onFocus={() => setAnswerFocused(true)}
                    onBlur={() => setAnswerFocused(false)}
                    placeholder="Type your answer…"
                    disabled={answering}
                    className="session-input"
                    style={{
                      flex: 1,
                      padding: "9px 12px",
                      borderRadius: 8,
                      background: "#0a0a0a",
                      border: `1px solid ${answerFocused ? "rgba(255,200,60,0.2)" : "#1a1a1a"}`,
                      outline: "none",
                      color: "#fff",
                      fontSize: 12,
                      fontFamily: "inherit",
                      transition: "border-color 0.15s",
                    }}
                  />
                  <button
                    onClick={handleAnswer}
                    disabled={!userAnswer.trim() || answering}
                    className="session-btn-primary"
                    style={{
                      padding: "9px 16px",
                      borderRadius: 8,
                      border: "none",
                      background: !userAnswer.trim() ? "rgba(255,255,255,0.06)" : "#fff",
                      color: !userAnswer.trim() ? "rgba(255,255,255,0.2)" : "#000",
                      fontSize: 12,
                      fontWeight: 600,
                      fontFamily: "inherit",
                      cursor: !userAnswer.trim() ? "default" : "pointer",
                      transition: "background 0.12s",
                    }}
                  >
                    {answering ? "Sending…" : "Reply"}
                  </button>
                </div>
              ) : (
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <input
                    type="text"
                    value={followUp}
                    onChange={(e) => setFollowUp(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleSendFollowUp()}
                    onFocus={() => setFollowFocused(true)}
                    onBlur={() => setFollowFocused(false)}
                    placeholder="Send a follow-up message…"
                    disabled={sending || isActive}
                    className="session-input"
                    style={{
                      flex: 1,
                      padding: "9px 12px",
                      borderRadius: 8,
                      background: "#0a0a0a",
                      border: `1px solid ${followFocused ? "rgba(255,255,255,0.15)" : "#1a1a1a"}`,
                      outline: "none",
                      color: "#fff",
                      fontSize: 12,
                      fontFamily: "inherit",
                      transition: "border-color 0.15s",
                    }}
                  />
                  <button
                    onClick={handleSendFollowUp}
                    disabled={!followUp.trim() || sending || isActive}
                    className="session-btn-primary"
                    style={{
                      padding: "9px 16px",
                      borderRadius: 8,
                      border: "none",
                      background: !followUp.trim() || isActive ? "rgba(255,255,255,0.06)" : "#fff",
                      color: !followUp.trim() || isActive ? "rgba(255,255,255,0.2)" : "#000",
                      fontSize: 12,
                      fontWeight: 600,
                      fontFamily: "inherit",
                      cursor: !followUp.trim() || isActive ? "default" : "pointer",
                      transition: "background 0.12s",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {sending ? "Sending…" : "Send"}
                  </button>
                  {canRetry && (
                    <button
                      onClick={handleUserRetry}
                      className="session-action"
                      title="Retry task"
                      style={{
                        padding: "9px 12px",
                        borderRadius: 8,
                        border: "1px solid #1a1a1a",
                        background: "transparent",
                        color: "rgba(255,255,255,0.25)",
                        fontSize: 13,
                        cursor: "pointer",
                        transition: "all 0.12s",
                        display: "flex",
                        alignItems: "center",
                      }}
                    >
                      ↻
                    </button>
                  )}
                </div>
              )}
            </div>
            </div>

          {/* ─── Right: Actions panel ─────────────────── */}
          {(isDone || isAwaitingInput || session.status === "failed") && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12, position: "sticky", top: 132 }}>
              {/* Awaiting input card */}
              {isAwaitingInput && (
                <div
                  className="session-card"
                  style={{
                    borderRadius: 12,
                    border: "1px solid rgba(255,200,60,0.12)",
                    background: "#080808",
                    overflow: "hidden",
                    transition: "border-color 0.15s",
                  }}
                >
                  <div
                    style={{
                      padding: "10px 16px",
                      borderBottom: "1px solid rgba(255,200,60,0.06)",
                      display: "flex",
                      alignItems: "center",
                      gap: 6,
                    }}
                  >
                    <div
                      style={{
                        width: 6,
                        height: 6,
                        borderRadius: "50%",
                        background: "rgba(255,200,60,0.5)",
                        animation: "dotPulse 1.2s ease-in-out infinite",
                      }}
                    />
                    <span
                      style={{
                        fontSize: 10,
                        fontWeight: 600,
                        letterSpacing: "0.1em",
                        textTransform: "uppercase",
                        color: "rgba(255,200,60,0.4)",
                      }}
                    >
                      Agent needs input
                    </span>
                  </div>
                  <div style={{ padding: "14px 16px" }}>
                    <p
                      style={{
                        fontSize: 13,
                        color: "rgba(255,255,255,0.6)",
                        margin: 0,
                        lineHeight: 1.65,
                        whiteSpace: "pre-wrap",
                      }}
                    >
                      {session.result_summary || "The agent has a question for you."}
                    </p>
                  </div>
                </div>
              )}

              {/* Changes card */}
              {diff && (isDone || session.status === "failed") && (
                <div
                  className="session-card"
                  style={{
                    borderRadius: 12,
                    border: "1px solid #141414",
                    background: "#080808",
                    overflow: "hidden",
                    transition: "border-color 0.15s",
                  }}
                >
                  <div
                    style={{
                      padding: "10px 16px",
                      borderBottom: "1px solid #111",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                    }}
                  >
                    <span
                      style={{
                        fontSize: 10,
                        fontWeight: 600,
                        letterSpacing: "0.1em",
                        textTransform: "uppercase",
                        color: "rgba(255,255,255,0.2)",
                      }}
                    >
                      Changes
                    </span>
                    <div style={{ display: "flex", gap: 8 }}>
                      {diffStats.ins > 0 && (
                        <span style={{ fontFamily: "var(--font-hero-mono)", fontSize: 10, color: "rgba(80,255,120,0.4)" }}>
                          +{diffStats.ins}
                        </span>
                      )}
                      {diffStats.del > 0 && (
                        <span style={{ fontFamily: "var(--font-hero-mono)", fontSize: 10, color: "rgba(255,80,80,0.4)" }}>
                          -{diffStats.del}
                        </span>
                      )}
                    </div>
                  </div>
                  <div style={{ padding: "12px 14px", maxHeight: 300, overflow: "auto" }}>
                    <DiffPanel diff={diff} />
                  </div>
                </div>
              )}

              {/* Commit card */}
              {isDone && !commitResult && !prResult && (
                <div
                  className="session-card"
                  style={{
                    borderRadius: 12,
                    border: "1px solid #141414",
                    background: "#080808",
                    overflow: "hidden",
                    transition: "border-color 0.15s",
                  }}
                >
                  <div style={{ padding: "10px 16px", borderBottom: "1px solid #111" }}>
                    <span
                      style={{
                        fontSize: 10,
                        fontWeight: 600,
                        letterSpacing: "0.1em",
                        textTransform: "uppercase",
                        color: "rgba(255,255,255,0.2)",
                      }}
                    >
                      Commit
                    </span>
                  </div>
                  <div style={{ padding: "14px 16px" }}>
                    <textarea
                      value={commitMsg}
                      onChange={(e) => setCommitMsg(e.target.value)}
                      placeholder="Commit message…"
                      className="session-input"
                      style={{
                        width: "100%",
                        minHeight: 60,
                        padding: "9px 12px",
                        borderRadius: 8,
                        background: "#0a0a0a",
                        border: "1px solid #1a1a1a",
                        outline: "none",
                        color: "#fff",
                        fontSize: 12,
                        lineHeight: "1.5",
                        fontFamily: "inherit",
                        resize: "vertical",
                        transition: "border-color 0.15s",
                        boxSizing: "border-box",
                      }}
                    />

                    {/* Branch toggle */}
                    <div style={{ display: "flex", gap: 16, margin: "12px 0" }}>
                      {(["current", "new"] as const).map((mode) => (
                        <label
                          key={mode}
                          onClick={() => setBranchMode(mode)}
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 6,
                            cursor: "pointer",
                            fontSize: 11,
                            color: branchMode === mode ? "rgba(255,255,255,0.6)" : "rgba(255,255,255,0.2)",
                            transition: "color 0.12s",
                          }}
                        >
                          <div
                            style={{
                              width: 12,
                              height: 12,
                              borderRadius: "50%",
                              border: `2px solid ${branchMode === mode ? "rgba(255,255,255,0.5)" : "rgba(255,255,255,0.12)"}`,
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "center",
                              transition: "border-color 0.12s",
                            }}
                          >
                            {branchMode === mode && (
                              <div style={{ width: 5, height: 5, borderRadius: "50%", background: "#fff" }} />
                            )}
                          </div>
                          {mode === "current" ? "Current branch" : "New branch"}
                        </label>
                      ))}
                    </div>

                    {branchMode === "new" && (
              <input
                        type="text"
                        value={newBranchName}
                        onChange={(e) => setNewBranchName(e.target.value)}
                        placeholder="feature/my-branch"
                        className="session-input"
                style={{
                          width: "100%",
                          padding: "8px 12px",
                          borderRadius: 8,
                          background: "#0a0a0a",
                          border: "1px solid #1a1a1a",
                          outline: "none",
                          color: "#fff",
                          fontSize: 11,
                          fontFamily: "var(--font-hero-mono)",
                          marginBottom: 12,
                  transition: "border-color 0.15s",
                          boxSizing: "border-box",
                        }}
                      />
                    )}

                    {commitError && (
                      <p
                        style={{
                          fontSize: 11,
                          color: "rgba(255,80,80,0.6)",
                          margin: "0 0 10px",
                          padding: "6px 10px",
                          borderRadius: 6,
                          background: "rgba(255,60,60,0.04)",
                          border: "1px solid rgba(255,80,80,0.08)",
                        }}
                      >
                        {commitError}
                      </p>
                    )}

              <button
                      onClick={handleCommit}
                      disabled={committing || !commitMsg.trim() || (branchMode === "new" && !newBranchName.trim())}
                      className="session-btn-primary"
                style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 6,
                        padding: "8px 18px",
                        borderRadius: 8,
                        border: "none",
                        background:
                          committing || !commitMsg.trim() ? "rgba(255,255,255,0.06)" : "#fff",
                        color: committing || !commitMsg.trim() ? "rgba(255,255,255,0.2)" : "#000",
                        fontSize: 12,
                        fontWeight: 600,
                        fontFamily: "inherit",
                        cursor: committing || !commitMsg.trim() ? "default" : "pointer",
                        transition: "background 0.12s",
                      }}
                    >
                      <svg width="12" height="12" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                      </svg>
                      {committing ? "Committing…" : "Commit"}
              </button>
            </div>
          </div>
              )}

              {/* Post-commit: Create PR card */}
              {commitResult && !prResult && (
                <div
                  className="session-card"
                  style={{
                    borderRadius: 12,
                    border: "1px solid rgba(80,255,120,0.08)",
                    background: "#080808",
                    overflow: "hidden",
                    transition: "border-color 0.15s",
                  }}
                >
                  <div
                    style={{
                      padding: "10px 16px",
                      borderBottom: "1px solid #111",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                    }}
                  >
                    <span
                      style={{
                        fontSize: 10,
                        fontWeight: 600,
                        letterSpacing: "0.1em",
                        textTransform: "uppercase",
                        color: "rgba(80,255,120,0.35)",
                      }}
                    >
                      Create Pull Request
                    </span>
                    <span
                      style={{
                        fontFamily: "var(--font-hero-mono)",
                        fontSize: 10,
                        color: "rgba(255,255,255,0.2)",
                      }}
                    >
                      {commitResult.commit_hash.slice(0, 8)} on {commitResult.branch}
                    </span>
                  </div>
                  <div style={{ padding: "14px 16px", display: "flex", flexDirection: "column", gap: 10 }}>

                    {/* GitHub connection status bar */}
                    {!ghLoading && (
                      <div style={{
                        display: "flex", alignItems: "center", justifyContent: "space-between",
                        padding: "8px 12px", borderRadius: 8,
                        background: ghStatus.connected ? "rgba(80,255,120,0.04)" : "rgba(255,180,50,0.04)",
                        border: `1px solid ${ghStatus.connected ? "rgba(80,255,120,0.1)" : "rgba(255,180,50,0.1)"}`,
                      }}>
                        {ghStatus.connected ? (
                          <>
                            <span style={{ fontSize: 11, color: "rgba(80,255,120,0.6)", display: "flex", alignItems: "center", gap: 6 }}>
                              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.374 0 0 5.373 0 12c0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23A11.509 11.509 0 0112 5.803c1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576C20.566 21.797 24 17.3 24 12c0-6.627-5.373-12-12-12z"/></svg>
                              Connected as <strong style={{ color: "rgba(80,255,120,0.8)" }}>@{ghStatus.github_user}</strong>
                            </span>
                            <button
                              onClick={handleDisconnectGitHub}
                              style={{
                                fontSize: 10, color: "rgba(255,255,255,0.3)", background: "none",
                                border: "none", cursor: "pointer", fontFamily: "inherit",
                                textDecoration: "underline", padding: 0,
                              }}
                            >
                              Disconnect
                            </button>
                          </>
                        ) : (
                          <>
                            <span style={{ fontSize: 11, color: "rgba(255,180,50,0.6)" }}>
                              GitHub not connected — required for creating PRs
                            </span>
                            <button
                              onClick={handleConnectGitHub}
                              style={{
                                fontSize: 11, fontWeight: 600, color: "#fff",
                                background: "rgba(255,255,255,0.08)", border: "1px solid rgba(255,255,255,0.12)",
                                borderRadius: 6, padding: "5px 12px", cursor: "pointer",
                                fontFamily: "inherit", display: "flex", alignItems: "center", gap: 5,
                                transition: "background 0.12s",
                              }}
                            >
                              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.374 0 0 5.373 0 12c0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23A11.509 11.509 0 0112 5.803c1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576C20.566 21.797 24 17.3 24 12c0-6.627-5.373-12-12-12z"/></svg>
                              Connect GitHub
                            </button>
                          </>
                        )}
                      </div>
                    )}

                    <input
                      type="text"
                      value={prTitle}
                      onChange={(e) => setPrTitle(e.target.value)}
                      placeholder="PR title…"
                      className="session-input"
                      style={{
                        width: "100%",
                        padding: "9px 12px",
                        borderRadius: 8,
                        background: "#0a0a0a",
                        border: "1px solid #1a1a1a",
                        outline: "none",
                        color: "#fff",
                        fontSize: 12,
                        fontFamily: "inherit",
                        transition: "border-color 0.15s",
                        boxSizing: "border-box",
                      }}
                    />
                    <textarea
                      value={prBody}
                      onChange={(e) => setPrBody(e.target.value)}
                      placeholder="Description (optional, Markdown supported)…"
                      className="session-input"
                      style={{
                        width: "100%",
                        minHeight: 60,
                        padding: "9px 12px",
                        borderRadius: 8,
                        background: "#0a0a0a",
                        border: "1px solid #1a1a1a",
                        outline: "none",
                        color: "#fff",
                        fontSize: 12,
                        lineHeight: "1.5",
                        fontFamily: "inherit",
                        resize: "vertical",
                        transition: "border-color 0.15s",
                        boxSizing: "border-box",
                      }}
                    />

                    {prError && (
                      <p
                        style={{
                          fontSize: 11,
                          color: "rgba(255,80,80,0.6)",
                          margin: 0,
                          padding: "6px 10px",
                          borderRadius: 6,
                          background: "rgba(255,60,60,0.04)",
                          border: "1px solid rgba(255,80,80,0.08)",
                        }}
                      >
                        {prError}
                      </p>
                    )}

                    <div style={{ display: "flex", gap: 8 }}>
                    <button
                        onClick={handleCreatePr}
                        disabled={creatingPr || !prTitle.trim() || !ghStatus.connected}
                        className="session-btn-primary"
                      style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 6,
                          padding: "8px 18px",
                          borderRadius: 8,
                          border: "none",
                          background: creatingPr || !prTitle.trim() || !ghStatus.connected ? "rgba(255,255,255,0.06)" : "#fff",
                          color: creatingPr || !prTitle.trim() || !ghStatus.connected ? "rgba(255,255,255,0.2)" : "#000",
                          fontSize: 12,
                          fontWeight: 600,
                          fontFamily: "inherit",
                          cursor: creatingPr || !prTitle.trim() || !ghStatus.connected ? "default" : "pointer",
                          transition: "background 0.12s",
                        }}
                      >
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <circle cx="18" cy="18" r="3" />
                          <circle cx="6" cy="6" r="3" />
                          <path d="M13 6h3a2 2 0 012 2v7" />
                          <line x1="6" y1="9" x2="6" y2="21" />
                        </svg>
                        {creatingPr ? "Creating PR…" : "Create PR"}
                    </button>
                    <button
                        onClick={handleDiscard}
                        disabled={creatingPr}
                        className="session-danger"
                      style={{
                          padding: "8px 18px",
                          borderRadius: 8,
                          border: "1px solid #1a1a1a",
                          background: "transparent",
                          color: "rgba(255,80,80,0.45)",
                          fontSize: 12,
                          fontFamily: "inherit",
                          cursor: "pointer",
                          transition: "all 0.12s",
                      }}
                    >
                      Discard
                    </button>
                    </div>
                  </div>
                  </div>
                )}

              {/* PR created confirmation */}
              {commitResult && prResult && (
                <div
                  className="session-card"
                  style={{
                    borderRadius: 12,
                    border: "1px solid rgba(80,255,120,0.08)",
                    background: "#080808",
                    overflow: "hidden",
                  }}
                >
                  <div style={{ padding: "10px 16px", borderBottom: "1px solid #111" }}>
                    <span
                      style={{
                        fontSize: 10,
                        fontWeight: 600,
                        letterSpacing: "0.1em",
                        textTransform: "uppercase",
                        color: "rgba(80,255,120,0.35)",
                      }}
                    >
                      Pull Request Created
                    </span>
                  </div>
                  <div style={{ padding: "14px 16px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="rgba(80,255,120,0.5)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <circle cx="18" cy="18" r="3" />
                        <circle cx="6" cy="6" r="3" />
                        <path d="M13 6h3a2 2 0 012 2v7" />
                        <line x1="6" y1="9" x2="6" y2="21" />
                      </svg>
                      <span style={{ fontFamily: "var(--font-hero-mono)", fontSize: 12, color: "rgba(255,255,255,0.5)" }}>
                        #{prResult.pr_number}
                      </span>
                      <span style={{ fontSize: 12, color: "rgba(255,255,255,0.4)" }}>
                        {prResult.branch} → {prResult.base_branch}
                      </span>
                    </div>
                    <a
                      href={prResult.pr_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="session-btn-primary"
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 6,
                        padding: "8px 18px",
                        borderRadius: 8,
                        border: "none",
                        background: "#fff",
                        color: "#000",
                        fontSize: 12,
                        fontWeight: 600,
                        fontFamily: "inherit",
                        textDecoration: "none",
                        cursor: "pointer",
                        transition: "background 0.12s",
                      }}
                    >
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6" />
                        <polyline points="15 3 21 3 21 9" />
                        <line x1="10" y1="14" x2="21" y2="3" />
                      </svg>
                      View on GitHub
                    </a>
                  </div>
                </div>
              )}

              {/* Quick actions card (before commit) */}
              {(isDone || session.status === "failed") && !commitResult && !prResult && (
                <div
                  style={{
                    borderRadius: 12,
                    border: "1px solid #141414",
                    background: "#080808",
                    padding: "14px 16px",
                    display: "flex",
                    flexDirection: "column",
                    gap: 8,
                  }}
                >
                  <div style={{ display: "flex", gap: 8 }}>
                    <button
                      onClick={handleRevert}
                      disabled={reverting}
                      className="session-warn"
                      style={{
                        flex: 1,
                        padding: "8px 14px",
                        borderRadius: 8,
                        border: "1px solid #1a1a1a",
                        background: "transparent",
                        color: "rgba(255,200,60,0.45)",
                        fontSize: 11,
                        fontFamily: "inherit",
                        cursor: reverting ? "default" : "pointer",
                        transition: "all 0.12s",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        gap: 5,
                      }}
                    >
                      <svg width="11" height="11" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 10h10a5 5 0 010 10H9M3 10l4-4M3 10l4 4" />
                      </svg>
                      {reverting ? "Reverting…" : "Revert all"}
                    </button>
                    <button
                      onClick={handleDiscard}
                      className="session-danger"
                      style={{
                        flex: 1,
                        padding: "8px 14px",
                        borderRadius: 8,
                        border: "1px solid #1a1a1a",
                        background: "transparent",
                        color: "rgba(255,80,80,0.4)",
                        fontSize: 11,
                        fontFamily: "inherit",
                        cursor: "pointer",
                        transition: "all 0.12s",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        gap: 5,
                      }}
                    >
                      <svg width="11" height="11" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <line x1="18" y1="6" x2="6" y2="18" strokeWidth="2" strokeLinecap="round" />
                        <line x1="6" y1="6" x2="18" y2="18" strokeWidth="2" strokeLinecap="round" />
                      </svg>
                      Discard
                    </button>
                  </div>
                  {revertMsg && (
                    <p
                      style={{
                        fontSize: 10,
                        color: "rgba(255,255,255,0.35)",
                        margin: 0,
                        padding: "6px 10px",
                        borderRadius: 6,
                        background: "rgba(255,255,255,0.02)",
                        border: "1px solid rgba(255,255,255,0.05)",
                      }}
                    >
                      {revertMsg}
                  </p>
                )}
              </div>
            )}

              {/* Checkpoints card */}
              {checkpoints.length > 0 && !commitResult && (
                <div
                  className="session-card"
                  style={{
                    borderRadius: 12,
                    border: "1px solid #141414",
                    background: "#080808",
                    overflow: "hidden",
                    transition: "border-color 0.15s",
                  }}
                >
                  <div style={{ padding: "10px 16px", borderBottom: "1px solid #111" }}>
                    <span
                      style={{
                        fontSize: 10,
                        fontWeight: 600,
                        letterSpacing: "0.1em",
                        textTransform: "uppercase",
                        color: "rgba(255,255,255,0.2)",
                      }}
                    >
                      Checkpoints
                    </span>
                  </div>
                  <div style={{ padding: "8px 12px" }}>
                    {checkpoints.map((cp) => (
                      <div
                        key={cp.sha}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          padding: "6px 6px",
                          borderRadius: 6,
                        }}
                      >
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <span
                            style={{
                              fontFamily: "var(--font-hero-mono)",
                              fontSize: 10,
                              color: "rgba(255,255,255,0.3)",
                            }}
                          >
                            Step {cp.step}
                          </span>
                          <span
                            style={{
                              fontFamily: "var(--font-hero-mono)",
                              fontSize: 9,
                              color: "rgba(255,255,255,0.15)",
                            }}
                          >
                            {cp.sha.slice(0, 8)}
                          </span>
                        </div>
                        <button
                          onClick={() => handleRestore(cp.step)}
                          disabled={restoring}
                          className="session-cp-btn"
                          style={{
                            padding: "3px 10px",
                            borderRadius: 5,
                            border: "1px solid rgba(80,200,255,0.1)",
                            background: "transparent",
                            color: "rgba(80,200,255,0.35)",
                            fontSize: 10,
                            fontFamily: "var(--font-hero-mono)",
                            cursor: restoring ? "default" : "pointer",
                            transition: "all 0.12s",
                          }}
                        >
                          Restore
                        </button>
                      </div>
                    ))}
                  </div>
              </div>
            )}

              {/* Failed state info */}
              {session.status === "failed" && session.error_message && (
                <div
                  className="session-card"
                  style={{
                    borderRadius: 12,
                    border: "1px solid rgba(255,80,80,0.08)",
                    background: "#080808",
                    overflow: "hidden",
                  }}
                >
                  <div style={{ padding: "10px 16px", borderBottom: "1px solid #111" }}>
                    <span
                      style={{
                        fontSize: 10,
                        fontWeight: 600,
                        letterSpacing: "0.1em",
                        textTransform: "uppercase",
                        color: "rgba(255,80,80,0.35)",
                      }}
                    >
                      Error details
                    </span>
          </div>
                  <div style={{ padding: "14px 16px" }}>
                    <p
                      style={{
                        fontSize: 12,
                        color: "rgba(255,80,80,0.55)",
                        margin: 0,
                        lineHeight: 1.55,
                        whiteSpace: "pre-wrap",
                        wordBreak: "break-word",
                      }}
                    >
                      {session.error_message}
                    </p>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
