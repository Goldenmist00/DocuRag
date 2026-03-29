"use client";

import Link from "next/link";
import type { AgentSession } from "@/lib/api";

type AgentSessionRowProps = {
  repoId: string;
  session: AgentSession;
};

/**
 * Row linking to a single agent session detail page.
 */
export function AgentSessionRow({ repoId, session }: AgentSessionRowProps) {
  return (
    <Link
      href={`/repos/${repoId}/sessions/${session.id}`}
      className="flex flex-col gap-1 rounded-lg border border-white/10 bg-white/[0.02] px-4 py-3 transition hover:border-white/18 hover:bg-white/[0.05] sm:flex-row sm:items-center sm:justify-between"
    >
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-white/85">{session.task_description}</p>
        <p className="mt-0.5 text-xs text-white/35">
          {session.current_step || "—"} · {new Date(session.created_at).toLocaleString()}
        </p>
      </div>
      <span className="shrink-0 rounded-md border border-white/10 bg-white/[0.05] px-2 py-0.5 text-[0.65rem] font-medium uppercase tracking-wide text-white/50">
        {session.status}
      </span>
    </Link>
  );
}
