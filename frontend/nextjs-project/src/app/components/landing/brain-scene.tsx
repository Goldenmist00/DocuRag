"use client"

import { Canvas, useFrame } from "@react-three/fiber"
import { useRef, useMemo } from "react"
import * as THREE from "three"
import { Float, MeshDistortMaterial, Sphere, Trail } from "@react-three/drei"

function GlowOrb({ position, color, scale = 1 }: { position: [number, number, number]; color: string; scale?: number }) {
  const ref = useRef<THREE.Mesh>(null)
  const timeRef = useRef(Math.random() * 100)

  useFrame((_, delta) => {
    timeRef.current += delta
    if (ref.current) {
      ref.current.scale.setScalar(scale * (1 + Math.sin(timeRef.current * 2) * 0.1))
    }
  })

  return (
    <mesh ref={ref} position={position}>
      <sphereGeometry args={[0.15, 32, 32]} />
      <meshStandardMaterial color={color} emissive={color} emissiveIntensity={2} transparent opacity={0.9} />
    </mesh>
  )
}

function OrbitingParticle({ radius, speed, offset, color }: { radius: number; speed: number; offset: number; color: string }) {
  const ref = useRef<THREE.Mesh>(null)
  const timeRef = useRef(offset)

  useFrame((_, delta) => {
    timeRef.current += delta * speed
    if (ref.current) {
      ref.current.position.x = Math.cos(timeRef.current) * radius
      ref.current.position.z = Math.sin(timeRef.current) * radius
      ref.current.position.y = Math.sin(timeRef.current * 2) * 0.5
    }
  })

  return (
    <Trail width={0.5} length={8} color={color} attenuation={(t) => t * t}>
      <mesh ref={ref}>
        <sphereGeometry args={[0.04, 16, 16]} />
        <meshBasicMaterial color={color} />
      </mesh>
    </Trail>
  )
}

function CentralSphere() {
  const ref = useRef<THREE.Mesh>(null)
  const timeRef = useRef(0)

  useFrame((_, delta) => {
    timeRef.current += delta
    if (ref.current) {
      ref.current.rotation.x = timeRef.current * 0.15
      ref.current.rotation.y = timeRef.current * 0.2
    }
  })

  return (
    <Float speed={1.5} rotationIntensity={0.3} floatIntensity={0.5}>
      <Sphere ref={ref} args={[1, 128, 128]}>
        <MeshDistortMaterial
          color="#e0e0e0"
          emissive="#ffffff"
          emissiveIntensity={0.3}
          roughness={0.1}
          metalness={0.9}
          distort={0.35}
          speed={1.5}
          transparent
          opacity={0.95}
        />
      </Sphere>
    </Float>
  )
}

function FloatingRing({ radius, rotationSpeed }: { radius: number; rotationSpeed: number }) {
  const ref = useRef<THREE.Mesh>(null)
  const timeRef = useRef(0)

  useFrame((_, delta) => {
    timeRef.current += delta
    if (ref.current) {
      ref.current.rotation.x = Math.PI / 2 + Math.sin(timeRef.current * 0.5) * 0.2
      ref.current.rotation.z = timeRef.current * rotationSpeed
    }
  })

  return (
    <mesh ref={ref}>
      <torusGeometry args={[radius, 0.02, 16, 100]} />
      <meshStandardMaterial color="#d0d0d0" emissive="#ffffff" emissiveIntensity={0.6} transparent opacity={0.4} />
    </mesh>
  )
}

function ParticleField() {
  const count = 200
  const ref = useRef<THREE.Points>(null)
  const timeRef = useRef(0)

  const positions = useMemo(() => {
    const pos = new Float32Array(count * 3)
    for (let i = 0; i < count; i++) {
      const theta = Math.random() * Math.PI * 2
      const phi = Math.acos(Math.random() * 2 - 1)
      const r = 2.5 + Math.random() * 2
      pos[i * 3] = r * Math.sin(phi) * Math.cos(theta)
      pos[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta)
      pos[i * 3 + 2] = r * Math.cos(phi)
    }
    return pos
  }, [])

  useFrame((_, delta) => {
    timeRef.current += delta
    if (ref.current) ref.current.rotation.y = timeRef.current * 0.05
  })

  return (
    <points ref={ref}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" count={count} array={positions} itemSize={3} />
      </bufferGeometry>
      <pointsMaterial color="#cccccc" size={0.03} transparent opacity={0.5} sizeAttenuation />
    </points>
  )
}

