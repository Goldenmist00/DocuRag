"use client";

import React, { useState } from "react";
import Link from "next/link";

function BackgroundGradient() {
  return (
    <div aria-hidden style={{ position: "fixed", inset: 0, pointerEvents: "none", zIndex: 0 }}>
      <div
        style={{
          position: "absolute",
          top: "30%",
          left: "50%",
          transform: "translateX(-50%)",
          width: 600,
          height: 600,
          borderRadius: "50%",
          background: "radial-gradient(circle, rgba(255,255,255,0.03) 0%, transparent 70%)",
          filter: "blur(40px)",
        }}
      />
    </div>
  );
}

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [focused, setFocused] = useState(false);
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setTimeout(() => {
      setLoading(false);
      setSent(true);
    }, 1400);
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        paddingTop: 52,
        width: "100%",
        background: "#060609",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontFamily: "var(--font-inria), 'Inria Sans', sans-serif",
        position: "relative",
        padding: "24px",
      }}
    >
      <BackgroundGradient />

      {/* Back to login */}
      <Link
        href="/login"
        style={{
          position: "fixed",
          top: "24px",
          left: "32px",
          zIndex: 20,
          display: "flex",
          alignItems: "center",
          gap: "8px",
          color: "rgba(255,255,255,0.7)",
          textDecoration: "none",
          fontSize: "0.85rem",
          fontFamily: "inherit",
          transition: "color 0.2s",
        }}
        onMouseEnter={(e) => (e.currentTarget.style.color = "white")}
        onMouseLeave={(e) => (e.currentTarget.style.color = "rgba(255,255,255,0.7)")}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
          <path d="M19 12H5M5 12L12 19M5 12L12 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        Back to sign in
      </Link>

      {/* Card */}
      <div
        style={{
          position: "relative",
          zIndex: 10,
          width: "100%",
          maxWidth: "400px",
          background: "rgba(6,6,9,0.85)",
          backdropFilter: "blur(24px)",
          border: "1px solid rgba(255,255,255,0.08)",
          borderRadius: "12px",
          padding: "40px 36px",
          boxShadow: "0 32px 80px rgba(0,0,0,0.5)",
        }}
      >
        {!sent ? (
          <>
            {/* Header */}
            <div style={{ marginBottom: "32px" }}>
              {/* Lock icon */}
              <div
                style={{
                  width: "44px",
                  height: "44px",
                  borderRadius: "6px",
                  background: "rgba(255,255,255,0.05)",
                  border: "1px solid rgba(255,255,255,0.1)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  marginBottom: "20px",
                }}
              >
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
                  <rect x="3" y="11" width="18" height="11" rx="2" stroke="rgba(255,255,255,0.6)" strokeWidth="1.5" />
                  <path d="M7 11V7a5 5 0 0 1 10 0v4" stroke="rgba(255,255,255,0.6)" strokeWidth="1.5" strokeLinecap="round" />
                </svg>
              </div>
              <p
                style={{
                  fontSize: "0.75rem",
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  color: "rgba(255,255,255,0.4)",
                  marginBottom: "10px",
                  fontWeight: 400,
                  fontFamily: "var(--font-hero-mono)",
                }}
              >
                Account recovery
              </p>
              <h1
                style={{
                  fontSize: "1.75rem",
                  fontWeight: 700,
                  color: "white",
                  lineHeight: 1.2,
                  margin: 0,
                  fontFamily: "var(--font-hero-display)",
                }}
              >
                Forgot password?
              </h1>
              <p style={{ marginTop: "8px", fontSize: "0.875rem", color: "rgba(255,255,255,0.4)", lineHeight: 1.6 }}>
                No worries. Enter your email and we&apos;ll send you a reset link.
              </p>
            </div>

            {/* Form */}
            <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "18px" }}>
              <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                <label
                  style={{
                    fontSize: "0.78rem",
                    fontWeight: 400,
                    letterSpacing: "0.08em",
                    textTransform: "uppercase",
                    color: "rgba(255,255,255,0.45)",
                    fontFamily: "var(--font-hero-mono)",
                  }}
                >
                  Email address
                </label>
                <input
                  type="email"
                  placeholder="you@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  onFocus={() => setFocused(true)}
                  onBlur={() => setFocused(false)}
                  required
                  style={{
                    background: "rgba(255,255,255,0.04)",
                    border: focused ? "1px solid rgba(255,255,255,0.3)" : "1px solid rgba(255,255,255,0.1)",
                    borderRadius: "6px",
                    padding: "13px 16px",
                    color: "white",
                    fontSize: "0.92rem",
                    fontFamily: "inherit",
                    outline: "none",
                    transition: "border-color 0.25s ease, box-shadow 0.25s ease",
                    boxShadow: focused ? "0 0 0 3px rgba(255,255,255,0.06)" : "none",
                    width: "100%",
                    boxSizing: "border-box",
                  }}
                />
              </div>

              <button
                type="submit"
                disabled={loading}
                style={{
                  marginTop: "4px",
                  padding: "14px",
                  borderRadius: "6px",
                  background: loading ? "rgba(255,255,255,0.45)" : "#fff",
                  border: "none",
                  color: "#060609",
                  fontSize: "0.95rem",
                  fontWeight: 600,
                  fontFamily: "inherit",
                  cursor: loading ? "not-allowed" : "pointer",
                  letterSpacing: "0.02em",
                  transition: "transform 0.2s ease, box-shadow 0.2s ease",
                  boxShadow: loading ? "none" : "0 4px 24px rgba(255,255,255,0.1)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: "8px",
                }}
                onMouseEnter={(e) => {
                  if (!loading) {
                    (e.currentTarget as HTMLButtonElement).style.transform = "translateY(-1px)";
                    (e.currentTarget as HTMLButtonElement).style.boxShadow = "0 8px 32px rgba(255,255,255,0.15)";
                  }
                }}
                onMouseLeave={(e) => {
                  (e.currentTarget as HTMLButtonElement).style.transform = "translateY(0)";
                  (e.currentTarget as HTMLButtonElement).style.boxShadow = loading
                    ? "none"
                    : "0 4px 24px rgba(255,255,255,0.1)";
                }}
              >
                {loading ? (
                  <>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" style={{ animation: "spin 0.8s linear infinite" }}>
                      <circle cx="12" cy="12" r="10" stroke="rgba(6,6,9,0.25)" strokeWidth="2" />
                      <path d="M12 2a10 10 0 0 1 10 10" stroke="#060609" strokeWidth="2" strokeLinecap="round" />
                    </svg>
                    Sending…
                  </>
                ) : (
                  "Send reset link"
                )}
              </button>
            </form>

            <p style={{ textAlign: "center", marginTop: "24px", fontSize: "0.85rem", color: "rgba(255,255,255,0.35)" }}>
              Remember it?{" "}
              <Link
                href="/login"
                style={{ color: "rgba(255,255,255,0.7)", textDecoration: "none", fontWeight: 600 }}
                onMouseEnter={(e) => (e.currentTarget.style.color = "white")}
                onMouseLeave={(e) => (e.currentTarget.style.color = "rgba(255,255,255,0.7)")}
              >
                Sign in
              </Link>
            </p>
          </>
        ) : (
          /* Success state */
          <div style={{ textAlign: "center" }}>
            <div
              style={{
                width: "56px",
                height: "56px",
                borderRadius: "50%",
                background: "rgba(255,255,255,0.05)",
                border: "1px solid rgba(255,255,255,0.1)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                margin: "0 auto 24px",
              }}
            >
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                <path d="M20 6L9 17l-5-5" stroke="rgba(255,255,255,0.7)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <h2 style={{ fontSize: "1.4rem", fontWeight: 700, color: "white", marginBottom: "10px" }}>
              Check your inbox
            </h2>
            <p style={{ fontSize: "0.875rem", color: "rgba(255,255,255,0.45)", lineHeight: 1.6, marginBottom: "28px" }}>
              We sent a reset link to{" "}
              <span style={{ color: "rgba(255,255,255,0.7)", fontWeight: 600 }}>{email}</span>.
              <br />Check your spam if you don&apos;t see it.
            </p>
            <Link
              href="/login"
              style={{
                display: "inline-block",
                padding: "12px 32px",
                borderRadius: "6px",
                background: "#fff",
                color: "#060609",
                textDecoration: "none",
                fontSize: "0.92rem",
                fontWeight: 600,
                fontFamily: "inherit",
                boxShadow: "0 4px 24px rgba(255,255,255,0.1)",
                transition: "transform 0.2s ease, box-shadow 0.2s ease",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.transform = "translateY(-1px)";
                e.currentTarget.style.boxShadow = "0 8px 32px rgba(255,255,255,0.15)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.transform = "translateY(0)";
                e.currentTarget.style.boxShadow = "0 4px 24px rgba(255,255,255,0.1)";
              }}
            >
              Back to sign in
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}
