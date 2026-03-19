"use client"

import { useState, useRef, useEffect, Suspense } from "react"
import { motion, useScroll, useTransform, AnimatePresence } from "framer-motion"
import { IntroAnimation } from "./components/landing/intro-animation"
import dynamic from "next/dynamic"
import MagneticCursor from "./components/landing/magnetic-cursor"
import { useRouter } from "next/navigation"

const BrainScene = dynamic(() => import("./components/landing/brain-scene"), {
  ssr: false,
  loading: () => (
    <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{ width: 56, height: 56, border: "1.5px solid #7352DD", borderTopColor: "transparent", borderRadius: "50%", animation: "spin 1s linear infinite" }} />
    </div>
  ),
})

/* ─── Floating 3D Card ─── */
function FloatingCard({ children, style = {} }: { children: React.ReactNode; style?: React.CSSProperties }) {
  const ref = useRef<HTMLDivElement>(null)
  const [visible, setVisible] = useState(false)
  const [tilt, setTilt] = useState({ x: 0, y: 0 })
  useEffect(() => {
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) setVisible(true) }, { threshold: 0.1 })
    if (ref.current) io.observe(ref.current)
    return () => io.disconnect()
  }, [])
  return (
    <motion.div ref={ref} initial={{ opacity: 0, y: 50 }} animate={{ opacity: visible ? 1 : 0, y: visible ? 0 : 50 }}
      transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }} style={{ perspective: 1200, ...style }}
      onMouseMove={(e) => { if (!ref.current) return; const r = ref.current.getBoundingClientRect(); setTilt({ x: (e.clientY - r.top - r.height / 2) / 28, y: (e.clientX - r.left - r.width / 2) / 28 }) }}
      onMouseLeave={() => setTilt({ x: 0, y: 0 })}>
      <motion.div animate={{ rotateX: -tilt.x, rotateY: tilt.y }} transition={{ type: "spring", stiffness: 280, damping: 28 }} style={{ transformStyle: "preserve-3d" }}>
        {children}
      </motion.div>
    </motion.div>
  )
}

/* ─── Story Feature Block ─── */
const cardVariants = {
  hidden: (align: string) => ({ opacity: 0, x: align === "right" ? 70 : -70 }),
  show: { opacity: 1, x: 0, transition: { duration: 0.55, ease: [0.22, 1, 0.36, 1] as const, staggerChildren: 0.09, delayChildren: 0.08 } },
}
const childVariants = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.38, ease: [0.22, 1, 0.36, 1] as const } },
}
const accentVariants = {
  hidden: { scaleY: 0 },
  show: { scaleY: 1, transition: { duration: 0.55, ease: [0.22, 1, 0.36, 1] as const } },
}

