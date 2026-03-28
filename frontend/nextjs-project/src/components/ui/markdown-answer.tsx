"use client";

import { useEffect, useRef, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";
import type { Components } from "react-markdown";

function MermaidBlock({ chart }: { chart: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const rendered = useRef(false);

  const render = useCallback(async () => {
    if (!ref.current || rendered.current) return;
    rendered.current = true;
    try {
      const mermaid = (await import("mermaid")).default;
      mermaid.initialize({
        startOnLoad: false,
        theme: "dark",
        themeVariables: {
          primaryColor: "#1a1a2e",
          primaryTextColor: "#e0e0e0",
          primaryBorderColor: "#333",
          lineColor: "#555",
          secondaryColor: "#16213e",
          tertiaryColor: "#0f3460",
          fontFamily: "var(--font-hero-mono), monospace",
          fontSize: "12px",
        },
      });
      const id = `mermaid-${Math.random().toString(36).slice(2, 9)}`;
      const { svg } = await mermaid.render(id, chart.trim());
      if (ref.current) ref.current.innerHTML = svg;
    } catch {
      if (ref.current) {
        ref.current.textContent = chart;
        ref.current.style.whiteSpace = "pre-wrap";
        ref.current.style.color = "rgba(255,80,80,0.5)";
      }
    }
  }, [chart]);

  useEffect(() => {
    render();
  }, [render]);

  return (
    <div
      ref={ref}
      style={{
        margin: "12px 0",
        padding: 16,
        borderRadius: 8,
        background: "#0c0c0c",
        border: "1px solid #1f1f1f",
        overflow: "auto",
        display: "flex",
        justifyContent: "center",
      }}
    />
  );
}

const CODE_STYLE: React.CSSProperties = {
  margin: "12px 0",
  borderRadius: 8,
  border: "1px solid #1f1f1f",
  fontSize: "0.78rem",
  lineHeight: 1.65,
};

const INLINE_CODE_STYLE: React.CSSProperties = {
  fontFamily: "var(--font-hero-mono), monospace",
  fontSize: "0.8em",
  padding: "2px 6px",
  borderRadius: 4,
  background: "rgba(255,255,255,0.06)",
  color: "rgba(255,255,255,0.7)",
};

const components: Components = {
  h1: ({ children }) => (
    <h1 style={{ fontSize: 18, fontWeight: 600, color: "#fff", margin: "20px 0 8px", letterSpacing: "-0.02em" }}>
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 style={{ fontSize: 15, fontWeight: 600, color: "rgba(255,255,255,0.85)", margin: "18px 0 6px", letterSpacing: "-0.01em" }}>
      {children}
    </h2>
  ),
  h3: ({ children }) => (
    <h3 style={{ fontSize: 13, fontWeight: 600, color: "rgba(255,255,255,0.7)", margin: "14px 0 4px" }}>
      {children}
    </h3>
  ),
  p: ({ children }) => (
    <p style={{ fontSize: 13, color: "rgba(255,255,255,0.6)", lineHeight: 1.75, margin: "6px 0" }}>
      {children}
    </p>
  ),
  ul: ({ children }) => (
    <ul style={{ margin: "6px 0", paddingLeft: 20, color: "rgba(255,255,255,0.6)", fontSize: 13, lineHeight: 1.75 }}>
      {children}
    </ul>
  ),
  ol: ({ children }) => (
    <ol style={{ margin: "6px 0", paddingLeft: 20, color: "rgba(255,255,255,0.6)", fontSize: 13, lineHeight: 1.75 }}>
      {children}
    </ol>
  ),
  li: ({ children }) => (
    <li style={{ marginBottom: 3 }}>{children}</li>
  ),
  strong: ({ children }) => (
    <strong style={{ color: "rgba(255,255,255,0.85)", fontWeight: 600 }}>{children}</strong>
  ),
  a: ({ href, children }) => (
    <a href={href} style={{ color: "rgba(130,170,255,0.8)", textDecoration: "none" }} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  ),
  table: ({ children }) => (
    <div style={{ overflow: "auto", margin: "12px 0" }}>
      <table style={{
        width: "100%", borderCollapse: "collapse", fontSize: 12,
        border: "1px solid #1f1f1f", borderRadius: 6,
      }}>
        {children}
      </table>
    </div>
  ),
  th: ({ children }) => (
    <th style={{
      padding: "8px 12px", textAlign: "left", fontWeight: 600,
      color: "rgba(255,255,255,0.6)", background: "rgba(255,255,255,0.04)",
      borderBottom: "1px solid #1f1f1f", fontSize: 11,
      letterSpacing: "0.04em", textTransform: "uppercase",
    }}>
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td style={{
      padding: "6px 12px", color: "rgba(255,255,255,0.5)",
      borderBottom: "1px solid #141414",
    }}>
      {children}
    </td>
  ),
  blockquote: ({ children }) => (
    <blockquote style={{
      margin: "10px 0", padding: "8px 14px",
      borderLeft: "3px solid rgba(255,255,255,0.15)",
      color: "rgba(255,255,255,0.45)", fontStyle: "italic",
    }}>
      {children}
    </blockquote>
  ),
  hr: () => (
    <hr style={{ border: "none", borderTop: "1px solid #1f1f1f", margin: "16px 0" }} />
  ),
  code: ({ className, children }) => {
    const match = /language-(\w+)/.exec(className || "");
    const lang = match ? match[1] : "";
    const codeStr = String(children).replace(/\n$/, "");
    const isInline = !className && !codeStr.includes("\n");

    if (isInline) {
      return <code style={INLINE_CODE_STYLE}>{children}</code>;
    }

    if (lang === "mermaid") {
      return <MermaidBlock chart={codeStr} />;
    }

    return (
      <SyntaxHighlighter
        style={vscDarkPlus as unknown as { [key: string]: React.CSSProperties }}
        language={lang || "text"}
        customStyle={CODE_STYLE}
        showLineNumbers={codeStr.split("\n").length > 3}
        wrapLongLines
      >
        {codeStr}
      </SyntaxHighlighter>
    );
  },
};

function cleanAnswer(raw: string): string {
  const trimmed = raw.trim();
  const jsonDupeMatch = trimmed.match(/\n\s*\{\s*\n?\s*"answer"\s*:/);
  if (jsonDupeMatch && jsonDupeMatch.index) {
    return trimmed.slice(0, jsonDupeMatch.index).trim();
  }
  return trimmed;
}

export default function MarkdownAnswer({ content }: { content: string }) {
  const cleaned = cleanAnswer(content);

  return (
    <div className="markdown-answer">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {cleaned}
      </ReactMarkdown>
    </div>
  );
}
