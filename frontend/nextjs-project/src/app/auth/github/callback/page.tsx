"use client";

import { useSearchParams, useRouter } from "next/navigation";
import { useEffect, useState, Suspense } from "react";

function CallbackContent() {
  const params = useSearchParams();
  const router = useRouter();
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [user, setUser] = useState("");

  useEffect(() => {
    const s = params.get("status");
    const u = params.get("user");
    if (s === "success" && u) {
      setStatus("success");
      setUser(u);
      setTimeout(() => {
        window.close();
      }, 2000);
    } else {
      setStatus("error");
    }
  }, [params, router]);

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "#000",
        color: "#fff",
        fontFamily: "inherit",
      }}
    >
      <div
        style={{
          textAlign: "center",
          padding: 40,
          borderRadius: 16,
          background: "rgba(255,255,255,0.04)",
          border: "1px solid rgba(255,255,255,0.08)",
          maxWidth: 420,
        }}
      >
        {status === "loading" && (
          <>
            <div style={{ fontSize: 32, marginBottom: 12 }}>Connecting...</div>
            <p style={{ color: "rgba(255,255,255,0.5)" }}>
              Completing GitHub authorization...
            </p>
          </>
        )}
        {status === "success" && (
          <>
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" style={{ marginBottom: 16 }}>
              <circle cx="12" cy="12" r="10" stroke="#22c55e" strokeWidth="2" />
              <path d="M8 12l2.5 2.5L16 9" stroke="#22c55e" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <div style={{ fontSize: 20, fontWeight: 600, marginBottom: 8 }}>
              GitHub Connected
            </div>
            <p style={{ color: "rgba(255,255,255,0.5)", marginBottom: 16 }}>
              Signed in as <strong style={{ color: "#fff" }}>@{user}</strong>
            </p>
            <p style={{ color: "rgba(255,255,255,0.3)", fontSize: 13 }}>
              This window will close automatically...
            </p>
          </>
        )}
        {status === "error" && (
          <>
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" style={{ marginBottom: 16 }}>
              <circle cx="12" cy="12" r="10" stroke="#ef4444" strokeWidth="2" />
              <path d="M15 9l-6 6M9 9l6 6" stroke="#ef4444" strokeWidth="2" strokeLinecap="round" />
            </svg>
            <div style={{ fontSize: 20, fontWeight: 600, marginBottom: 8 }}>
              Connection Failed
            </div>
            <p style={{ color: "rgba(255,255,255,0.5)", marginBottom: 16 }}>
              GitHub authorization was not completed.
            </p>
            <button
              onClick={() => window.close()}
              style={{
                padding: "8px 20px",
                borderRadius: 8,
                border: "1px solid rgba(255,255,255,0.1)",
                background: "rgba(255,255,255,0.06)",
                color: "#fff",
                cursor: "pointer",
                fontFamily: "inherit",
                fontSize: 13,
              }}
            >
              Close
            </button>
          </>
        )}
      </div>
    </div>
  );
}

export default function GitHubCallbackPage() {
  return (
    <Suspense
      fallback={
        <div style={{ minHeight: "100vh", background: "#000", display: "flex", alignItems: "center", justifyContent: "center", color: "#fff" }}>
          Connecting to GitHub...
        </div>
      }
    >
      <CallbackContent />
    </Suspense>
  );
}
