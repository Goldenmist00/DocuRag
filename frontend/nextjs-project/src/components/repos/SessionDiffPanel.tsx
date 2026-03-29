"use client";

import type { SessionDiff } from "@/lib/api";

type SessionDiffPanelProps = {
  diff: SessionDiff | null;
  loading: boolean;
  error: string | null;
};

/**
 * Shows session diff summary and per-file patches when the agent has finished.
 */
export function SessionDiffPanel({ diff, loading, error }: SessionDiffPanelProps) {
  if (loading) {
    return <p className="text-sm text-white/40">Loading diff…</p>;
  }
  if (error) {
    return <p className="text-sm text-red-300/90">{error}</p>;
  }
  if (!diff) {
    return <p className="text-sm text-white/35">Diff will appear when the session completes.</p>;
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-4 text-xs text-white/50">
        <span>
          Files: <strong className="text-white/70">{diff.files_changed}</strong>
        </span>
        <span className="text-emerald-400/80">
          +{diff.insertions} <span className="text-white/30">/</span>{" "}
          <span className="text-rose-400/80">−{diff.deletions}</span>
        </span>
      </div>
      {diff.agent_summary ? (
        <p className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-3 text-sm text-white/65">{diff.agent_summary}</p>
      ) : null}
      {diff.diff_text ? (
        <pre className="max-h-64 overflow-auto rounded-lg border border-white/10 bg-black/40 p-3 text-xs text-white/55 [scrollbar-width:thin]">
          {diff.diff_text}
        </pre>
      ) : null}
      {diff.files?.length ? (
        <div className="space-y-2">
          <p className="text-[0.65rem] font-semibold uppercase tracking-wider text-white/35">Files</p>
          <ul className="max-h-48 space-y-2 overflow-auto [scrollbar-width:thin]">
            {diff.files.map((f) => (
              <li key={f.path} className="rounded-md border border-white/[0.06] bg-white/[0.02] p-2">
                <div className="flex items-center justify-between gap-2 text-xs">
                  <span className="truncate font-mono text-white/70">{f.path}</span>
                  <span className="shrink-0 text-white/40">{f.status}</span>
                </div>
                {f.diff ? (
                  <pre className="mt-2 max-h-32 overflow-auto text-[0.65rem] leading-snug text-white/45">{f.diff}</pre>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
