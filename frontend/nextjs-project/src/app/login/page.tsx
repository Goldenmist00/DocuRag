"use client";

import React, { useState, useCallback } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { authClient } from "@/lib/auth/client";

function BackgroundGradient() {
  return (
    <div aria-hidden style={{ position: "fixed", inset: 0, pointerEvents: "none", zIndex: 0 }}>
      <div style={{ position: "absolute", top: "30%", left: "50%", transform: "translateX(-50%)", width: 600, height: 600, borderRadius: "50%", background: "radial-gradient(circle, rgba(255,255,255,0.03) 0%, transparent 70%)", filter: "blur(40px)" }} />
    </div>
  );
}

function InputField({
  label, type, placeholder, value, onChange,
}: {
  label: string; type: string; placeholder: string; value: string; onChange: (v: string) => void;
}) {
  const [focused, setFocused] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const isPassword = type === "password";
  const inputType = isPassword && showPassword ? "text" : type;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
      <label style={{ fontSize: "0.78rem", fontWeight: 400, letterSpacing: "0.08em", textTransform: "uppercase", color: "rgba(255,255,255,0.45)", fontFamily: "var(--font-hero-mono)" }}>
        {label}
      </label>
      <div style={{ position: "relative" }}>
        <input
          type={inputType}
          placeholder={placeholder}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          style={{
            width: "100%",
            background: "rgba(255,255,255,0.04)",
            border: focused ? "1px solid rgba(255,255,255,0.3)" : "1px solid rgba(255,255,255,0.1)",
            borderRadius: "6px",
            padding: isPassword ? "13px 44px 13px 16px" : "13px 16px",
            color: "white",
            fontSize: "0.92rem",
            fontFamily: "inherit",
            outline: "none",
            transition: "border-color 0.25s ease, box-shadow 0.25s ease",
            boxShadow: focused ? "0 0 0 3px rgba(255,255,255,0.06)" : "none",
            boxSizing: "border-box",
          }}
          autoComplete={isPassword ? "current-password" : "email"}
        />
        {isPassword && (
          <button
            type="button"
            onClick={() => setShowPassword(!showPassword)}
            aria-label={showPassword ? "Hide password" : "Show password"}
            style={{ position: "absolute", right: "14px", top: "50%", transform: "translateY(-50%)", background: "none", border: "none", cursor: "pointer", padding: 0, color: "rgba(255,255,255,0.3)", display: "flex", alignItems: "center", transition: "color 0.2s" }}
            onMouseEnter={(e) => (e.currentTarget.style.color = "rgba(255,255,255,0.7)")}
            onMouseLeave={(e) => (e.currentTarget.style.color = "rgba(255,255,255,0.3)")}
          >
            {showPassword ? (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                <line x1="1" y1="1" x2="23" y2="23" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
              </svg>
            ) : (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.5"/>
              </svg>
            )}
          </button>
        )}
      </div>
    </div>
  );
}

function validate(email: string, password: string): string | null {
  if (!email) return "Email is required.";
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return "Enter a valid email address.";
  if (!password) return "Password is required.";
  return null;
}

