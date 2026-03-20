"use client";

import { createContext, useCallback, useContext, useState, useRef, type ReactNode } from "react";

type ToastType = "success" | "error" | "info";

interface Toast {
  id: number;
  message: string;
  type: ToastType;
  exiting: boolean;
}

interface ToastContextValue {
  toast: (message: string, type?: ToastType) => void;
  success: (message: string) => void;
  error: (message: string) => void;
  info: (message: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const DISMISS_MS = 4000;
const EXIT_MS = 300;

const ICON_PATHS: Record<ToastType, string> = {
  success: "M5 13l4 4L19 7",
  error: "M6 18L18 6M6 6l12 12",
  info: "M12 8v4m0 4h.01M12 2a10 10 0 100 20 10 10 0 000-20z",
};

const COLORS: Record<ToastType, { bg: string; border: string; icon: string; text: string }> = {
  success: {
    bg: "rgba(34,197,94,0.12)",
    border: "rgba(34,197,94,0.25)",
    icon: "rgba(134,239,172,0.9)",
    text: "rgba(220,252,231,0.95)",
  },
  error: {
    bg: "rgba(239,68,68,0.12)",
    border: "rgba(239,68,68,0.25)",
    icon: "rgba(252,165,165,0.9)",
    text: "rgba(254,226,226,0.95)",
  },
  info: {
    bg: "rgba(91,138,240,0.12)",
    border: "rgba(91,138,240,0.25)",
    icon: "rgba(140,175,255,0.9)",
    text: "rgba(219,234,254,0.95)",
  },
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const idRef = useRef(0);

  const addToast = useCallback((message: string, type: ToastType = "info") => {
    const id = ++idRef.current;
    setToasts(prev => [...prev, { id, message, type, exiting: false }]);

    setTimeout(() => {
      setToasts(prev => prev.map(t => (t.id === id ? { ...t, exiting: true } : t)));
      setTimeout(() => {
        setToasts(prev => prev.filter(t => t.id !== id));
      }, EXIT_MS);
    }, DISMISS_MS);
  }, []);

  const ctx: ToastContextValue = {
    toast: addToast,
    success: useCallback((m: string) => addToast(m, "success"), [addToast]),
    error: useCallback((m: string) => addToast(m, "error"), [addToast]),
    info: useCallback((m: string) => addToast(m, "info"), [addToast]),
  };

  return (
    <ToastContext.Provider value={ctx}>
      {children}

      {/* Toast container */}
      <div
        style={{
          position: "fixed",
          bottom: 20,
          right: 20,
          zIndex: 99999,
          display: "flex",
          flexDirection: "column-reverse",
          gap: 8,
          pointerEvents: "none",
        }}
      >
        {toasts.map(t => {
          const c = COLORS[t.type];
          return (
            <div
              key={t.id}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "10px 16px",
                borderRadius: 10,
                background: c.bg,
                border: `1px solid ${c.border}`,
                backdropFilter: "blur(12px)",
                boxShadow: "0 8px 32px rgba(0,0,0,0.4)",
                color: c.text,
                fontSize: "0.82rem",
                fontWeight: 500,
                fontFamily: "var(--font-inria), 'Inria Sans', sans-serif",
                letterSpacing: "-0.01em",
                maxWidth: 360,
                pointerEvents: "auto",
                animation: t.exiting
                  ? `toastExit ${EXIT_MS}ms ease forwards`
                  : `toastEnter 0.25s ease both`,
              }}
            >
              <svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                style={{ flexShrink: 0 }}
              >
                <path
                  d={ICON_PATHS[t.type]}
                  stroke={c.icon}
                  strokeWidth="2.2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
              {t.message}
            </div>
          );
        })}
      </div>

      <style>{`
        @keyframes toastEnter {
          from { opacity: 0; transform: translateY(12px) scale(0.96); }
          to   { opacity: 1; transform: translateY(0) scale(1); }
        }
        @keyframes toastExit {
          from { opacity: 1; transform: translateY(0) scale(1); }
          to   { opacity: 0; transform: translateY(8px) scale(0.96); }
        }
      `}</style>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used within a <ToastProvider>");
  }
  return ctx;
}