function LightBeam({ start, end, delay }: { start: [number, number, number]; end: [number, number, number]; delay: number }) {
  const ref = useRef<THREE.Line>(null)
  const timeRef = useRef(delay)

  const points = useMemo(() => [new THREE.Vector3(...start), new THREE.Vector3(...end)], [start, end])
  const geometry = useMemo(() => new THREE.BufferGeometry().setFromPoints(points), [points])

  useFrame((_, delta) => {
    timeRef.current += delta
    if (ref.current) {
      const material = ref.current.material as THREE.LineBasicMaterial
      material.opacity = 0.15 + Math.sin(timeRef.current * 2) * 0.1
    }
  })

  return (
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    <primitive object={new THREE.Line(geometry, new THREE.LineBasicMaterial({ color: "#cccccc", transparent: true, opacity: 0.15 }))} ref={ref as any} />
  )
}

function Scene() {
  const groupRef = useRef<THREE.Group>(null)
  const timeRef = useRef(0)

  useFrame((_, delta) => {
    timeRef.current += delta
    if (groupRef.current) groupRef.current.rotation.y = timeRef.current * 0.08
  })

  const orbs = useMemo(() => [
    { position: [1.8, 0.5, 0.5] as [number, number, number], color: "#e0e0e0", scale: 0.8 },
    { position: [-1.5, -0.3, 1] as [number, number, number], color: "#cccccc", scale: 0.6 },
    { position: [0.8, -1.2, -0.8] as [number, number, number], color: "#d0d0d0", scale: 0.5 },
    { position: [-1.2, 1, -0.5] as [number, number, number], color: "#b0b0b0", scale: 0.7 },
    { position: [1.5, -0.8, 1.2] as [number, number, number], color: "#f0f0f0", scale: 0.4 },
  ], [])

  const beams = useMemo(() => [
    { start: [0, 0, 0] as [number, number, number], end: [1.8, 0.5, 0.5] as [number, number, number] },
    { start: [0, 0, 0] as [number, number, number], end: [-1.5, -0.3, 1] as [number, number, number] },
    { start: [0, 0, 0] as [number, number, number], end: [0.8, -1.2, -0.8] as [number, number, number] },
    { start: [0, 0, 0] as [number, number, number], end: [-1.2, 1, -0.5] as [number, number, number] },
    { start: [1.8, 0.5, 0.5] as [number, number, number], end: [-1.2, 1, -0.5] as [number, number, number] },
    { start: [-1.5, -0.3, 1] as [number, number, number], end: [0.8, -1.2, -0.8] as [number, number, number] },
  ], [])

  return (
    <group ref={groupRef}>
      <CentralSphere />
      <FloatingRing radius={1.6} rotationSpeed={0.3} />
      <FloatingRing radius={2.2} rotationSpeed={-0.2} />
      {orbs.map((orb, i) => <GlowOrb key={i} {...orb} />)}
      {beams.map((beam, i) => <LightBeam key={i} start={beam.start} end={beam.end} delay={i * 0.5} />)}
      <OrbitingParticle radius={2} speed={0.8} offset={0} color="#e0e0e0" />
      <OrbitingParticle radius={2.4} speed={0.6} offset={Math.PI / 2} color="#cccccc" />
      <OrbitingParticle radius={1.8} speed={1} offset={Math.PI} color="#d0d0d0" />
      <ParticleField />
    </group>
  )
}

export default function BrainScene({ className }: { className?: string }) {
  return (
    <div className={className}>
      <Canvas camera={{ position: [0, 0, 6], fov: 45 }}>
        <color attach="background" args={["#060609"]} />
        <fog attach="fog" args={["#060609", 4, 12]} />
        <ambientLight intensity={0.3} />
        <pointLight position={[5, 5, 5]} intensity={1.5} color="#e0e0e0" />
        <pointLight position={[-5, -5, -5]} intensity={0.8} color="#cccccc" />
        <pointLight position={[0, 0, 5]} intensity={0.5} color="#d0d0d0" />
        <Scene />
      </Canvas>
    </div>
  )
}
