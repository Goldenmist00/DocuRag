"use client";

import Link from "next/link";
import Image from "next/image";
import { usePathname } from "next/navigation";

/**
 * Persistent top navigation bar rendered on every page.
 * Shows the MindSync logo on the left side.
 * On the landing page (`/`), it's hidden since the hero header
 * already includes full navigation.
 */
export default function GlobalNav() {
  const pathname = usePathname();

  if (pathname === "/") return null;

  return (
    <nav
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        zIndex: 100,
        height: 52,
        display: "flex",
        alignItems: "center",
        justifyContent: "flex-start",
        padding: "0 20px",
        background: "rgba(0,0,0,0.55)",
        backdropFilter: "blur(14px)",
        WebkitBackdropFilter: "blur(14px)",
        borderBottom: "1px solid rgba(255,255,255,0.06)",
        pointerEvents: "auto",
      }}
    >
      <Link
        href="/"
        style={{
          position: "relative",
          display: "block",
          height: 36,
          width: 140,
          flexShrink: 0,
        }}
      >
        <Image
          src="/logo.png"
          alt="MindSync"
          fill
          sizes="140px"
          style={{ objectFit: "contain", objectPosition: "left center" }}
          priority
        />
      </Link>
    </nav>
  );
}
