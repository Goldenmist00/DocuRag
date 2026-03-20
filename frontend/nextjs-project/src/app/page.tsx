"use client"

import { useState, useRef, useEffect, Suspense } from "react"
import { motion, useScroll, useTransform, AnimatePresence } from "framer-motion"
import { IntroAnimation } from "./components/landing/intro-animation"
import dynamic from "next/dynamic"
import MagneticCursor from "./components/landing/magnetic-cursor"
import { useRouter } from "next/navigation"
import HeroAscii from "@/components/ui/hero-ascii"
import { FileText, MessageSquare, ClipboardList, Search, ShieldCheck, Smartphone } from "lucide-react"
import RadialOrbitalTimeline from "@/components/ui/radial-orbital-timeline"

const BrainScene = dynamic(() => import("./components/landing/brain-scene"), {
  ssr: false,
  loading: () => (
    <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{ width: 56, height: 56, border: "1.5px solid rgba(255,255,255,0.2)", borderTopColor: "transparent", borderRadius: "50%", animation: "spin 1s linear infinite" }} />
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
        background: "rgba(255,255,255,0.02)",
        backdropFilter: "blur(24px)", border: "1px solid rgba(255,255,255,0.07)",
        boxShadow: "0 12px 40px rgba(0,0,0,0.35), inset 0 1px 0 rgba(255,255,255,0.06)", overflow: "hidden",
      }}>
        {/* top shimmer line */}
        <div style={{ position: "absolute", top: 0, left: "10%", right: "10%", height: 1, background: "linear-gradient(90deg, transparent, rgba(255,255,255,0.12), transparent)" }} />
        {/* side accent */}
        <motion.div variants={accentVariants} style={{
          position: "absolute", top: 0, bottom: 0, [align === "right" ? "right" : "left"]: 0,
          width: 3, borderRadius: 99, background: "linear-gradient(180deg, rgba(255,255,255,0.25) 0%, rgba(255,255,255,0.08) 60%, transparent 100%)", transformOrigin: "top",
        }} />
        {/* number watermark */}
        <motion.span variants={{ hidden: { opacity: 0, scale: 0.85 }, show: { opacity: 0.06, scale: 1, transition: { duration: 0.6 } } }}
          style={{
            position: "absolute", [align === "right" ? "left" : "right"]: -28, top: -12,
            fontSize: "clamp(90px, 13vw, 150px)", fontWeight: 900, lineHeight: 1,
            userSelect: "none", pointerEvents: "none",
            background: "linear-gradient(135deg, rgba(255,255,255,0.15) 0%, rgba(255,255,255,0.05) 100%)",
            WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
          }}>{number}</motion.span>
        <div style={{ position: "relative", zIndex: 1 }}>
          <motion.div variants={childVariants} style={{
            display: "inline-flex", alignItems: "center", gap: 6, padding: "5px 12px",
            borderRadius: 99, marginBottom: "1.25rem", background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)",
          }}>
            <span style={{ color: "rgba(255,255,255,0.5)", fontSize: "0.68rem", fontWeight: 600, letterSpacing: "0.22em", textTransform: "uppercase" }}>Feature {number}</span>
          </motion.div>
          <motion.div variants={childVariants} style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: "1.1rem", flexDirection: align === "right" ? "row-reverse" : "row" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", width: 52, height: 52, borderRadius: "0.75rem", flexShrink: 0, background: "rgba(255,255,255,0.04)", color: "rgba(255,255,255,0.6)", border: "1px solid rgba(255,255,255,0.08)" }}>
              {icon}
            </div>
            <h2 style={{ fontSize: "clamp(1.4rem, 2.8vw, 2.1rem)", fontWeight: 700, color: "#fff", lineHeight: 1.2 }}>{title}</h2>
          </motion.div>
          <motion.p variants={childVariants} style={{ fontSize: "1rem", color: "rgba(255,255,255,0.65)", lineHeight: 1.85 }}>{description}</motion.p>
        </div>
        <motion.div variants={{ hidden: { opacity: 0, scale: 0 }, show: { opacity: 1, scale: 1, transition: { duration: 0.3, delay: 0.4 } } }}
          style={{ position: "absolute", bottom: 14, [align === "right" ? "left" : "right"]: 14, width: 24, height: 24,
            borderRight: align === "right" ? "none" : "1.5px solid rgba(255,255,255,0.1)",
            borderLeft: align === "right" ? "1.5px solid rgba(255,255,255,0.1)" : "none",
            borderBottom: "1.5px solid rgba(255,255,255,0.1)" }} />
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
      <motion.div animate={{ borderColor: ["rgba(255,255,255,0.1)", "rgba(255,255,255,0.3)", "rgba(255,255,255,0.1)"] }}
        transition={{ duration: 2, repeat: Infinity }}
        style={{ width: 22, height: 36, borderRadius: 99, border: "1px solid rgba(255,255,255,0.15)", display: "flex", justifyContent: "center", paddingTop: 5 }}>
        <motion.div animate={{ y: [0, 12, 0] }} transition={{ duration: 1.4, repeat: Infinity, ease: "easeInOut" }}
          style={{ width: 3, height: 7, borderRadius: 99, background: "linear-gradient(180deg, rgba(255,255,255,0.5), rgba(255,255,255,0.15))" }} />
      </motion.div>
    </motion.div>
  )
}

