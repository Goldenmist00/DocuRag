"use client";

import Link from "next/link";
import type { Repo } from "@/lib/api";

type RepoListCardProps = {
  repo: Repo;
};

/**
 * Single repo summary card linking to the repo dashboard.
 */
export function RepoListCard({ repo }: RepoListCardProps) {
  return (
    <Link
      href={`/repos/${repo.id}`}
      className="group block rounded-xl border border-white/10 bg-white/[0.03] p-5 transition hover:border-white/18 hover:bg-white/[0.06]"
    >
      <div className="flex items-start justify-between gap-3">
        <h3 className="line-clamp-2 text-base font-medium text-white/90 group-hover:text-white">
          {repo.name}
        </h3>
        <span className="shrink-0 rounded-md border border-white/10 bg-white/[0.05] px-2 py-0.5 text-[0.65rem] font-medium uppercase tracking-wide text-white/45">
          {repo.indexing_status}
        </span>
      </div>
      <p className="mt-2 truncate text-xs text-white/30">{repo.remote_url}</p>
      <div className="mt-4 flex items-center gap-4 text-xs text-white/40">
        <span>
          <span className="text-white/55">{repo.indexed_files}</span>
          {" / "}
          {repo.total_files} files indexed
        </span>
        {repo.last_indexed_at && (
          <span className="hidden sm:inline">Updated {new Date(repo.last_indexed_at).toLocaleString()}</span>
        )}
      </div>
    </Link>
  );
}
