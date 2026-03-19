"use client"

import { useEffect, useState, useRef } from "react"

export default function MagneticCursor() {
  const cursorRef = useRef<HTMLDivElement>(null)
  const cursorDotRef = useRef<HTMLDivElement>(null)
  const [isHovering, setIsHovering] = useState(false)
  const [isClicking, setIsClicking] = useState(false)
  const position = useRef({ x: 0, y: 0 })
  const targetPosition = useRef({ x: 0, y: 0 })

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => { targetPosition.current = { x: e.clientX, y: e.clientY } }
    const handleMouseDown = () => setIsClicking(true)
    const handleMouseUp = () => setIsClicking(false)
    const handleMouseOver = (e: MouseEvent) => {
      const target = e.target as HTMLElement
      if (target.tagName === "BUTTON" || target.tagName === "A" || target.closest("button") || target.closest("a") || target.dataset.magnetic === "true") setIsHovering(true)
    }
    const handleMouseOut = (e: MouseEvent) => {
      const target = e.target as HTMLElement
      if (target.tagName === "BUTTON" || target.tagName === "A" || target.closest("button") || target.closest("a") || target.dataset.magnetic === "true") setIsHovering(false)
    }

    window.addEventListener("mousemove", handleMouseMove)
    window.addEventListener("mousedown", handleMouseDown)
    window.addEventListener("mouseup", handleMouseUp)
    document.addEventListener("mouseover", handleMouseOver)
    document.addEventListener("mouseout", handleMouseOut)

    let animationId: number
    const animate = () => {
      position.current.x += (targetPosition.current.x - position.current.x) * 0.15
      position.current.y += (targetPosition.current.y - position.current.y) * 0.15
      if (cursorRef.current) cursorRef.current.style.transform = `translate(${position.current.x - 20}px, ${position.current.y - 20}px)`
      if (cursorDotRef.current) cursorDotRef.current.style.transform = `translate(${targetPosition.current.x - 4}px, ${targetPosition.current.y - 4}px)`
      animationId = requestAnimationFrame(animate)
    }
    animate()

    return () => {
      window.removeEventListener("mousemove", handleMouseMove)
      window.removeEventListener("mousedown", handleMouseDown)
      window.removeEventListener("mouseup", handleMouseUp)
      document.removeEventListener("mouseover", handleMouseOver)
      document.removeEventListener("mouseout", handleMouseOut)
      cancelAnimationFrame(animationId)
    }
  }, [])

  return (
    <>
      <div ref={cursorRef} className="fixed top-0 left-0 pointer-events-none z-[9999] hidden md:block" style={{ mixBlendMode: "difference" }}>
        <div className={`w-10 h-10 rounded-full border-2 border-white transition-all duration-300 ${isHovering ? "scale-150 bg-white/10" : ""} ${isClicking ? "scale-75" : ""}`} />
      </div>
      <div ref={cursorDotRef} className="fixed top-0 left-0 pointer-events-none z-[9999] hidden md:block">
        <div className={`w-2 h-2 rounded-full bg-white transition-transform duration-150 ${isClicking ? "scale-0" : ""}`} />
      </div>
    </>
  )
}
