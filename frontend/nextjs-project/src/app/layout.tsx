import type { Metadata } from "next";
import { Inria_Sans } from "next/font/google";
import "./globals.css";

const inriaSans = Inria_Sans({
  subsets: ["latin"],
  weight: ["300", "400", "700"],
  style: ["normal", "italic"],
  variable: "--font-inria",
  display: "swap",
});

export const metadata: Metadata = {
  title: "MindSync — Search. Understand. Visualize. Learn.",
  description:
    "Ask questions, visualize concepts, generate flashcards, and verify answers — all grounded directly in your study material.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={inriaSans.variable}>
      <body>{children}</body>
    </html>
  );
}
