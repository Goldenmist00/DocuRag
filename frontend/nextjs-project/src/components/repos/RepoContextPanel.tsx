"use client";

import type { ReactNode } from "react";
import type { RepoContext } from "@/lib/api";

type RepoContextPanelProps = {
  context: RepoContext | null;
  loading: boolean;
  error: string | null;
};

function ContextSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-4">
      <h4 className="text-[0.65rem] font-semibold uppercase tracking-wider text-white/35">{title}</h4>
      <div className="mt-2">{children}</div>
    </section>
  );
}

function ObjectPreview({ data }: { data: Record<string, unknown> }) {
  const keys = Object.keys(data);
  if (keys.length === 0) return <p className="text-sm text-white/25">—</p>;
  return (
    <pre className="max-h-40 overflow-auto text-xs leading-relaxed text-white/55 [scrollbar-width:thin]">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}

function ListPreview({ items }: { items: unknown[] }) {
  if (!items.length) return <p className="text-sm text-white/25">—</p>;
  return (
    <ul className="max-h-40 list-inside list-disc space-y-1 overflow-auto text-xs text-white/55 [scrollbar-width:thin]">
      {items.map((item, i) => (
        <li key={i} className="break-words">
          {typeof item === "string" ? item : JSON.stringify(item)}
        </li>
      ))}
    </ul>
  );
}

/**
 * Renders indexed repository context (architecture, stack, features, etc.).
 */
export function RepoContextPanel({ context, loading, error }: RepoContextPanelProps) {
  if (loading) {
    return (
      <div className="rounded-xl border border-white/10 bg-white/[0.03] p-8 text-center text-sm text-white/40">
        Loading context…
      </div>
    );
  }
  if (error) {
    return (
      <div className="rounded-xl border border-red-500/20 bg-red-500/[0.06] p-4 text-sm text-red-300/90">
        {error}
      </div>
    );
  }
  if (!context) {
    return (
      <div className="rounded-xl border border-white/10 bg-white/[0.03] p-6 text-sm text-white/35">
        No context loaded yet.
      </div>
    );
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <ContextSection title="Architecture">
        <ObjectPreview data={context.architecture} />
      </ContextSection>
      <ContextSection title="Tech stack">
        <ObjectPreview data={context.tech_stack} />
      </ContextSection>
      <ContextSection title="Features">
        <ListPreview items={context.features} />
      </ContextSection>
      <ContextSection title="API surface">
        <ListPreview items={context.api_surface} />
      </ContextSection>
      <ContextSection title="Future scope">
        <ListPreview items={context.future_scope} />
      </ContextSection>
      <ContextSection title="Security findings">
        <ListPreview items={context.security_findings} />
      </ContextSection>
      <ContextSection title="Tech debt">
        <ListPreview items={context.tech_debt} />
      </ContextSection>
      <ContextSection title="Test coverage">
        <ObjectPreview data={context.test_coverage} />
      </ContextSection>
      <ContextSection title="Dependency graph">
        <ObjectPreview data={context.dependency_graph} />
      </ContextSection>
      <ContextSection title="Key files">
        <ListPreview items={context.key_files} />
      </ContextSection>
    </div>
  );
}
