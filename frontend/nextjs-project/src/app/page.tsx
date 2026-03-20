"use client"

import { useState, useRef, useEffect } from "react"
import { motion, useScroll, AnimatePresence } from "framer-motion"
import { IntroAnimation } from "./components/landing/intro-animation"
import MagneticCursor from "./components/landing/magnetic-cursor"
import HeroAscii from "@/components/ui/hero-ascii"
import { FileText, MessageSquare, ClipboardList, Search, ShieldCheck, Smartphone } from "lucide-react"
import RadialOrbitalTimeline from "@/components/ui/radial-orbital-timeline"

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

/* ─── Main Page ─── */
export default function Home() {
  const [showContent, setShowContent] = useState(false)
  const { scrollYProgress } = useScroll()

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

      <AnimatePresence>
        {showContent && (
          <motion.main initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.22 }}
            style={{ background: "#060609", minHeight: "100vh", overflowX: "hidden" }}>

            {/* scroll progress */}
            <motion.div style={{ position: "fixed", top: 0, left: 0, right: 0, height: 2, zIndex: 100, background: "linear-gradient(90deg, rgba(255,255,255,0.4), rgba(255,255,255,0.7), rgba(255,255,255,0.4))", scaleX: scrollYProgress, transformOrigin: "left" }} />

            {/* ══ HERO ══ */}
            <HeroAscii />

            {/* ══ FEATURES ══ */}
            <section id="features" style={{ position: "relative", overflow: "hidden" }}>

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
            <section id="cta" style={{ padding: "6rem 1.5rem 8rem", position: "relative", overflow: "hidden" }}>
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
