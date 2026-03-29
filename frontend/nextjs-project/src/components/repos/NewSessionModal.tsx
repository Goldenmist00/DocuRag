"use client";

import { useState } from "react";

type NewSessionModalProps = {
  open: boolean;
  onClose: () => void;
  onCreate: (task: string) => Promise<void>;
};

/**
 * Modal to start a new agent session with a task description.
 */
export function NewSessionModal({ open, onClose, onCreate }: NewSessionModalProps) {
  const [task, setTask] = useState("");
  const [busy, setBusy] = useState(false);

  if (!open) return null;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const t = task.trim();
    if (!t || busy) return;
    setBusy(true);
    try {
      await onCreate(t);
      setTask("");
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
      aria-labelledby="new-session-title"
      onClick={(e) => e.target === e.currentTarget && !busy && onClose()}
    >
      <div
        className="w-full max-w-lg rounded-xl border border-white/10 bg-[#0a0a0a] p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="new-session-title" className="text-lg font-semibold text-white">
          New agent session
        </h2>
        <p className="mt-1 text-sm text-white/40">Describe what the agent should work on in this repo.</p>
        <form onSubmit={submit} className="mt-4 flex flex-col gap-3">
          <textarea
            required
            rows={4}
            value={task}
            onChange={(e) => setTask(e.target.value)}
            placeholder="e.g. Add error handling to the auth module and update tests"
            className="w-full resize-y rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2.5 text-sm text-white placeholder:text-white/25 focus:border-white/20 focus:outline-none"
          />
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => !busy && onClose()}
              className="rounded-lg border border-white/10 px-4 py-2 text-sm text-white/60 hover:text-white"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={busy}
              className="rounded-lg border border-white/15 bg-white/[0.08] px-4 py-2 text-sm font-medium text-white hover:bg-white/[0.12] disabled:opacity-50"
            >
              {busy ? "Creating…" : "Start session"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
