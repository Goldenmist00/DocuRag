"use client";

type AgentLogListProps = {
  entries: Record<string, unknown>[];
};

/**
 * Renders agent log entries as readable lines.
 */
export function AgentLogList({ entries }: AgentLogListProps) {
  if (!entries.length) {
    return <p className="text-sm text-white/35">No log entries yet.</p>;
  }
  return (
    <ol className="max-h-80 space-y-2 overflow-auto pr-1 text-sm [scrollbar-width:thin]">
      {entries.map((entry, i) => (
        <li
          key={i}
          className="rounded-lg border border-white/[0.06] bg-black/20 px-3 py-2 font-mono text-xs leading-relaxed text-white/60"
        >
          {formatLogEntry(entry)}
        </li>
      ))}
    </ol>
  );
}

function formatLogEntry(entry: Record<string, unknown>): string {
  const msg = entry.message ?? entry.action ?? entry.step ?? entry.type;
  if (typeof msg === "string") return msg;
  try {
    return JSON.stringify(entry, null, 2);
  } catch {
    return String(entry);
  }
}
