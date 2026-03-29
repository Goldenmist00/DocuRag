"use client";

import { useState } from "react";

type ConnectRepoModalProps = {
  open: boolean;
  onClose: () => void;
  onSubmit: (remoteUrl: string, authToken?: string) => Promise<void>;
};

/**
 * Modal to connect a new Git remote for repo analysis.
 */
export function ConnectRepoModal({ open, onClose, onSubmit }: ConnectRepoModalProps) {
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);

  if (!open) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = url.trim();
    if (!trimmed || busy) return;
    setBusy(true);
    try {
      await onSubmit(trimmed, token.trim() || undefined);
      setUrl("");
      setToken("");
      onClose();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 px-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="connect-repo-title"
      onClick={(e) => e.target === e.currentTarget && !busy && onClose()}
    >
      <div
        className="w-full max-w-md rounded-xl border border-white/10 bg-[#0a0a0a] p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="connect-repo-title" className="text-lg font-semibold tracking-tight text-white">
          Connect repository
        </h2>
        <p className="mt-1 text-sm text-white/40">Clone URL and optional credentials for private remotes.</p>

        <form onSubmit={handleSubmit} className="mt-5 flex flex-col gap-4">
          <label className="block">
            <span className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-white/35">
              Remote URL
            </span>
            <input
              type="url"
              required
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://github.com/org/repo.git"
              className="w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2.5 text-sm text-white placeholder:text-white/25 focus:border-white/20 focus:outline-none"
            />
          </label>
          <label className="block">
            <span className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-white/35">
              Auth token (optional)
            </span>
            <input
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="PAT or deploy token"
              autoComplete="off"
              className="w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2.5 text-sm text-white placeholder:text-white/25 focus:border-white/20 focus:outline-none"
            />
          </label>
          <div className="mt-2 flex justify-end gap-2">
            <button
              type="button"
              onClick={() => !busy && onClose()}
              className="rounded-lg border border-white/10 bg-transparent px-4 py-2 text-sm text-white/60 transition hover:border-white/20 hover:text-white"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={busy}
              className="rounded-lg border border-white/15 bg-white/[0.08] px-4 py-2 text-sm font-medium text-white transition hover:bg-white/[0.12] disabled:opacity-50"
            >
              {busy ? "Connecting…" : "Connect"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
