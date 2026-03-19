"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

function BackgroundGradient() {
  return (
    <div
      aria-hidden
      style={{
        position: "fixed",
        inset: 0,
        pointerEvents: "none",
        zIndex: 0,
        overflow: "hidden",
      }}
    >
      <svg
        viewBox="0 0 1200 900"
        fill="none"
        preserveAspectRatio="xMidYMid slice"
        style={{ position: "absolute", width: "100%", height: "100%", top: "-10%", left: 0 }}
      >
        <defs>
          <filter id="su_blur_a" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="90" />
          </filter>
          <filter id="su_blur_b" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="110" />
          </filter>
          <filter id="su_blur_c" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="120" />
          </filter>
          <radialGradient id="su_radial_dark" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#3F18BF" />
            <stop offset="100%" stopColor="#141414" stopOpacity="0" />
          </radialGradient>
        </defs>
        <g filter="url(#su_blur_c)">
          <ellipse cx="600" cy="500" rx="420" ry="230" fill="url(#su_radial_dark)" />
        </g>
        <g filter="url(#su_blur_b)">
          <ellipse cx="600" cy="340" rx="380" ry="210" fill="#7F57F9" fillOpacity="0.7" />
        </g>
        <g filter="url(#su_blur_a)">
          <ellipse cx="600" cy="210" rx="320" ry="170" fill="#CDBCFF" fillOpacity="0.55" />
        </g>
      </svg>
    </div>
  );
}

function InputField({
  label,
  type,
  placeholder,
  value,
  onChange,
}: {
  label: string;
  type: string;
  placeholder: string;
  value: string;
  onChange: (v: string) => void;
}) {
  const [focused, setFocused] = useState(false);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
      <label
        style={{
          fontSize: "0.78rem",
          fontWeight: 400,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "rgba(255,255,255,0.45)",
          fontFamily: "inherit",
        }}
      >
        {label}
      </label>
      <input
        type={type}
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        style={{
          background: "rgba(255,255,255,0.04)",
          border: focused
            ? "1px solid rgba(127,87,249,0.7)"
            : "1px solid rgba(255,255,255,0.1)",
          borderRadius: "10px",
          padding: "13px 16px",
          color: "white",
          fontSize: "0.92rem",
          fontFamily: "inherit",
          outline: "none",
          transition: "border-color 0.25s ease, box-shadow 0.25s ease",
          boxShadow: focused
            ? "0 0 0 3px rgba(127,87,249,0.15)"
            : "none",
          width: "100%",
          boxSizing: "border-box",
        }}
        autoComplete={type === "password" ? "new-password" : "off"}
      />
    </div>
  );
}

export default function SignUpPage() {
  const router = useRouter();
  const [form, setForm] = useState({ name: "", email: "", password: "", confirm: "" });
  const [loading, setLoading] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setTimeout(() => {
      setLoading(false);
      router.push("/books");
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

      {/* Back to home */}
      <Link
        href="/"
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
        <div style={{ width: 110, height: 32, overflow: "hidden", display: "flex", alignItems: "center", justifyContent: "center" }}>
          <img src="/logo.png" alt="MindSync" style={{ height: 70, width: 154, objectFit: "contain", flexShrink: 0 }} />
        </div>
      </Link>

      {/* Card */}
      <div
        style={{
          position: "relative",
          zIndex: 10,
          width: "100%",
          maxWidth: "420px",
          background: "rgba(21,25,41,0.75)",
          backdropFilter: "blur(24px)",
          border: "1px solid rgba(255,255,255,0.08)",
          borderRadius: "20px",
          padding: "40px 36px",
          boxShadow: "0 32px 80px rgba(0,0,0,0.5), 0 0 0 1px rgba(127,87,249,0.08)",
        }}
      >
        {/* Header */}
        <div style={{ marginBottom: "32px" }}>
          <p
            style={{
              fontSize: "0.75rem",
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: "rgba(127,87,249,0.9)",
              marginBottom: "10px",
              fontWeight: 400,
            }}
          >
            Get started
          </p>
          <h1
            style={{
              fontSize: "1.75rem",
              fontWeight: 700,
              color: "white",
              lineHeight: 1.2,
              margin: 0,
            }}
          >
            Create your account
          </h1>
          <p style={{ marginTop: "8px", fontSize: "0.875rem", color: "rgba(255,255,255,0.4)", lineHeight: 1.5 }}>
            Start learning smarter with MindSync.
          </p>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "18px" }}>
          <InputField
            label="Full name"
            type="text"
            placeholder="Jane Doe"
            value={form.name}
            onChange={(v) => setForm({ ...form, name: v })}
          />
          <InputField
            label="Email"
            type="email"
            placeholder="you@example.com"
            value={form.email}
            onChange={(v) => setForm({ ...form, email: v })}
          />
          <InputField
            label="Password"
            type="password"
            placeholder="Min. 8 characters"
            value={form.password}
            onChange={(v) => setForm({ ...form, password: v })}
          />
          <InputField
            label="Confirm password"
            type="password"
            placeholder="Repeat your password"
            value={form.confirm}
            onChange={(v) => setForm({ ...form, confirm: v })}
          />

          {/* Submit */}
          <button
            type="submit"
            disabled={loading}
            style={{
              marginTop: "6px",
              padding: "14px",
              borderRadius: "10px",
              background: loading
                ? "rgba(115,82,221,0.5)"
                : "linear-gradient(135deg, #7352DD 0%, #9187E0 100%)",
              border: "none",
              color: "white",
              fontSize: "0.95rem",
              fontWeight: 600,
              fontFamily: "inherit",
              cursor: loading ? "not-allowed" : "pointer",
              letterSpacing: "0.02em",
              transition: "transform 0.2s ease, box-shadow 0.2s ease, background 0.2s ease",
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
                Creating account…
              </>
            ) : (
              "Create account"
            )}
          </button>
        </form>

        {/* Divider */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "12px",
            margin: "24px 0",
          }}
        >
          <div style={{ flex: 1, height: "1px", background: "rgba(255,255,255,0.08)" }} />
          <span style={{ fontSize: "0.75rem", color: "rgba(255,255,255,0.3)" }}>or</span>
          <div style={{ flex: 1, height: "1px", background: "rgba(255,255,255,0.08)" }} />
        </div>

        {/* Footer link */}
        <p style={{ textAlign: "center", fontSize: "0.85rem", color: "rgba(255,255,255,0.35)", margin: 0 }}>
          Already have an account?{" "}
          <Link
            href="/login"
            style={{
              color: "rgba(205,188,255,0.85)",
              textDecoration: "none",
              fontWeight: 600,
              transition: "color 0.2s",
            }}
            onMouseEnter={(e) => (e.currentTarget.style.color = "white")}
            onMouseLeave={(e) => (e.currentTarget.style.color = "rgba(205,188,255,0.85)")}
          >
            Sign in
          </Link>
        </p>
      </div>

    </div>
  );
}