export default function LoginPage() {
  const router = useRouter();
  const [form, setForm] = useState({ email: "", password: "" });
  const [loading, setLoading] = useState(false);
  const [oauthLoading, setOauthLoading] = useState(false);
  const [remember, setRemember] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    const validationError = validate(form.email, form.password);
    if (validationError) { setError(validationError); return; }
    setLoading(true);
    const { error: signInError } = await authClient.signIn.email({
      email: form.email,
      password: form.password,
      rememberMe: remember,
    });
    setLoading(false);
    if (signInError) {
      setError(signInError.message || "Failed to sign in. Try again.");
    } else {
      router.push("/books");
    }
  }, [form, remember, router]);

  const handleGoogle = useCallback(async () => {
    setOauthLoading(true);
    try {
      await authClient.signIn.social({ provider: "google", callbackURL: "/books" });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Google sign-in failed.");
      setOauthLoading(false);
    }
  }, []);

  return (
    <div style={{ minHeight: "100vh", width: "100%", background: "#060609", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "var(--font-inria), 'Inria Sans', sans-serif", position: "relative", padding: "24px" }}>
      <BackgroundGradient />

      <Link href="/"
        style={{ position: "fixed", top: "24px", left: "32px", zIndex: 20, display: "flex", alignItems: "center", gap: "8px", color: "rgba(255,255,255,0.5)", textDecoration: "none", fontSize: "0.85rem", fontFamily: "inherit", transition: "color 0.2s" }}
        onMouseEnter={(e) => (e.currentTarget.style.color = "white")}
        onMouseLeave={(e) => (e.currentTarget.style.color = "rgba(255,255,255,0.5)")}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
          <path d="M19 12H5M5 12L12 19M5 12L12 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <div style={{ width: 110, height: 32, overflow: "hidden", display: "flex", alignItems: "center", justifyContent: "center" }}>
          <img src="/logo.png" alt="DocuRag" style={{ height: 70, width: 154, objectFit: "contain", flexShrink: 0 }} />
        </div>
      </Link>

      <div style={{ position: "relative", zIndex: 10, width: "100%", maxWidth: "400px", background: "rgba(6,6,9,0.85)", backdropFilter: "blur(24px)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: "12px", padding: "40px 36px", boxShadow: "0 32px 80px rgba(0,0,0,0.5)" }}>
        <div style={{ marginBottom: "32px" }}>
          <p style={{ fontSize: "0.75rem", letterSpacing: "0.12em", textTransform: "uppercase", color: "rgba(255,255,255,0.4)", marginBottom: "10px", fontWeight: 400, fontFamily: "var(--font-hero-mono)" }}>
            Welcome back
          </p>
          <h1 style={{ fontSize: "1.75rem", fontWeight: 700, color: "white", lineHeight: 1.2, margin: 0, fontFamily: "var(--font-hero-display)" }}>
            Sign in to DocuRag
          </h1>
          <p style={{ marginTop: "8px", fontSize: "0.875rem", color: "rgba(255,255,255,0.4)", lineHeight: 1.5 }}>
            Continue your learning journey.
          </p>
        </div>

        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "18px" }} noValidate>
          <InputField label="Email" type="email" placeholder="you@example.com" value={form.email} onChange={(v) => setForm({ ...form, email: v })} />
          <InputField label="Password" type="password" placeholder="Your password" value={form.password} onChange={(v) => setForm({ ...form, password: v })} />

          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <label style={{ display: "flex", alignItems: "center", gap: "8px", cursor: "pointer", fontSize: "0.82rem", color: "rgba(255,255,255,0.4)", userSelect: "none", fontFamily: "var(--font-hero-mono)" }}>
              <div
                role="checkbox"
                aria-checked={remember}
                tabIndex={0}
                onClick={() => setRemember(!remember)}
                onKeyDown={(e) => e.key === " " && setRemember(!remember)}
                style={{ width: "16px", height: "16px", borderRadius: "4px", border: remember ? "1px solid rgba(255,255,255,0.5)" : "1px solid rgba(255,255,255,0.2)", background: remember ? "rgba(255,255,255,0.1)" : "transparent", display: "flex", alignItems: "center", justifyContent: "center", transition: "all 0.2s ease", flexShrink: 0 }}
              >
                {remember && (
                  <svg width="10" height="10" viewBox="0 0 12 12" fill="none">
                    <path d="M2 6l3 3 5-5" stroke="rgba(255,255,255,0.8)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                )}
              </div>
              Remember me
            </label>
            <Link href="/forgot-password"
              style={{ fontSize: "0.82rem", color: "rgba(255,255,255,0.5)", textDecoration: "none", transition: "color 0.2s" }}
              onMouseEnter={(e) => (e.currentTarget.style.color = "white")}
              onMouseLeave={(e) => (e.currentTarget.style.color = "rgba(255,255,255,0.5)")}
            >
              Forgot password?
            </Link>
          </div>

          {error && <p role="alert" style={{ fontSize: "0.82rem", color: "#ff6b6b", textAlign: "center", margin: 0 }}>{error}</p>}

          <button type="submit" disabled={loading}
            style={{ marginTop: "4px", padding: "14px", borderRadius: "6px", background: loading ? "rgba(255,255,255,0.5)" : "#fff", border: "none", color: "#060609", fontSize: "0.95rem", fontWeight: 600, fontFamily: "inherit", cursor: loading ? "not-allowed" : "pointer", letterSpacing: "0.02em", transition: "transform 0.2s ease, box-shadow 0.2s ease", boxShadow: loading ? "none" : "0 4px 24px rgba(255,255,255,0.1)", display: "flex", alignItems: "center", justifyContent: "center", gap: "8px" }}
            onMouseEnter={(e) => { if (!loading) { (e.currentTarget as HTMLButtonElement).style.transform = "translateY(-1px)"; (e.currentTarget as HTMLButtonElement).style.boxShadow = "0 8px 32px rgba(255,255,255,0.15)"; } }}
            onMouseLeave={(e) => { const b = e.currentTarget as HTMLButtonElement; b.style.transform = "translateY(0)"; b.style.boxShadow = b.disabled ? "none" : "0 4px 24px rgba(255,255,255,0.1)"; }}
          >
            {loading ? (
              <>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" style={{ animation: "spin 0.8s linear infinite" }}>
                  <circle cx="12" cy="12" r="10" stroke="rgba(6,6,9,0.2)" strokeWidth="2" />
                  <path d="M12 2a10 10 0 0 1 10 10" stroke="#060609" strokeWidth="2" strokeLinecap="round" />
                </svg>
                Signing in…
              </>
            ) : "Sign in"}
          </button>
        </form>

        <div style={{ display: "flex", alignItems: "center", gap: "12px", margin: "24px 0" }}>
          <div style={{ flex: 1, height: "1px", background: "rgba(255,255,255,0.08)" }} />
          <span style={{ fontSize: "0.75rem", color: "rgba(255,255,255,0.3)" }}>or</span>
          <div style={{ flex: 1, height: "1px", background: "rgba(255,255,255,0.08)" }} />
        </div>

        <button type="button" onClick={handleGoogle} disabled={oauthLoading}
          style={{ width: "100%", padding: "13px", borderRadius: "6px", background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.12)", color: "rgba(255,255,255,0.85)", fontSize: "0.92rem", fontFamily: "inherit", cursor: oauthLoading ? "not-allowed" : "pointer", display: "flex", alignItems: "center", justifyContent: "center", gap: "10px", transition: "background 0.2s, border-color 0.2s", marginBottom: "20px" }}
          onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "rgba(255,255,255,0.09)"; }}
          onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "rgba(255,255,255,0.05)"; }}
        >
          <svg width="18" height="18" viewBox="0 0 24 24">
            <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
            <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
            <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z" fill="#FBBC05"/>
            <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
          </svg>
          {oauthLoading ? "Redirecting…" : "Continue with Google"}
        </button>

        <p style={{ textAlign: "center", fontSize: "0.85rem", color: "rgba(255,255,255,0.35)", margin: 0 }}>
          Don&apos;t have an account?{" "}
          <Link href="/signup"
            style={{ color: "rgba(255,255,255,0.7)", textDecoration: "none", fontWeight: 600, transition: "color 0.2s" }}
            onMouseEnter={(e) => (e.currentTarget.style.color = "white")}
            onMouseLeave={(e) => (e.currentTarget.style.color = "rgba(255,255,255,0.7)")}
          >
            Create one
          </Link>
        </p>
      </div>
    </div>
  );
}
