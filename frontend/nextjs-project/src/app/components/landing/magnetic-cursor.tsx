"use client"

import { useEffect, useRef, useCallback } from "react"

/**
 * Custom magnetic cursor that follows the mouse with smooth interpolation.
 * Uses refs and direct DOM manipulation to avoid React re-renders.
 * Only visible on md+ screens (hidden on mobile via CSS).
 */
export default function MagneticCursor() {
  const cursorRef = useRef<HTMLDivElement>(null)
  const cursorDotRef = useRef<HTMLDivElement>(null)
  const ringRef = useRef<HTMLDivElement>(null)
  const dotRef = useRef<HTMLDivElement>(null)
  const position = useRef({ x: -100, y: -100 })
  const targetPosition = useRef({ x: -100, y: -100 })
  const isHovering = useRef(false)
  const isClicking = useRef(false)
  const rafRef = useRef<number>(0)

  const applyHoverState = useCallback(() => {
    if (!ringRef.current || !dotRef.current) return
    const ring = ringRef.current
    if (isHovering.current) {
      ring.style.transform = "scale(1.5)"
      ring.style.background = "rgba(255,255,255,0.1)"
    } else {
      ring.style.transform = "scale(1)"
      ring.style.background = "transparent"
    }
    if (isClicking.current) {
      ring.style.transform = "scale(0.75)"
      dotRef.current.style.transform = "scale(0)"
    } else if (!isHovering.current) {
      dotRef.current.style.transform = "scale(1)"
    }
  }, [])

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      targetPosition.current = { x: e.clientX, y: e.clientY }
    }
    const handleMouseDown = () => {
      isClicking.current = true
      applyHoverState()
    }
    const handleMouseUp = () => {
      isClicking.current = false
      applyHoverState()
    }
    const handleMouseOver = (e: MouseEvent) => {
      const target = e.target as HTMLElement
      if (target.tagName === "BUTTON" || target.tagName === "A" || target.closest("button") || target.closest("a") || target.dataset.magnetic === "true") {
        isHovering.current = true
        applyHoverState()
      }
    }
    const handleMouseOut = (e: MouseEvent) => {
      const target = e.target as HTMLElement
      if (target.tagName === "BUTTON" || target.tagName === "A" || target.closest("button") || target.closest("a") || target.dataset.magnetic === "true") {
        isHovering.current = false
        applyHoverState()
      }
    }

    window.addEventListener("mousemove", handleMouseMove, { passive: true })
    window.addEventListener("mousedown", handleMouseDown)
    window.addEventListener("mouseup", handleMouseUp)
    document.addEventListener("mouseover", handleMouseOver, { passive: true })
    document.addEventListener("mouseout", handleMouseOut, { passive: true })

    const animate = () => {
      position.current.x += (targetPosition.current.x - position.current.x) * 0.15
      position.current.y += (targetPosition.current.y - position.current.y) * 0.15

      if (cursorRef.current) {
        cursorRef.current.style.transform = `translate3d(${position.current.x - 20}px, ${position.current.y - 20}px, 0)`
      }
      if (cursorDotRef.current) {
        cursorDotRef.current.style.transform = `translate3d(${targetPosition.current.x - 4}px, ${targetPosition.current.y - 4}px, 0)`
      }
      rafRef.current = requestAnimationFrame(animate)
    }
    rafRef.current = requestAnimationFrame(animate)

    return () => {
      window.removeEventListener("mousemove", handleMouseMove)
      window.removeEventListener("mousedown", handleMouseDown)
      window.removeEventListener("mouseup", handleMouseUp)
      document.removeEventListener("mouseover", handleMouseOver)
      document.removeEventListener("mouseout", handleMouseOut)
      cancelAnimationFrame(rafRef.current)
    }
  }, [applyHoverState])

  return (
    <>
      <div ref={cursorRef} className="fixed top-0 left-0 pointer-events-none z-[9999] hidden md:block" style={{ mixBlendMode: "difference", willChange: "transform" }}>
        <div ref={ringRef} className="w-10 h-10 rounded-full border-2 border-white" style={{ transition: "transform 0.3s, background 0.3s" }} />
      </div>
      <div ref={cursorDotRef} className="fixed top-0 left-0 pointer-events-none z-[9999] hidden md:block" style={{ willChange: "transform" }}>
        <div ref={dotRef} className="w-2 h-2 rounded-full bg-white" style={{ transition: "transform 0.15s" }} />
      </div>
    </>
  )
}