function StoryFeatureBlock({ number, icon, title, description, align = "left" }: {
  number: string; icon: React.ReactNode; title: string; description: string; align?: "left" | "right"; index: number
}) {
  return (
    <motion.div custom={align} variants={cardVariants} initial="hidden" whileInView="show"
      viewport={{ once: true, margin: "-60px" }}
      style={{ position: "relative", display: "flex", justifyContent: align === "right" ? "flex-end" : "flex-start" }}>
      <div style={{
        position: "relative", padding: "2.5rem 3rem", borderRadius: "1.5rem", maxWidth: 700, textAlign: align,
        background: "linear-gradient(135deg, rgba(115,82,221,0.09) 0%, rgba(192,132,252,0.04) 100%)",
        backdropFilter: "blur(24px)", border: "1px solid rgba(255,255,255,0.07)",
        boxShadow: "0 12px 40px rgba(0,0,0,0.35), inset 0 1px 0 rgba(255,255,255,0.06)", overflow: "hidden",
      }}>
        {/* top shimmer line */}
        <div style={{ position: "absolute", top: 0, left: "10%", right: "10%", height: 1, background: "linear-gradient(90deg, transparent, rgba(115,82,221,0.5), transparent)" }} />
        {/* side accent */}
        <motion.div variants={accentVariants} style={{
          position: "absolute", top: 0, bottom: 0, [align === "right" ? "right" : "left"]: 0,
          width: 3, borderRadius: 99, background: "linear-gradient(180deg, #7352DD 0%, #C084FC 60%, transparent 100%)", transformOrigin: "top",
        }} />
        {/* number watermark */}
        <motion.span variants={{ hidden: { opacity: 0, scale: 0.85 }, show: { opacity: 0.06, scale: 1, transition: { duration: 0.6 } } }}
          style={{
            position: "absolute", [align === "right" ? "left" : "right"]: -28, top: -12,
            fontSize: "clamp(90px, 13vw, 150px)", fontWeight: 900, lineHeight: 1,
            userSelect: "none", pointerEvents: "none",
            background: "linear-gradient(135deg, #7352DD 0%, #C084FC 100%)",
            WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
          }}>{number}</motion.span>
        <div style={{ position: "relative", zIndex: 1 }}>
          <motion.div variants={childVariants} style={{
            display: "inline-flex", alignItems: "center", gap: 6, padding: "5px 12px",
            borderRadius: 99, marginBottom: "1.25rem", background: "rgba(115,82,221,0.18)", border: "1px solid rgba(115,82,221,0.28)",
          }}>
            <span style={{ color: "#A78BFA", fontSize: "0.68rem", fontWeight: 600, letterSpacing: "0.22em", textTransform: "uppercase" }}>Feature {number}</span>
          </motion.div>
          <motion.div variants={childVariants} style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: "1.1rem", flexDirection: align === "right" ? "row-reverse" : "row" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", width: 52, height: 52, borderRadius: "0.75rem", flexShrink: 0, background: "rgba(115,82,221,0.14)", color: "#A78BFA", border: "1px solid rgba(115,82,221,0.22)" }}>
              {icon}
            </div>
            <h2 style={{ fontSize: "clamp(1.4rem, 2.8vw, 2.1rem)", fontWeight: 700, color: "#fff", lineHeight: 1.2 }}>{title}</h2>
          </motion.div>
          <motion.p variants={childVariants} style={{ fontSize: "1rem", color: "rgba(255,255,255,0.65)", lineHeight: 1.85 }}>{description}</motion.p>
        </div>
        <motion.div variants={{ hidden: { opacity: 0, scale: 0 }, show: { opacity: 1, scale: 1, transition: { duration: 0.3, delay: 0.4 } } }}
          style={{ position: "absolute", bottom: 14, [align === "right" ? "left" : "right"]: 14, width: 24, height: 24,
            borderRight: align === "right" ? "none" : "1.5px solid rgba(115,82,221,0.35)",
            borderLeft: align === "right" ? "1.5px solid rgba(115,82,221,0.35)" : "none",
            borderBottom: "1.5px solid rgba(115,82,221,0.35)" }} />
      </div>
    </motion.div>
  )
}

/* ─── Scroll Indicator ─── */
function ScrollIndicator() {
  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 4.2 }}
      style={{ position: "absolute", bottom: 40, left: "50%", transform: "translateX(-50%)", display: "flex", flexDirection: "column", alignItems: "center", gap: 8 }}>
      <span style={{ fontSize: "0.6rem", letterSpacing: "0.28em", textTransform: "uppercase", color: "rgba(255,255,255,0.25)" }}>Scroll</span>
      <motion.div animate={{ borderColor: ["rgba(255,255,255,0.15)", "rgba(115,82,221,0.7)", "rgba(255,255,255,0.15)"] }}
        transition={{ duration: 2, repeat: Infinity }}
        style={{ width: 22, height: 36, borderRadius: 99, border: "1px solid rgba(255,255,255,0.15)", display: "flex", justifyContent: "center", paddingTop: 5 }}>
        <motion.div animate={{ y: [0, 12, 0] }} transition={{ duration: 1.4, repeat: Infinity, ease: "easeInOut" }}
          style={{ width: 3, height: 7, borderRadius: 99, background: "linear-gradient(180deg,#A78BFA,#7352DD)" }} />
      </motion.div>
    </motion.div>
  )
}

/* ─── Section Label ─── */
function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <motion.div initial={{ opacity: 0, y: 12 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ duration: 0.5 }}
      style={{ display: "inline-flex", alignItems: "center", gap: 10, marginBottom: "1.25rem" }}>
      <div style={{ width: 20, height: 1, background: "linear-gradient(90deg, transparent, #7352DD)" }} />
      <span style={{ fontSize: "0.7rem", fontWeight: 600, letterSpacing: "0.22em", textTransform: "uppercase", color: "#A78BFA" }}>{children}</span>
      <div style={{ width: 20, height: 1, background: "linear-gradient(90deg, #7352DD, transparent)" }} />
    </motion.div>
  )
}

