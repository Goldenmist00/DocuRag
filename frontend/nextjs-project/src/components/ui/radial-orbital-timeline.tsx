"use client";
import { useState, useEffect, useRef } from "react";
import { ArrowRight, Link, Zap } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface TimelineItem {
  id: number;
  title: string;
  date: string;
  content: string;
  category: string;
  icon: React.ElementType;
  relatedIds: number[];
  status: "completed" | "in-progress" | "pending";
  energy: number;
}

interface RadialOrbitalTimelineProps {
  timelineData: TimelineItem[];
}

export default function RadialOrbitalTimeline({
  timelineData,
}: RadialOrbitalTimelineProps) {
  const [expandedItems, setExpandedItems] = useState<Record<number, boolean>>({});
  const [rotationAngle, setRotationAngle] = useState<number>(0);
  const [autoRotate, setAutoRotate] = useState<boolean>(true);
  const [pulseEffect, setPulseEffect] = useState<Record<number, boolean>>({});
  const [activeNodeId, setActiveNodeId] = useState<number | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const orbitRef = useRef<HTMLDivElement>(null);
  const nodeRefs = useRef<Record<number, HTMLDivElement | null>>({});

  const handleContainerClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target === containerRef.current || e.target === orbitRef.current) {
      setExpandedItems({});
      setActiveNodeId(null);
      setPulseEffect({});
      setAutoRotate(true);
    }
  };

  const toggleItem = (id: number) => {
    setExpandedItems((prev) => {
      const newState = { ...prev };
      Object.keys(newState).forEach((key) => {
        if (parseInt(key) !== id) newState[parseInt(key)] = false;
      });
      newState[id] = !prev[id];

      if (!prev[id]) {
        setActiveNodeId(id);
        setAutoRotate(false);
        const relatedItems = getRelatedItems(id);
        const newPulseEffect: Record<number, boolean> = {};
        relatedItems.forEach((relId) => { newPulseEffect[relId] = true; });
        setPulseEffect(newPulseEffect);
        centerViewOnNode(id);
      } else {
        setActiveNodeId(null);
        setAutoRotate(true);
        setPulseEffect({});
      }
      return newState;
    });
  };

  useEffect(() => {
    let rotationTimer: NodeJS.Timeout;
    if (autoRotate) {
      rotationTimer = setInterval(() => {
        setRotationAngle((prev) => Number(((prev + 0.25) % 360).toFixed(3)));
      }, 50);
    }
    return () => { if (rotationTimer) clearInterval(rotationTimer); };
  }, [autoRotate]);

  const centerViewOnNode = (nodeId: number) => {
    const nodeIndex = timelineData.findIndex((item) => item.id === nodeId);
    const targetAngle = (nodeIndex / timelineData.length) * 360;
    setRotationAngle(270 - targetAngle);
  };

  const calculateNodePosition = (index: number, total: number) => {
    const angle = ((index / total) * 360 + rotationAngle) % 360;
    const radius = 260;
    const radian = (angle * Math.PI) / 180;
    const x = radius * Math.cos(radian);
    const y = radius * Math.sin(radian);
    const zIndex = Math.round(100 + 50 * Math.cos(radian));
    const opacity = Math.max(0.5, Math.min(1, 0.5 + 0.5 * ((1 + Math.sin(radian)) / 2)));
    return { x, y, zIndex, opacity };
  };

  const getRelatedItems = (itemId: number): number[] => {
    const currentItem = timelineData.find((item) => item.id === itemId);
    return currentItem ? currentItem.relatedIds : [];
  };

  const isRelatedToActive = (itemId: number): boolean => {
    if (!activeNodeId) return false;
    return getRelatedItems(activeNodeId).includes(itemId);
  };

  const getStatusLabel = (status: TimelineItem["status"]): string => {
    switch (status) {
      case "completed": return "COMPLETE";
      case "in-progress": return "IN PROGRESS";
      case "pending": return "PENDING";
      default: return "PENDING";
    }
  };

  const MONO = { fontFamily: "var(--font-hero-mono)" } as const;
  const DISPLAY = { fontFamily: "var(--font-hero-display)" } as const;
  const BODY = { fontFamily: "var(--font-hero-body)" } as const;

  return (
    <div
      className="w-full flex flex-col items-center justify-center overflow-hidden"
      ref={containerRef}
      onClick={handleContainerClick}
      style={{ height: "min(100vh, 800px)", background: "transparent" }}
    >
      <div className="relative w-full max-w-5xl flex-1 flex items-center justify-center">
        <div
          className="absolute w-full h-full flex items-center justify-center"
          ref={orbitRef}
          style={{ perspective: "1200px" }}
        >
          {/* ── Central orb — white core like hero buttons ── */}
          <div className="absolute flex items-center justify-center z-10">
            <div className="w-16 h-16 rounded-full flex items-center justify-center bg-white/[0.06] border border-white/[0.12]">
              <div className="w-6 h-6 rounded-full bg-white/80" />
            </div>
            <div className="absolute w-20 h-20 rounded-full border border-white/[0.08] animate-ping opacity-30" />
            <div className="absolute w-24 h-24 rounded-full border border-white/[0.04] animate-ping opacity-15"
              style={{ animationDelay: "0.6s" }} />
          </div>

          {/* ── Orbit rings — same border opacity as hero corner frames ── */}
          <div className="absolute rounded-full border border-white/[0.06]" style={{ width: 520, height: 520 }} />
          <div className="absolute rounded-full border border-dashed border-white/[0.04]" style={{ width: 460, height: 460 }} />

          {/* ── Nodes ── */}
          {timelineData.map((item, index) => {
            const position = calculateNodePosition(index, timelineData.length);
            const isExpanded = expandedItems[item.id];
            const isRelated = isRelatedToActive(item.id);
            const isPulsing = pulseEffect[item.id];
            const Icon = item.icon;

            return (
              <div
                key={item.id}
                ref={(el) => { nodeRefs.current[item.id] = el; }}
                className="absolute transition-all duration-700 cursor-pointer"
                style={{
                  transform: `translate(${position.x}px, ${position.y}px)`,
                  zIndex: isExpanded ? 200 : position.zIndex,
                  opacity: isExpanded ? 1 : position.opacity,
                }}
                onClick={(e) => { e.stopPropagation(); toggleItem(item.id); }}
              >
                {/* subtle glow on pulse/expand */}
                {(isPulsing || isExpanded) && (
                  <div className="absolute rounded-full animate-pulse"
                    style={{
                      background: "radial-gradient(circle, rgba(255,255,255,0.08) 0%, transparent 70%)",
                      width: 80, height: 80, left: -16, top: -16,
                    }} />
                )}

                {/* node circle — mirrors hero border/bg style */}
                <div
                  className="w-12 h-12 rounded-full flex items-center justify-center transition-all duration-300"
                  style={
                    isExpanded
                      ? { background: "#fff", color: "#060609", boxShadow: "0 0 30px rgba(255,255,255,0.15)", transform: "scale(1.35)" }
                      : isRelated
                      ? { border: "1.5px solid rgba(255,255,255,0.4)", background: "rgba(255,255,255,0.08)", color: "rgba(255,255,255,0.9)" }
                      : { border: "1px solid rgba(255,255,255,0.12)", background: "rgba(255,255,255,0.03)", color: "rgba(255,255,255,0.5)" }
                  }
                >
                  <Icon size={18} />
                </div>

                {/* label — JetBrains Mono, uppercase, like hero status bar text */}
                <div
                  className="absolute left-1/2 -translate-x-1/2 whitespace-nowrap mt-2 transition-all duration-300"
                  style={{
                    ...MONO,
                    fontSize: 9,
                    letterSpacing: "0.15em",
                    textTransform: "uppercase",
                    fontWeight: 500,
                    color: isExpanded ? "rgba(255,255,255,0.7)" : "rgba(255,255,255,0.25)",
                    top: isExpanded ? 56 : 52,
                  }}
                >
                  {item.title}
                </div>

                {/* expanded card — #060609 bg, white/[0.06] border like hero footer */}
                {isExpanded && (
                  <Card
                    className="absolute top-[72px] left-1/2 -translate-x-1/2 w-72 overflow-visible"
                    style={{
                      background: "rgba(6,6,9,0.95)",
                      backdropFilter: "blur(24px)",
                      border: "1px solid rgba(255,255,255,0.07)",
                      boxShadow: "0 20px 60px rgba(0,0,0,0.5)",
                    }}
                  >
                    {/* connector line */}
                    <div className="absolute -top-3 left-1/2 -translate-x-1/2 w-px h-3"
                      style={{ background: "linear-gradient(to bottom, transparent, rgba(255,255,255,0.15))" }} />

                    <CardHeader className="pb-3 pt-5 px-5">
                      <div className="flex justify-between items-center">
                        <Badge
                          className="px-2.5 py-0.5"
                          style={{
                            ...MONO,
                            fontSize: 8,
                            letterSpacing: "0.2em",
                            fontWeight: 600,
                            background: "rgba(255,255,255,0.04)",
                            color: "rgba(255,255,255,0.5)",
                            border: "1px solid rgba(255,255,255,0.08)",
                            borderRadius: 2,
                          }}
                        >
                          {getStatusLabel(item.status)}
                        </Badge>
                        <span style={{ ...MONO, fontSize: 9, color: "rgba(255,255,255,0.2)", letterSpacing: "0.15em" }}>
                          {item.date}
                        </span>
                      </div>
                      <CardTitle className="mt-3" style={{ ...DISPLAY, fontSize: 14, fontWeight: 700, color: "#fff" }}>
                        {item.title}
                      </CardTitle>
                    </CardHeader>

                    <CardContent className="px-5 pb-5" style={{ ...BODY, fontSize: 12, color: "rgba(255,255,255,0.40)", lineHeight: 1.8 }}>
                      <p>{item.content}</p>

                      {/* energy bar — white gradient like hero accent line */}
                      <div className="mt-4 pt-3" style={{ borderTop: "1px solid rgba(255,255,255,0.06)" }}>
                        <div className="flex justify-between items-center mb-1.5">
                          <span className="flex items-center" style={{ ...MONO, fontSize: 9, color: "rgba(255,255,255,0.25)", letterSpacing: "0.15em" }}>
                            <Zap size={9} className="mr-1" style={{ color: "rgba(255,255,255,0.35)" }} />
                            READINESS
                          </span>
                          <span style={{ ...MONO, fontSize: 9, color: "rgba(255,255,255,0.3)" }}>{item.energy}%</span>
                        </div>
                        <div className="w-full h-1 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.04)" }}>
                          <div
                            className="h-full rounded-full"
                            style={{
                              width: `${item.energy}%`,
                              background: "linear-gradient(90deg, rgba(255,255,255,0.2), rgba(255,255,255,0.5))",
                            }}
                          />
                        </div>
                      </div>

                      {/* connected nodes */}
                      {item.relatedIds.length > 0 && (
                        <div className="mt-4 pt-3" style={{ borderTop: "1px solid rgba(255,255,255,0.06)" }}>
                          <div className="flex items-center mb-2">
                            <Link size={9} style={{ color: "rgba(255,255,255,0.2)", marginRight: 6 }} />
                            <h4 style={{ ...MONO, fontSize: 8, letterSpacing: "0.2em", textTransform: "uppercase", fontWeight: 500, color: "rgba(255,255,255,0.2)" }}>
                              Connected
                            </h4>
                          </div>
                          <div className="flex flex-wrap gap-1.5">
                            {item.relatedIds.map((relatedId) => {
                              const relatedItem = timelineData.find((i) => i.id === relatedId);
                              return (
                                <Button
                                  key={relatedId}
                                  variant="outline"
                                  size="sm"
                                  className="flex items-center h-6 px-2.5 py-0 rounded-sm transition-all hover:bg-white/[0.04]"
                                  style={{
                                    ...MONO,
                                    fontSize: 9,
                                    letterSpacing: "0.08em",
                                    borderColor: "rgba(255,255,255,0.07)",
                                    background: "transparent",
                                    color: "rgba(255,255,255,0.4)",
                                  }}
                                  onClick={(e) => { e.stopPropagation(); toggleItem(relatedId); }}
                                >
                                  {relatedItem?.title}
                                  <ArrowRight size={8} className="ml-1" style={{ color: "rgba(255,255,255,0.15)" }} />
                                </Button>
                              );
                            })}
                          </div>
                        </div>
                      )}
                    </CardContent>
                  </Card>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