/* ─── Section Label ─── */
function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <motion.div initial={{ opacity: 0, y: 12 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ duration: 0.5 }}
      style={{ display: "inline-flex", alignItems: "center", gap: 10, marginBottom: "1.25rem" }}>
      <div style={{ width: 20, height: 1, background: "linear-gradient(90deg, transparent, rgba(255,255,255,0.25))" }} />
      <span style={{ fontFamily: "var(--font-hero-mono)", fontSize: "0.65rem", fontWeight: 600, letterSpacing: "0.25em", textTransform: "uppercase", color: "rgba(255,255,255,0.4)" }}>{children}</span>
      <div style={{ width: 20, height: 1, background: "linear-gradient(90deg, rgba(255,255,255,0.25), transparent)" }} />
    </motion.div>
  )
}

/* ─── Stat Card ─── */
function StatCard({ value, label, delay }: { value: string; label: string; delay: number }) {
  return (
    <motion.div initial={{ opacity: 0, y: 24 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ duration: 0.5, delay }}
      style={{ textAlign: "center", padding: "1.75rem 2rem", borderRadius: "1rem", background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)", flex: 1, minWidth: 140 }}>
      <div style={{ fontSize: "clamp(1.8rem, 3vw, 2.5rem)", fontWeight: 800, background: "linear-gradient(135deg, rgba(255,255,255,0.9), rgba(255,255,255,0.5))", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", lineHeight: 1, marginBottom: 8 }}>{value}</div>
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

  const timelineData = [
    {
      id: 1,
      title: "Smart Flashcards",
      date: "Feature 01",
      content: "Automatically converts textbook content into interactive flashcards for quick revision and better retention.",
      category: "Learning",
      icon: FileText,
      relatedIds: [2, 3],
      status: "completed" as const,
      energy: 100,
    },
    {
      id: 2,
      title: "Mind Mapping",
      date: "Feature 02",
      content: "Transforms key concepts into visual mind maps to help users understand relationships and topic structure easily.",
      category: "Visualization",
      icon: MessageSquare,
      relatedIds: [1, 3],
      status: "completed" as const,
      energy: 90,
    },
    {
      id: 3,
      title: "Summary Mode",
      date: "Feature 03",
      content: "Generates concise, structured summaries of topics directly from textbook content for fast learning.",
      category: "Summarization",
      icon: ClipboardList,
      relatedIds: [2, 4],
      status: "completed" as const,
      energy: 85,
    },
    {
      id: 4,
      title: "Smart Search",
      date: "Feature 04",
      content: "Uses semantic AI search to instantly find the most relevant textbook sections for any question.",
      category: "Search",
      icon: Search,
      relatedIds: [3, 5],
      status: "in-progress" as const,
      energy: 70,
    },
    {
      id: 5,
      title: "Verified Citations",
      date: "Feature 05",
      content: "Every response includes exact section names and page numbers for reliable, verifiable learning.",
      category: "Trust",
      icon: ShieldCheck,
      relatedIds: [4, 6],
      status: "in-progress" as const,
      energy: 60,
    },
    {
      id: 6,
      title: "Study-Friendly UI",
      date: "Feature 06",
      content: "Designed for students with a clean, intuitive layout that makes exploring and revising topics effortless.",
      category: "Interface",
      icon: Smartphone,
      relatedIds: [5, 1],
      status: "pending" as const,
      energy: 40,
    },
  ]

  return (
    <>
      <MagneticCursor />
      <IntroAnimation onComplete={() => setShowContent(true)} />

      {/* ── PAGE TRANSITION ── */}
      {transitioning && (
        <div style={{
          position: "fixed", inset: 0, zIndex: 9999,
          background: "#060609",
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
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <img src="/logo.png" alt="MindSync" style={{ width: 36, height: 36, objectFit: "contain" }} />
              <span style={{ fontFamily: "var(--font-hero-display)", fontSize: "1rem", fontWeight: 700, color: "#fff", letterSpacing: "0.06em", textTransform: "uppercase" }}>MindSync</span>
            </div>
            <div style={{
              width: 120, height: 1.5, background: "linear-gradient(90deg, rgba(255,255,255,0.3), rgba(255,255,255,0.08))",
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
            <motion.div style={{ position: "fixed", top: 0, left: 0, right: 0, height: 2, zIndex: 100, background: "linear-gradient(90deg, rgba(255,255,255,0.4), rgba(255,255,255,0.7), rgba(255,255,255,0.4))", scaleX: scrollYProgress, transformOrigin: "left" }} />

            {/* ══ HERO ══ */}
            <HeroAscii />

            {/* ══ FEATURES ══ */}
            <section style={{ position: "relative", overflow: "hidden" }}>

              <div style={{ textAlign: "center", paddingTop: "5rem", paddingBottom: "1rem", position: "relative", zIndex: 10 }}>
                <SectionLabel>What we offer</SectionLabel>
                <motion.h2 initial={{ opacity: 0, y: 28 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ duration: 0.55 }}
                  style={{ fontFamily: "var(--font-hero-display)", fontSize: "clamp(2rem, 4vw, 3.2rem)", fontWeight: 800, color: "#fff", marginBottom: "0.9rem", letterSpacing: "0.04em", textTransform: "uppercase" }}>
                  Built for Modern Thinkers
                </motion.h2>
                <motion.p initial={{ opacity: 0, y: 16 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ duration: 0.55, delay: 0.12 }}
                  style={{ fontFamily: "var(--font-hero-body)", fontSize: "0.95rem", color: "rgba(255,255,255,0.35)", maxWidth: 480, margin: "0 auto", lineHeight: 1.8 }}>
                  Click on any orbiting node to explore each feature in detail
                </motion.p>
              </div>

              <RadialOrbitalTimeline timelineData={timelineData} />
            </section>

            {/* ══ CTA ══ */}
            <section style={{ padding: "6rem 1.5rem 8rem", position: "relative", overflow: "hidden" }}>
              <div style={{ position: "absolute", top: "50%", left: "50%", transform: "translate(-50%,-50%)", width: 600, height: 600, borderRadius: "50%", background: "radial-gradient(circle, rgba(255,255,255,0.03) 0%, transparent 70%)", pointerEvents: "none", filter: "blur(40px)" }} />
              <div style={{ position: "relative", maxWidth: 680, margin: "0 auto", textAlign: "center" }}>
                <FloatingCard>
                  <div style={{ padding: "3.5rem 2.5rem", borderRadius: "1.5rem", border: "1px solid rgba(255,255,255,0.07)", background: "rgba(255,255,255,0.02)", backdropFilter: "blur(24px)", position: "relative", overflow: "hidden" }}>
                    {/* top shimmer */}
                    <div style={{ position: "absolute", top: 0, left: "15%", right: "15%", height: 1, background: "linear-gradient(90deg, transparent, rgba(255,255,255,0.12), transparent)" }} />
                    <SectionLabel>Get started today</SectionLabel>
                    <motion.h2 initial={{ opacity: 0, y: 24 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ duration: 0.55 }}
                      style={{ fontFamily: "var(--font-hero-display)", fontSize: "clamp(1.7rem, 3.5vw, 2.8rem)", fontWeight: 800, color: "#fff", marginBottom: "0.9rem", letterSpacing: "0.04em", textTransform: "uppercase" }}>
                      Ready to sync your mind?
                    </motion.h2>
                    <motion.p initial={{ opacity: 0, y: 16 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ duration: 0.55, delay: 0.12 }}
                      style={{ fontFamily: "var(--font-hero-body)", fontSize: "0.95rem", color: "rgba(255,255,255,0.35)", marginBottom: "2.25rem", lineHeight: 1.8 }}>
                      Join thousands of students who have transformed how they study and retain knowledge.
                    </motion.p>
                    <motion.div initial={{ opacity: 0, y: 16 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ duration: 0.55, delay: 0.24 }}
                      style={{ display: "flex", gap: 10, justifyContent: "center", flexWrap: "wrap" }}>
                      <input type="email" placeholder="Enter your email"
                        style={{ fontFamily: "var(--font-hero-body)", padding: "13px 18px", borderRadius: 6, background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", color: "#fff", fontSize: "0.92rem", outline: "none", width: 260 }} />
                      <motion.button whileHover={{ scale: 1.05, boxShadow: "0 0 28px rgba(255,255,255,0.15)" }} whileTap={{ scale: 0.97 }}
                        style={{ fontFamily: "var(--font-hero-mono)", padding: "13px 26px", borderRadius: 6, fontWeight: 600, fontSize: "0.85rem", letterSpacing: "0.1em", textTransform: "uppercase", color: "#060609", border: "none", cursor: "pointer", background: "#fff" }}>
                        Get Early Access
                      </motion.button>
                    </motion.div>
                    <p style={{ fontFamily: "var(--font-hero-mono)", marginTop: "1rem", fontSize: "0.7rem", color: "rgba(255,255,255,0.18)", letterSpacing: "0.08em" }}>Free for the first 1,000 users · No credit card required</p>
                  </div>
                </FloatingCard>
              </div>
            </section>

            {/* ══ FOOTER ══ */}
            <footer style={{ padding: "1.75rem 1.5rem", borderTop: "1px solid rgba(255,255,255,0.04)" }}>
              <div style={{ maxWidth: 1200, margin: "0 auto", display: "flex", alignItems: "center", justifyContent: "center" }}>
                <p style={{ fontFamily: "var(--font-hero-mono)", fontSize: "0.7rem", color: "rgba(255,255,255,0.14)", letterSpacing: "0.1em" }}>© 2026 MindSync. All rights reserved.</p>
              </div>
            </footer>

          </motion.main>
        )}
      </AnimatePresence>
    </>
  )
}