/* ─── Stat Card ─── */
function StatCard({ value, label, delay }: { value: string; label: string; delay: number }) {
  return (
    <motion.div initial={{ opacity: 0, y: 24 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ duration: 0.5, delay }}
      style={{ textAlign: "center", padding: "1.75rem 2rem", borderRadius: "1rem", background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)", flex: 1, minWidth: 140 }}>
      <div style={{ fontSize: "clamp(1.8rem, 3vw, 2.5rem)", fontWeight: 800, background: "linear-gradient(135deg,#A78BFA,#7352DD)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", lineHeight: 1, marginBottom: 8 }}>{value}</div>
      <div style={{ fontSize: "0.82rem", color: "rgba(255,255,255,0.4)", letterSpacing: "0.04em" }}>{label}</div>
    </motion.div>
  )
}

/* ─── Main Page ─── */
export default function Home() {
  const [showContent, setShowContent] = useState(false)
  const [transitioning, setTransitioning] = useState(false)
  const [btnPos, setBtnPos] = useState({ x: "50%", y: "50%" })
  const router = useRouter()
  const { scrollYProgress } = useScroll()

  const handleTryMindSync = (e: React.MouseEvent<HTMLButtonElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    setBtnPos({
      x: `${rect.left + rect.width / 2}px`,
      y: `${rect.top + rect.height / 2}px`,
    })
    setTransitioning(true)
    setTimeout(() => router.push("/signup"), 600)
  }
  const heroOpacity = useTransform(scrollYProgress, [0, 0.16], [1, 0])
  const heroScale   = useTransform(scrollYProgress, [0, 0.16], [1, 0.94])
  const heroY       = useTransform(scrollYProgress, [0, 0.16], [0, -60])

  const features = [
    { icon: <svg width="22" height="22" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M6.75 3h10.5M6.75 3a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 006.75 21h10.5a2.25 2.25 0 002.25-2.25V5.25A2.25 2.25 0 0017.25 3M6.75 3H5.25M17.25 3h1.5M9 9h6M9 12h6M9 15h4" /></svg>, title: "Smart Flashcards Generator", description: "Automatically converts textbook content into interactive flashcards for quick revision and better retention." },
    { icon: <svg width="22" height="22" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.129.166 2.27.293 3.423.379.35.026.67.21.865.501L12 21l2.755-4.133a1.14 1.14 0 01.865-.501 48.172 48.172 0 003.423-.379c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018z" /></svg>, title: "Mind Mapping", description: "Transforms key concepts into visual mind maps to help users understand relationships and topic structure easily." },
    { icon: <svg width="22" height="22" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M9 12h3.75M9 15h3.75M9 18h3.75m3 .75H18a2.25 2.25 0 002.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 00-1.123-.08m-5.801 0c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 00.75-.75 2.25 2.25 0 00-.1-.664m-5.8 0A2.251 2.251 0 0113.5 2.25H15c1.012 0 1.867.668 2.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m0 0H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V9.375c0-.621-.504-1.125-1.125-1.125H8.25zM6.75 12h.008v.008H6.75V12zm0 3h.008v.008H6.75V15zm0 3h.008v.008H6.75V18z" /></svg>, title: "Summary Mode", description: "Generates concise, structured summaries of topics directly from textbook content for fast learning." },
    { icon: <svg width="22" height="22" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 15.803a7.5 7.5 0 0010.607 10.607z" /></svg>, title: "Smart Textbook Search", description: "Uses semantic AI search to instantly find the most relevant textbook sections for any question." },
    { icon: <svg width="22" height="22" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" /></svg>, title: "Verified Answers with Citations", description: "Every response includes exact section names and page numbers for reliable, verifiable learning." },
    { icon: <svg width="22" height="22" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M10.5 1.5H8.25A2.25 2.25 0 006 3.75v16.5a2.25 2.25 0 002.25 2.25h7.5A2.25 2.25 0 0018 20.25V3.75a2.25 2.25 0 00-2.25-2.25H13.5m-3 0V3h3V1.5m-3 0h3m-3 18.75h3" /></svg>, title: "Study-Friendly Interface", description: "Designed for students with a clean, intuitive layout that makes exploring and revising topics effortless." },
  ]

  return (
    <>
      <MagneticCursor />
      <IntroAnimation onComplete={() => setShowContent(true)} />

      {/* ── PAGE TRANSITION ── */}
      {transitioning && (
        <div style={{
          position: "fixed", inset: 0, zIndex: 9999,
          background: "#0a0a10",
          display: "flex", alignItems: "center", justifyContent: "center",
        }}>
          <style>{`
            @keyframes ms-reveal {
              0%   { opacity: 0; transform: translateY(6px); }
              100% { opacity: 1; transform: translateY(0); }
            }
            @keyframes ms-bar {
              0%   { transform: scaleX(0); opacity: 1; }
              60%  { transform: scaleX(1); opacity: 1; }
              100% { transform: scaleX(1); opacity: 0; }
            }
          `}</style>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 20,
            animation: "ms-reveal 0.35s cubic-bezier(0.22,1,0.36,1) 0.05s both" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <div style={{ width: 30, height: 30, borderRadius: 8, background: "linear-gradient(135deg,#7352DD,#C084FC)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                <svg viewBox="0 0 24 24" fill="none" width="15" height="15" stroke="white" strokeWidth="2">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
                </svg>
              </div>
              <span style={{ fontSize: "1rem", fontWeight: 700, color: "#fff", letterSpacing: "-0.02em" }}>MindSync</span>
            </div>
            <div style={{
              width: 120, height: 1.5, background: "linear-gradient(90deg, #7352DD, #C084FC)",
              transformOrigin: "left", borderRadius: 99,
              animation: "ms-bar 0.55s cubic-bezier(0.76,0,0.24,1) 0.1s both",
            }} />
          </div>
        </div>
      )}

      <AnimatePresence>
        {showContent && (
          <motion.main initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.22 }}
            style={{ background: "#0a0a10", minHeight: "100vh", overflowX: "hidden" }}>

            {/* scroll progress */}
            <motion.div style={{ position: "fixed", top: 0, left: 0, right: 0, height: 2, zIndex: 100, background: "linear-gradient(90deg,#7352DD,#A78BFA,#C084FC)", scaleX: scrollYProgress, transformOrigin: "left" }} />

            {/* ══ HERO ══ */}
            <motion.section style={{ position: "relative", height: "100vh", display: "flex", alignItems: "center", justifyContent: "center", overflow: "hidden", opacity: heroOpacity, scale: heroScale, y: heroY }}>
              <div style={{ position: "absolute", inset: 0, zIndex: 0 }}><Suspense fallback={null}><BrainScene className="w-full h-full" /></Suspense></div>
              <div style={{ position: "absolute", inset: 0, zIndex: 1, background: "linear-gradient(to bottom, rgba(10,10,16,0.15) 0%, rgba(10,10,16,0.45) 55%, #0a0a10 100%)" }} />
              {/* subtle grid */}
              <svg style={{ position: "absolute", inset: 0, width: "100%", height: "100%", zIndex: 1, opacity: 0.025, pointerEvents: "none" }}>
                <defs><pattern id="hgrid" width="80" height="80" patternUnits="userSpaceOnUse"><path d="M 80 0 L 0 0 0 80" fill="none" stroke="#A78BFA" strokeWidth="0.5" /></pattern></defs>
                <rect width="100%" height="100%" fill="url(#hgrid)" />
              </svg>
              <div style={{ position: "relative", zIndex: 2, textAlign: "center", padding: "0 1.5rem", maxWidth: 860, margin: "0 auto" }}>
                <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3, duration: 0.6 }}
                  style={{ display: "inline-flex", alignItems: "center", gap: 8, padding: "6px 16px", borderRadius: 99, marginBottom: 28, border: "1px solid rgba(115,82,221,0.35)", background: "rgba(115,82,221,0.1)" }}>
                  <span style={{ position: "relative", display: "flex", width: 7, height: 7 }}>
                    <span style={{ position: "absolute", inset: 0, borderRadius: "50%", background: "#A78BFA", opacity: 0.7, animation: "ping 1.5s cubic-bezier(0,0,0.2,1) infinite" }} />
                    <span style={{ position: "relative", width: 7, height: 7, borderRadius: "50%", background: "#A78BFA" }} />
                  </span>
                  <span style={{ fontSize: "0.78rem", color: "#A78BFA", fontWeight: 500, letterSpacing: "0.02em" }}>Now in Public Beta</span>
                </motion.div>
                <motion.h1 initial={{ opacity: 0, y: 40 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.45, duration: 0.75, ease: [0.22,1,0.36,1] }}
                  style={{ fontSize: "clamp(2.8rem, 7.5vw, 6rem)", fontWeight: 900, lineHeight: 1.05, marginBottom: "0.4rem", color: "#fff", letterSpacing: "-0.03em" }}>
                  Think Different.
                </motion.h1>
                <motion.h1 initial={{ opacity: 0, y: 40 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.62, duration: 0.75, ease: [0.22,1,0.36,1] }}
                  style={{ fontSize: "clamp(2.8rem, 7.5vw, 6rem)", fontWeight: 900, lineHeight: 1.05, marginBottom: "1.75rem", background: "linear-gradient(135deg,#7352DD 20%,#A78BFA 60%,#C084FC 100%)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", letterSpacing: "-0.03em" }}>
                  Think MindSync.
                </motion.h1>
                <motion.p initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.8, duration: 0.65 }}
                  style={{ fontSize: "clamp(1rem, 1.8vw, 1.2rem)", color: "rgba(255,255,255,0.48)", maxWidth: 520, margin: "0 auto 2.25rem", lineHeight: 1.75 }}>
                  Your second brain powered by AI. Capture, connect, and create with intelligence that evolves with you.
                </motion.p>
                <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 1, duration: 0.55 }}
                  style={{ display: "flex", gap: 10, justifyContent: "center", flexWrap: "wrap" }}>
                  <motion.button onClick={handleTryMindSync} whileHover={{ scale: 1.05, boxShadow: "0 0 32px rgba(115,82,221,0.5)" }} whileTap={{ scale: 0.97 }}
                    style={{ padding: "13px 30px", borderRadius: 12, fontWeight: 600, fontSize: "0.92rem", color: "#fff", border: "none", cursor: "pointer", background: "linear-gradient(135deg,#7352DD,#A78BFA)", boxShadow: "0 0 20px rgba(115,82,221,0.3)" }}>
                    Try MindSync →
                  </motion.button>
                </motion.div>
              </div>
              <ScrollIndicator />
            </motion.section>

            {/* ══ MARQUEE ══ */}
            <section style={{ padding: "2.5rem 0", borderTop: "1px solid rgba(255,255,255,0.04)", borderBottom: "1px solid rgba(255,255,255,0.04)", overflow: "hidden", position: "relative" }}>
              <motion.div animate={{ x: ["0%", "-50%"] }} transition={{ duration: 22, repeat: Infinity, ease: "linear" }}
                style={{ display: "flex", whiteSpace: "nowrap", willChange: "transform" }}>
                {[...Array(8)].map((_, i) => (
                  <span key={i} style={{ fontSize: "clamp(1.6rem, 4vw, 3rem)", fontWeight: 800, color: "rgba(255,255,255,0.035)", marginRight: "2.5rem", letterSpacing: "0.06em" }}>
                    THINK FASTER &nbsp;·&nbsp; CREATE BETTER &nbsp;·&nbsp; LEARN SMARTER &nbsp;·&nbsp;
                  </span>
                ))}
              </motion.div>
            </section>

            {/* ══ FEATURES ══ */}
            <section style={{ padding: "4rem 1.5rem 8rem" }}>
              <div style={{ maxWidth: 1100, margin: "0 auto" }}>
                <div style={{ textAlign: "center", marginBottom: "5rem" }}>
                  <SectionLabel>What we offer</SectionLabel>
                  <motion.h2 initial={{ opacity: 0, y: 28 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ duration: 0.55 }}
                    style={{ fontSize: "clamp(2rem, 4vw, 3.2rem)", fontWeight: 800, color: "#fff", marginBottom: "0.9rem", letterSpacing: "-0.025em" }}>
                    Built for Modern Thinkers
                  </motion.h2>
                  <motion.p initial={{ opacity: 0, y: 16 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ duration: 0.55, delay: 0.12 }}
                    style={{ fontSize: "1.05rem", color: "rgba(255,255,255,0.4)", maxWidth: 440, margin: "0 auto" }}>
                    Every feature designed to amplify your cognitive potential
                  </motion.p>
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: "4.5rem" }}>
                  {features.map((f, i) => (
                    <StoryFeatureBlock key={i} number={String(i + 1).padStart(2, "0")} icon={f.icon} title={f.title} description={f.description} align={i % 2 === 0 ? "left" : "right"} index={i} />
                  ))}
                </div>
              </div>
            </section>

            {/* ══ CTA ══ */}
            <section style={{ padding: "6rem 1.5rem 8rem", position: "relative", overflow: "hidden" }}>
              <div style={{ position: "absolute", top: "50%", left: "50%", transform: "translate(-50%,-50%)", width: 600, height: 600, borderRadius: "50%", background: "radial-gradient(circle, rgba(115,82,221,0.15) 0%, transparent 70%)", pointerEvents: "none", filter: "blur(40px)" }} />
              <div style={{ position: "relative", maxWidth: 680, margin: "0 auto", textAlign: "center" }}>
                <FloatingCard>
                  <div style={{ padding: "3.5rem 2.5rem", borderRadius: "1.5rem", border: "1px solid rgba(255,255,255,0.07)", background: "rgba(255,255,255,0.02)", backdropFilter: "blur(24px)", position: "relative", overflow: "hidden" }}>
                    {/* top shimmer */}
                    <div style={{ position: "absolute", top: 0, left: "15%", right: "15%", height: 1, background: "linear-gradient(90deg, transparent, rgba(115,82,221,0.6), transparent)" }} />
                    <SectionLabel>Get started today</SectionLabel>
                    <motion.h2 initial={{ opacity: 0, y: 24 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ duration: 0.55 }}
                      style={{ fontSize: "clamp(1.7rem, 3.5vw, 2.8rem)", fontWeight: 800, color: "#fff", marginBottom: "0.9rem", letterSpacing: "-0.025em" }}>
                      Ready to sync your mind?
                    </motion.h2>
                    <motion.p initial={{ opacity: 0, y: 16 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ duration: 0.55, delay: 0.12 }}
                      style={{ fontSize: "0.97rem", color: "rgba(255,255,255,0.42)", marginBottom: "2.25rem", lineHeight: 1.75 }}>
                      Join thousands of students who have transformed how they study and retain knowledge.
                    </motion.p>
                    <motion.div initial={{ opacity: 0, y: 16 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ duration: 0.55, delay: 0.24 }}
                      style={{ display: "flex", gap: 10, justifyContent: "center", flexWrap: "wrap" }}>
                      <input type="email" placeholder="Enter your email"
                        style={{ padding: "13px 18px", borderRadius: 11, background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.09)", color: "#fff", fontSize: "0.92rem", outline: "none", width: 260 }} />
                      <motion.button whileHover={{ scale: 1.05, boxShadow: "0 0 28px rgba(115,82,221,0.45)" }} whileTap={{ scale: 0.97 }}
                        style={{ padding: "13px 26px", borderRadius: 11, fontWeight: 600, fontSize: "0.92rem", color: "#fff", border: "none", cursor: "pointer", background: "linear-gradient(135deg,#7352DD,#A78BFA)" }}>
                        Get Early Access
                      </motion.button>
                    </motion.div>
                    <p style={{ marginTop: "1rem", fontSize: "0.75rem", color: "rgba(255,255,255,0.2)" }}>Free for the first 1,000 users · No credit card required</p>
                  </div>
                </FloatingCard>
              </div>
            </section>

            {/* ══ FOOTER ══ */}
            <footer style={{ padding: "1.75rem 1.5rem", borderTop: "1px solid rgba(255,255,255,0.04)" }}>
              <div style={{ maxWidth: 1200, margin: "0 auto", display: "flex", alignItems: "center", justifyContent: "center" }}>
                <p style={{ fontSize: "0.75rem", color: "rgba(255,255,255,0.16)", letterSpacing: "0.05em" }}>© 2026 MindSync. All rights reserved.</p>
              </div>
            </footer>

          </motion.main>
        )}
      </AnimatePresence>
    </>
  )
}
