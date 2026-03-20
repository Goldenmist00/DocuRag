'use client';

import Image from 'next/image';
import Link from 'next/link';
import { useEffect } from 'react';
import { BookOpen, Search, ShieldCheck, LayoutDashboard, Sparkles } from 'lucide-react';

export default function HeroAscii() {
  useEffect(() => {
    const embedScript = document.createElement('script');
    embedScript.type = 'text/javascript';
    embedScript.textContent = `
      !function(){
        if(!window.UnicornStudio){
          window.UnicornStudio={isInitialized:!1};
          var i=document.createElement("script");
          i.src="https://cdn.jsdelivr.net/gh/hiunicornstudio/unicornstudio.js@v1.4.33/dist/unicornStudio.umd.js";
          i.onload=function(){
            window.UnicornStudio.isInitialized||(UnicornStudio.init(),window.UnicornStudio.isInitialized=!0)
          };
          (document.head || document.body).appendChild(i)
        }
      }();
    `;
    document.head.appendChild(embedScript);

    const style = document.createElement('style');
    style.textContent = `
      [data-us-project] {
        position: relative !important;
        overflow: hidden !important;
      }
      [data-us-project] canvas {
        clip-path: inset(0 0 10% 0) !important;
      }
      [data-us-project] * {
        pointer-events: none !important;
      }
      [data-us-project] a[href*="unicorn"],
      [data-us-project] button[title*="unicorn"],
      [data-us-project] div[title*="Made with"],
      [data-us-project] .unicorn-brand,
      [data-us-project] [class*="brand"],
      [data-us-project] [class*="credit"],
      [data-us-project] [class*="watermark"] {
        display: none !important;
        visibility: hidden !important;
        opacity: 0 !important;
        position: absolute !important;
        left: -9999px !important;
        top: -9999px !important;
      }
    `;
    document.head.appendChild(style);

    const hideBranding = () => {
      const projectDiv = document.querySelector('[data-us-project]');
      if (projectDiv) {
        const allElements = projectDiv.querySelectorAll('*');
        allElements.forEach(el => {
          const text = (el.textContent || '').toLowerCase();
          if (text.includes('made with') || text.includes('unicorn')) {
            el.remove();
          }
        });
      }
    };

    hideBranding();
    const interval = setInterval(hideBranding, 100);
    setTimeout(hideBranding, 1000);
    setTimeout(hideBranding, 3000);
    setTimeout(hideBranding, 5000);

    return () => {
      clearInterval(interval);
      if (document.head.contains(embedScript)) document.head.removeChild(embedScript);
      if (document.head.contains(style)) document.head.removeChild(style);
    };
  }, []);

  return (
    <section className="relative min-h-screen overflow-hidden bg-[#060609]">
      {/* Vitruvian man animation — desktop */}
      <div className="absolute inset-0 w-full h-full hidden lg:block">
        <div
          data-us-project="whwOGlfJ5Rz2rHaEUgHl"
          style={{ width: '100%', height: '100%', minHeight: '100vh' }}
        />
      </div>

      {/* Stars fallback — mobile / tablet */}
      <div className="absolute inset-0 w-full h-full lg:hidden stars-bg" />

      {/* Soft vignette overlay */}
      <div className="absolute inset-0 z-[1] pointer-events-none bg-[radial-gradient(ellipse_at_center,transparent_40%,rgba(6,6,9,0.7)_100%)]" />

      {/* ── Top Header ── */}
      <header className="absolute top-0 left-0 right-0 z-30 border-b border-white/[0.07] bg-black/20 backdrop-blur-sm">
        <div className="mx-auto max-w-7xl px-6 sm:px-8 md:px-10 lg:px-14 py-5 lg:py-6 flex items-center justify-between">
          <Link href="/" className="relative shrink-0 block" style={{ height: '100px', width: '250px' }}>
            <Image
              src="/logo.png"
              alt="MindSync"
              fill
              className="object-contain"
              priority
            />
          </Link>

          <nav className="hidden md:flex items-center gap-3 lg:gap-4" style={{ fontFamily: 'var(--font-hero-mono)' }}>
            <Link href="#features" className="flex items-center gap-2.5 px-5 py-2.5 rounded-md text-sm tracking-[0.12em] uppercase text-white/40 hover:text-white/80 hover:bg-white/[0.04] transition-all duration-200">
              <Sparkles size={16} className="opacity-50" />
              Features
            </Link>
            <Link href="#search" className="flex items-center gap-2.5 px-5 py-2.5 rounded-md text-sm tracking-[0.12em] uppercase text-white/40 hover:text-white/80 hover:bg-white/[0.04] transition-all duration-200">
              <Search size={16} className="opacity-50" />
              Search
            </Link>
            <Link href="#docs" className="flex items-center gap-2.5 px-5 py-2.5 rounded-md text-sm tracking-[0.12em] uppercase text-white/40 hover:text-white/80 hover:bg-white/[0.04] transition-all duration-200">
              <BookOpen size={16} className="opacity-50" />
              Docs
            </Link>
            <Link href="#citations" className="flex items-center gap-2.5 px-5 py-2.5 rounded-md text-sm tracking-[0.12em] uppercase text-white/40 hover:text-white/80 hover:bg-white/[0.04] transition-all duration-200">
              <ShieldCheck size={16} className="opacity-50" />
              Citations
            </Link>
            <div className="w-px h-6 bg-white/[0.08] mx-3" />
            <Link href="/signup" className="flex items-center gap-2.5 px-6 py-2.5 rounded-md text-sm tracking-[0.12em] uppercase bg-white text-[#060609] font-semibold hover:bg-white/90 transition-all duration-200">
              <LayoutDashboard size={16} />
              Dashboard
            </Link>
          </nav>
        </div>
      </header>

      {/* ── Corner frame accents ── */}
      <div className="absolute top-0 left-0 w-5 h-5 sm:w-7 sm:h-7 lg:w-9 lg:h-9 border-t border-l border-white/[0.12] z-20" />
      <div className="absolute top-0 right-0 w-5 h-5 sm:w-7 sm:h-7 lg:w-9 lg:h-9 border-t border-r border-white/[0.12] z-20" />
      <div className="absolute bottom-12 sm:bottom-14 left-0 w-5 h-5 sm:w-7 sm:h-7 lg:w-9 lg:h-9 border-b border-l border-white/[0.12] z-20" />
      <div className="absolute bottom-12 sm:bottom-14 right-0 w-5 h-5 sm:w-7 sm:h-7 lg:w-9 lg:h-9 border-b border-r border-white/[0.12] z-20" />

      {/* ── Hero content ── */}
      <div className="absolute inset-0 z-10 flex items-center" style={{ paddingLeft: '5%' }}>
        <div style={{ maxWidth: '26rem', width: '100%' }}>

            {/* Decorative rule */}
            <div className="flex items-center gap-2.5 mb-5 sm:mb-6 opacity-40">
              <div className="w-5 sm:w-7 h-px bg-gradient-to-r from-white/60 to-transparent" />
              <span className="text-white/50 text-[9px] tracking-[0.3em] uppercase" style={{ fontFamily: 'var(--font-hero-mono)' }}>001</span>
              <div className="flex-1 h-px bg-gradient-to-r from-white/20 to-transparent" />
            </div>

            {/* Title */}
            <h1 className="font-bold text-white leading-[1.05] tracking-[0.06em] text-3xl sm:text-4xl md:text-[2.75rem] lg:text-5xl xl:text-[3.4rem]" style={{ fontFamily: 'var(--font-hero-display)' }}>
              SEARCH
              <span className="block mt-1.5 sm:mt-2 lg:mt-3 bg-gradient-to-r from-white via-white/90 to-white/60 bg-clip-text text-transparent">
                WITH PROOF
              </span>
            </h1>

            {/* Thin accent line below title */}
            <div className="mt-5 sm:mt-6 mb-5 sm:mb-6 flex items-center gap-3 opacity-25">
              <div className="h-px flex-1 max-w-[180px] bg-gradient-to-r from-[#7352DD]/60 via-[#A78BFA]/40 to-transparent" />
              <div className="w-1 h-1 rounded-full bg-[#A78BFA]/50" />
            </div>

            {/* Description */}
            <p className="text-[13px] sm:text-sm lg:text-[0.94rem] text-white/40 leading-[1.8] max-w-sm mb-20 sm:mb-24 lg:mb-28" style={{ fontFamily: 'var(--font-hero-body)' }}>
              Ask questions, generate flashcards, and map textbook ideas with grounded answers tied back to the source material.
            </p>

            {/* Buttons */}
            <div className="flex flex-col sm:flex-row gap-5" style={{ marginTop: '80px' }}>
              <Link
                href="/signup"
                className="group relative inline-flex items-center justify-center gap-3 px-14 py-5 bg-white text-[#060609] text-base tracking-[0.12em] font-bold uppercase rounded-md transition-all duration-300 hover:bg-[#A78BFA] hover:text-white hover:shadow-[0_0_40px_rgba(167,139,250,0.3)] hover:scale-[1.02]"
                style={{ fontFamily: 'var(--font-hero-mono)' }}
              >
                Get Started
                <svg className="w-5 h-5 transition-transform duration-300 group-hover:translate-x-1" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M17.25 8.25L21 12m0 0l-3.75 3.75M21 12H3" />
                </svg>
              </Link>

              <Link
                href="#features"
                className="inline-flex items-center justify-center px-14 py-5 border border-white/20 text-white/70 text-base tracking-[0.12em] font-medium uppercase rounded-md transition-all duration-300 hover:border-white/40 hover:text-white hover:bg-white/5 hover:scale-[1.02]"
                style={{ fontFamily: 'var(--font-hero-mono)' }}
              >
                Learn More
              </Link>
            </div>

            {/* Bottom notation */}
            <div className="hidden md:flex items-center gap-2.5 mt-10 lg:mt-14 opacity-20">
              <span className="text-white text-[9px] tracking-[0.2em]" style={{ fontFamily: 'var(--font-hero-mono)' }}>∞</span>
              <div className="flex-1 h-px bg-gradient-to-r from-white/40 to-transparent" />
              <span className="text-white text-[9px] tracking-[0.25em] uppercase" style={{ fontFamily: 'var(--font-hero-mono)' }}>Grounded Retrieval</span>
            </div>
        </div>
      </div>

      {/* ── Bottom status bar ── */}
      <footer className="absolute bottom-0 left-0 right-0 z-20 border-t border-white/[0.06] bg-[#060609]/60 backdrop-blur-md">
        <div className="mx-auto max-w-7xl px-5 sm:px-6 md:px-8 lg:px-12 py-2.5 flex items-center justify-between">
          <div className="flex items-center gap-3 lg:gap-5 text-[7px] sm:text-[8px] lg:text-[9px] text-white/25 tracking-[0.15em]" style={{ fontFamily: 'var(--font-hero-mono)' }}>
            <span className="hidden sm:inline">SYSTEM.ACTIVE</span>
            <span className="sm:hidden">SYS.ACT</span>
            <div className="hidden md:flex gap-[2px]">
              {[5, 8, 4, 10, 7, 3, 9, 6].map((h, i) => (
                <div key={i} className="w-[2px] rounded-[1px] bg-white/15" style={{ height: h }} />
              ))}
            </div>
            <span>RAG.V1</span>
          </div>

          <div className="flex items-center gap-2.5 lg:gap-4 text-[7px] sm:text-[8px] lg:text-[9px] text-white/25 tracking-[0.15em]" style={{ fontFamily: 'var(--font-hero-mono)' }}>
            <span className="hidden md:inline">RENDERING</span>
            <div className="flex gap-1">
              <div className="w-1 h-1 bg-[#A78BFA]/50 rounded-full animate-pulse" />
              <div className="w-1 h-1 bg-[#A78BFA]/30 rounded-full animate-pulse" style={{ animationDelay: '0.2s' }} />
              <div className="w-1 h-1 bg-[#A78BFA]/15 rounded-full animate-pulse" style={{ animationDelay: '0.4s' }} />
            </div>
            <span className="hidden md:inline">FRAME: ∞</span>
          </div>
        </div>
      </footer>

      <style jsx>{`
        .stars-bg {
          background-image:
            radial-gradient(1px 1px at 20% 30%, rgba(167,139,250,0.4), transparent),
            radial-gradient(1px 1px at 60% 70%, white, transparent),
            radial-gradient(1px 1px at 50% 50%, rgba(167,139,250,0.3), transparent),
            radial-gradient(1px 1px at 80% 10%, white, transparent),
            radial-gradient(1px 1px at 90% 60%, rgba(167,139,250,0.3), transparent),
            radial-gradient(1px 1px at 33% 80%, white, transparent),
            radial-gradient(1px 1px at 15% 60%, rgba(167,139,250,0.2), transparent),
            radial-gradient(1px 1px at 70% 40%, white, transparent);
          background-size: 200% 200%, 180% 180%, 250% 250%, 220% 220%, 190% 190%, 240% 240%, 210% 210%, 230% 230%;
          background-position: 0% 0%, 40% 40%, 60% 60%, 20% 20%, 80% 80%, 30% 30%, 70% 70%, 50% 50%;
          opacity: 0.25;
        }
      `}</style>
    </section>
  );
}
