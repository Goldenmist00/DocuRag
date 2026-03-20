"use client"

import { useEffect, useRef, useState } from "react"
import { motion, AnimatePresence } from "framer-motion"
import Image from "next/image"

function Particle({ x, y, size, delay, duration }: { x: number; y: number; size: number; delay: number; duration: number }) {
  return (
    <motion.div
      style={{
        position: "absolute",
        left: `${x}%`, top: `${y}%`,
        width: size, height: size,
        borderRadius: "50%",
        background: "radial-gradient(circle, rgba(255,255,255,0.6) 0%, rgba(255,255,255,0.1) 60%, transparent 100%)",
        pointerEvents: "none",
      }}
      initial={{ opacity: 0, scale: 0 }}
      animate={{ opacity: [0, 0.5, 0.2, 0.5, 0], scale: [0, 1, 0.8, 1, 0], y: [0, -30, -60] }}
      transition={{ duration, delay, ease: "easeOut", repeat: Infinity, repeatDelay: Math.random() * 2 }}
    />
  )
}

function GridOverlay() {
  return (
    <svg style={{ position: "absolute", inset: 0, width: "100%", height: "100%", opacity: 0.03, pointerEvents: "none" }}>
      <defs>
        <pattern id="grid" width="60" height="60" patternUnits="userSpaceOnUse">
          <path d="M 60 0 L 0 0 0 60" fill="none" stroke="white" strokeWidth="0.5" />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill="url(#grid)" />
    </svg>
  )
}

function RingPulse({ delay }: { delay: number }) {
  return (
    <motion.div
      style={{
        position: "absolute", top: "50%", left: "50%",
        width: 200, height: 200,
        borderRadius: "50%",
        border: "1px solid rgba(255,255,255,0.12)",
        transform: "translate(-50%, -50%)",
        pointerEvents: "none",
      }}
      initial={{ scale: 0.3, opacity: 0 }}
      animate={{ scale: [0.3, 2.5], opacity: [0.4, 0] }}
      transition={{ duration: 2.5, delay, ease: "easeOut", repeat: Infinity, repeatDelay: 1 }}
    />
  )
}

