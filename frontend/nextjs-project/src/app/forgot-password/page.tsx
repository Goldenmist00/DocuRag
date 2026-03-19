"use client";

import React, { useState } from "react";
import Link from "next/link";

function BackgroundGradient() {
  return (
    <div
      aria-hidden
      style={{ position: "fixed", inset: 0, pointerEvents: "none", zIndex: 0, overflow: "hidden" }}
    >
      <svg
        viewBox="0 0 1200 900"
        fill="none"
        preserveAspectRatio="xMidYMid slice"
        style={{ position: "absolute", width: "100%", height: "100%", top: "-10%", left: 0 }}
      >
        <defs>
          <filter id="fp_blur_a" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="90" />
          </filter>
          <filter id="fp_blur_b" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="110" />
          </filter>
          <filter id="fp_blur_c" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="120" />
          </filter>
          <radialGradient id="fp_radial_dark" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#3F18BF" />
            <stop offset="100%" stopColor="#141414" stopOpacity="0" />
          </radialGradient>
        </defs>
        <g filter="url(#fp_blur_c)">
          <ellipse cx="600" cy="500" rx="420" ry="230" fill="url(#fp_radial_dark)" />
        </g>
        <g filter="url(#fp_blur_b)">
          <ellipse cx="600" cy="340" rx="380" ry="210" fill="#7F57F9" fillOpacity="0.7" />
        </g>
        <g filter="url(#fp_blur_a)">
          <ellipse cx="600" cy="210" rx="320" ry="170" fill="#CDBCFF" fillOpacity="0.55" />
        </g>
      </svg>
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
        width: "100%",
        background: "#141414",
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
          color: "rgba(255,255,255,0.5)",
          textDecoration: "none",
          fontSize: "0.85rem",
          fontFamily: "inherit",
          transition: "color 0.2s",
        }}
        onMouseEnter={(e) => (e.currentTarget.style.color = "white")}
        onMouseLeave={(e) => (e.currentTarget.style.color = "rgba(255,255,255,0.5)")}
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
          background: "rgba(21,25,41,0.75)",
          backdropFilter: "blur(24px)",
          border: "1px solid rgba(255,255,255,0.08)",
          borderRadius: "20px",
          padding: "40px 36px",
          boxShadow: "0 32px 80px rgba(0,0,0,0.5), 0 0 0 1px rgba(127,87,249,0.08)",
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
                  borderRadius: "12px",
                  background: "rgba(127,87,249,0.12)",
                  border: "1px solid rgba(127,87,249,0.25)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  marginBottom: "20px",
                }}
              >
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
                  <rect x="3" y="11" width="18" height="11" rx="2" stroke="rgba(205,188,255,0.8)" strokeWidth="1.5" />
                  <path d="M7 11V7a5 5 0 0 1 10 0v4" stroke="rgba(205,188,255,0.8)" strokeWidth="1.5" strokeLinecap="round" />
                </svg>
              </div>
              <p style={{ fontSize: "0.75rem", letterSpacing: "0.12em", textTransform: "uppercase", color: "rgba(127,87,249,0.9)", marginBottom: "10px", fontWeight: 400 }}>
                Account recovery
              </p>
              <h1 style={{ fontSize: "1.75rem", fontWeight: 700, color: "white", lineHeight: 1.2, margin: 0 }}>
                Forgot password?
              </h1>
              <p style={{ marginTop: "8px", fontSize: "0.875rem", color: "rgba(255,255,255,0.4)", lineHeight: 1.6 }}>
                No worries. Enter your email and we&apos;ll send you a reset link.
              </p>
            </div>

            {/* Form */}
            <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "18px" }}>
              <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                <label style={{ fontSize: "0.78rem", fontWeight: 400, letterSpacing: "0.08em", textTransform: "uppercase", color: "rgba(255,255,255,0.45)", fontFamily: "inherit" }}>
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
                    border: focused ? "1px solid rgba(127,87,249,0.7)" : "1px solid rgba(255,255,255,0.1)",
                    borderRadius: "10px",
                    padding: "13px 16px",
                    color: "white",
                    fontSize: "0.92rem",
                    fontFamily: "inherit",
                    outline: "none",
                    transition: "border-color 0.25s ease, box-shadow 0.25s ease",
                    boxShadow: focused ? "0 0 0 3px rgba(127,87,249,0.15)" : "none",
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
                  borderRadius: "10px",
                  background: loading ? "rgba(115,82,221,0.5)" : "linear-gradient(135deg, #7352DD 0%, #9187E0 100%)",
                  border: "none",
                  color: "white",
                  fontSize: "0.95rem",
                  fontWeight: 600,
                  fontFamily: "inherit",
                  cursor: loading ? "not-allowed" : "pointer",
                  letterSpacing: "0.02em",
                  transition: "transform 0.2s ease, box-shadow 0.2s ease",
                  boxShadow: loading ? "none" : "0 4px 24px rgba(115,82,221,0.35)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: "8px",
                }}
                onMouseEnter={(e) => {
                  if (!loading) {
                    (e.currentTarget as HTMLButtonElement).style.transform = "translateY(-1px)";
                    (e.currentTarget as HTMLButtonElement).style.boxShadow = "0 8px 32px rgba(115,82,221,0.5)";
                  }
                }}
                onMouseLeave={(e) => {
                  (e.currentTarget as HTMLButtonElement).style.transform = "translateY(0)";
                  (e.currentTarget as HTMLButtonElement).style.boxShadow = "0 4px 24px rgba(115,82,221,0.35)";
                }}
              >
                {loading ? (
                  <>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" style={{ animation: "spin 0.8s linear infinite" }}>
                      <circle cx="12" cy="12" r="10" stroke="rgba(255,255,255,0.3)" strokeWidth="2" />
                      <path d="M12 2a10 10 0 0 1 10 10" stroke="white" strokeWidth="2" strokeLinecap="round" />
                    </svg>
                    Sending…
                  </>
                ) : "Send reset link"}
              </button>
            </form>

            <p style={{ textAlign: "center", marginTop: "24px", fontSize: "0.85rem", color: "rgba(255,255,255,0.35)" }}>
              Remember it?{" "}
              <Link
                href="/login"
                style={{ color: "rgba(205,188,255,0.85)", textDecoration: "none", fontWeight: 600 }}
                onMouseEnter={(e) => (e.currentTarget.style.color = "white")}
                onMouseLeave={(e) => (e.currentTarget.style.color = "rgba(205,188,255,0.85)")}
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
                background: "rgba(127,87,249,0.12)",
                border: "1px solid rgba(127,87,249,0.3)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                margin: "0 auto 24px",
              }}
            >
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                <path d="M20 6L9 17l-5-5" stroke="rgba(205,188,255,0.9)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <h2 style={{ fontSize: "1.4rem", fontWeight: 700, color: "white", marginBottom: "10px" }}>
              Check your inbox
            </h2>
            <p style={{ fontSize: "0.875rem", color: "rgba(255,255,255,0.45)", lineHeight: 1.6, marginBottom: "28px" }}>
              We sent a reset link to{" "}
              <span style={{ color: "rgba(205,188,255,0.85)", fontWeight: 600 }}>{email}</span>.
              <br />Check your spam if you don&apos;t see it.
            </p>
            <Link
              href="/login"
              style={{
                display: "inline-block",
                padding: "12px 32px",
                borderRadius: "10px",
                background: "linear-gradient(135deg, #7352DD 0%, #9187E0 100%)",
                color: "white",
                textDecoration: "none",
                fontSize: "0.92rem",
                fontWeight: 600,
                fontFamily: "inherit",
                boxShadow: "0 4px 24px rgba(115,82,221,0.35)",
                transition: "transform 0.2s ease",
              }}
              onMouseEnter={(e) => (e.currentTarget.style.transform = "translateY(-1px)")}
              onMouseLeave={(e) => (e.currentTarget.style.transform = "translateY(0)")}
            >
              Back to sign in
            </Link>
          </div>
        )}
      </div>

    </div>
  );
}
