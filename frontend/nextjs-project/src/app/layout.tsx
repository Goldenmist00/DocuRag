import type { Metadata } from "next";
import { Inria_Sans, JetBrains_Mono, Sora } from "next/font/google";
import "./globals.css";

const inriaSans = Inria_Sans({
  subsets: ["latin"],
  weight: ["300", "400", "700"],
  style: ["normal", "italic"],
  variable: "--font-inria",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-hero-mono",
  display: "swap",
});

const sora = Sora({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800"],
  variable: "--font-hero-display",
  display: "swap",
});

export const metadata: Metadata = {
  title: "MindSync — Search. Understand. Visualize. Learn.",
  description:
    "Ask questions, visualize concepts, generate flashcards, and verify answers — all grounded directly in your study material.",
  icons: {
    icon: "/logo.png",
    apple: "/logo.png",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${inriaSans.variable} ${jetbrainsMono.variable} ${sora.variable}`}>
      <body>{children}</body>
    </html>
  );
}