export function IntroAnimation({ onComplete }: { onComplete: () => void }) {
  const [visible, setVisible] = useState(true)
  const [phase, setPhase] = useState(0)
  const called = useRef(false)

  const particles = useRef(
    Array.from({ length: 24 }, (_, i) => ({
      x: 5 + (i * 37.3) % 90,
      y: 5 + (i * 53.7) % 90,
      size: 2 + (i % 3),
      delay: (i * 0.18) % 2.5,
      duration: 2.5 + (i % 4) * 0.5,
    }))
  )

  useEffect(() => {
    const t1 = setTimeout(() => setPhase(1), 500)
    const t2 = setTimeout(() => setPhase(2), 1400)
    const t3 = setTimeout(() => setPhase(3), 2200)
    const t4 = setTimeout(() => setVisible(false), 3000)
    const t5 = setTimeout(() => {
      if (!called.current) { called.current = true; onComplete() }
    }, 3700)
    return () => [t1, t2, t3, t4, t5].forEach(clearTimeout)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          key="intro"
          style={{
            position: "fixed", inset: 0, zIndex: 9999,
            display: "flex", alignItems: "center", justifyContent: "center",
            overflow: "hidden", background: "#060609",
          }}
          exit={{ opacity: 0, scale: 1.04, transition: { duration: 0.55, ease: [0.22, 1, 0.36, 1] } }}
        >
          <GridOverlay />

          {/* ambient glow — white */}
          <div style={{ position: "absolute", top: "20%", left: "15%", width: 500, height: 500, borderRadius: "50%", background: "radial-gradient(circle, rgba(255,255,255,0.04) 0%, transparent 65%)", pointerEvents: "none", filter: "blur(40px)" }} />
          <div style={{ position: "absolute", bottom: "15%", right: "10%", width: 400, height: 400, borderRadius: "50%", background: "radial-gradient(circle, rgba(255,255,255,0.03) 0%, transparent 65%)", pointerEvents: "none", filter: "blur(40px)" }} />

          <RingPulse delay={0.8} />
          <RingPulse delay={1.6} />

          {particles.current.map((p, i) => <Particle key={i} {...p} />)}

          {/* corner brackets */}
          {[
            { top: 24, left: 24, borderTop: "1px solid rgba(255,255,255,0.12)", borderLeft: "1px solid rgba(255,255,255,0.12)" },
            { top: 24, right: 24, borderTop: "1px solid rgba(255,255,255,0.12)", borderRight: "1px solid rgba(255,255,255,0.12)" },
            { bottom: 24, left: 24, borderBottom: "1px solid rgba(255,255,255,0.12)", borderLeft: "1px solid rgba(255,255,255,0.12)" },
            { bottom: 24, right: 24, borderBottom: "1px solid rgba(255,255,255,0.12)", borderRight: "1px solid rgba(255,255,255,0.12)" },
          ].map((s, i) => (
            <motion.div key={i} style={{ position: "absolute", width: 40, height: 40, ...s }}
              initial={{ opacity: 0, scale: 0.5 }} animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: 0.2 + i * 0.08, duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
            />
          ))}

          {/* ── center stage ── */}
          <div style={{ position: "relative", zIndex: 10, display: "flex", flexDirection: "column", alignItems: "center", gap: 0 }}>

            {/* MindSync logo */}
            <motion.div
              style={{ position: "relative", marginBottom: 40 }}
              initial={{ scale: 0, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1] }}
            >
              {/* outer ring */}
              <motion.div
                style={{
                  position: "absolute", inset: -16, borderRadius: "50%",
                  border: "1px solid rgba(255,255,255,0.08)",
                  pointerEvents: "none",
                }}
                animate={{ rotate: 360 }}
                transition={{ duration: 12, repeat: Infinity, ease: "linear" }}
              >
                <div style={{ position: "absolute", top: -3, left: "50%", transform: "translateX(-50%)", width: 5, height: 5, borderRadius: "50%", background: "rgba(255,255,255,0.5)", boxShadow: "0 0 8px rgba(255,255,255,0.3)" }} />
              </motion.div>

              {/* logo image */}
              <motion.div
                style={{
                  position: "relative", zIndex: 1,
                  width: 120, height: 120,
                  display: "flex", alignItems: "center", justifyContent: "center",
                }}
                animate={{
                  filter: [
                    "drop-shadow(0 0 20px rgba(255,255,255,0.1))",
                    "drop-shadow(0 0 35px rgba(255,255,255,0.2))",
                    "drop-shadow(0 0 20px rgba(255,255,255,0.1))",
                  ],
                }}
                transition={{ duration: 2.5, repeat: Infinity }}
              >
                <Image
                  src="/logo.png"
                  alt="MindSync"
                  width={120}
                  height={120}
                  style={{ objectFit: "contain" }}
                  priority
                />
              </motion.div>
            </motion.div>

            {/* brand name */}
            <div style={{ overflow: "hidden", marginBottom: 12 }}>
              <motion.h1
                style={{
                  fontSize: "clamp(2.8rem, 9vw, 5.5rem)", fontWeight: 900,
                  letterSpacing: "-0.04em", lineHeight: 1, margin: 0,
                  fontFamily: "var(--font-hero-display)",
                  display: "flex",
                }}
                initial={{ y: "110%" }}
                animate={{ y: phase >= 1 ? "0%" : "110%" }}
                transition={{ duration: 0.65, ease: [0.22, 1, 0.36, 1] }}
              >
                {"Mind".split("").map((c, i) => (
                  <motion.span key={`m${i}`} style={{ display: "inline-block", color: "#fff" }}
                    initial={{ opacity: 0 }} animate={{ opacity: phase >= 1 ? 1 : 0 }}
                    transition={{ delay: 0.1 + i * 0.05 }}>{c}</motion.span>
                ))}
                {"Sync".split("").map((c, i) => (
                  <motion.span key={`s${i}`} style={{
                    display: "inline-block",
                    color: "rgba(255,255,255,0.4)",
                  }}
                    initial={{ opacity: 0 }} animate={{ opacity: phase >= 1 ? 1 : 0 }}
                    transition={{ delay: 0.3 + i * 0.05 }}>{c}</motion.span>
                ))}
              </motion.h1>
            </div>

            {/* subtitle */}
            <motion.div
              style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 40 }}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: phase >= 2 ? 1 : 0, y: phase >= 2 ? 0 : 10 }}
              transition={{ duration: 0.5, ease: "easeOut" }}
            >
              <div style={{ width: 24, height: 1, background: "rgba(255,255,255,0.15)" }} />
              <span style={{
                fontFamily: "var(--font-hero-mono)",
                fontSize: "0.7rem", letterSpacing: "0.25em", textTransform: "uppercase",
                color: "rgba(255,255,255,0.3)", fontWeight: 400,
              }}>
                Search · Understand · Visualize
              </span>
              <div style={{ width: 24, height: 1, background: "rgba(255,255,255,0.15)" }} />
            </motion.div>

            {/* progress bar */}
            <motion.div
              style={{ position: "relative", width: 280, height: 2, borderRadius: 99, background: "rgba(255,255,255,0.06)", overflow: "visible" }}
              initial={{ opacity: 0, scaleX: 0 }}
              animate={{ opacity: phase >= 3 ? 1 : 0, scaleX: phase >= 3 ? 1 : 0 }}
              transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
            >
              <motion.div
                style={{
                  height: "100%", borderRadius: 99,
                  background: "linear-gradient(90deg, rgba(255,255,255,0.2), rgba(255,255,255,0.6), rgba(255,255,255,0.2))",
                  position: "relative", overflow: "hidden",
                }}
                initial={{ width: "0%" }}
                animate={{ width: phase >= 3 ? "100%" : "0%" }}
                transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
              >
                <motion.div
                  style={{ position: "absolute", inset: 0, background: "linear-gradient(90deg, transparent, rgba(255,255,255,0.5), transparent)", width: "50%" }}
                  animate={{ x: ["-100%", "300%"] }}
                  transition={{ duration: 0.8, delay: 0.7, ease: "easeInOut" }}
                />
              </motion.div>
              <motion.div
                style={{
                  position: "absolute", top: "50%", transform: "translateY(-50%)",
                  width: 6, height: 6, borderRadius: "50%",
                  background: "rgba(255,255,255,0.8)",
                  boxShadow: "0 0 10px rgba(255,255,255,0.4)",
                  marginLeft: -3,
                }}
                initial={{ left: "0%" }}
                animate={{ left: phase >= 3 ? "100%" : "0%" }}
                transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
              />
            </motion.div>

            {/* status text */}
            <motion.p
              style={{
                fontFamily: "var(--font-hero-mono)",
                marginTop: 14, fontSize: "0.6rem", letterSpacing: "0.2em",
                textTransform: "uppercase", color: "rgba(255,255,255,0.15)", fontWeight: 400,
              }}
              initial={{ opacity: 0 }}
              animate={{ opacity: phase >= 3 ? 1 : 0 }}
              transition={{ duration: 0.4, delay: 0.15 }}
            >
              Initializing experience
            </motion.p>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
