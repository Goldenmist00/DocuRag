'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { listNotebooks, createNotebook, deleteNotebook, updateNotebookTitle, type Notebook } from '@/lib/api';
import { useToast } from '@/components/ui/toast';
import { authClient } from '@/lib/auth/client';

type Book = {
  id: string; title: string; date: string; sources: number;
};

/* ── Loading overlay (shared for create + open) ── */
function LoadingOverlay({ visible, mode }: { visible: boolean; mode: 'create' | 'open' }) {
  const [progress, setProgress] = useState(0);
  const [phase, setPhase] = useState(0);
  const rafRef = useRef<number | null>(null);
  const startRef = useRef<number | null>(null);

  useEffect(() => {
    if (!visible) { setProgress(0); setPhase(0); return; }
    const animate = (ts: number) => {
      if (!startRef.current) startRef.current = ts;
      const elapsed = ts - startRef.current;
      let p = 0;
      if (elapsed < 400)       { p = (elapsed / 400) * 70; setPhase(1); }
      else if (elapsed < 1200) { p = 70 + ((elapsed - 400) / 800) * 20; setPhase(2); }
      else                     { p = 90 + Math.min(((elapsed - 1200) / 200) * 10, 10); setPhase(3); }
      setProgress(Math.min(p, 100));
      if (p < 100) rafRef.current = requestAnimationFrame(animate);
    };
    rafRef.current = requestAnimationFrame(animate);
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current); startRef.current = null; };
  }, [visible]);

  if (!visible) return null;

  const isOpen = mode === 'open';

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 9999,
      background: '#000',
      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
      animation: 'overlayFadeIn 0.12s ease both',
    }}>
      {/* Top progress bar */}
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 2, background: '#111' }}>
        <div style={{
          height: '100%', width: `${progress}%`, background: '#fff',
          transition: phase === 1 ? 'width 0.05s linear' : phase === 2 ? 'width 0.3s ease' : 'width 0.15s ease',
          boxShadow: '0 0 8px rgba(255,255,255,0.6)',
        }} />
      </div>

      {/* Center content */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 20 }}>
        <div style={{ position: 'relative', width: 48, height: 48 }}>
          <svg width="48" height="48" viewBox="0 0 48 48" fill="none" style={{ animation: 'iconPulse 1.4s ease-in-out infinite' }}>
            <rect x="8" y="4" width="28" height="36" rx="3" fill="#111" stroke="#2a2a2a" strokeWidth="1.5" />
            {isOpen ? (
              /* Open book — lines animate in sequentially */
              <>
                <line x1="15" y1="14" x2="33" y2="14" stroke="#555" strokeWidth="1.5" strokeLinecap="round" style={{ animation: 'lineReveal 0.4s 0.0s ease both' }} />
                <line x1="15" y1="20" x2="33" y2="20" stroke="#444" strokeWidth="1.5" strokeLinecap="round" style={{ animation: 'lineReveal 0.4s 0.1s ease both' }} />
                <line x1="15" y1="26" x2="28" y2="26" stroke="#333" strokeWidth="1.5" strokeLinecap="round" style={{ animation: 'lineReveal 0.4s 0.2s ease both' }} />
                <line x1="15" y1="32" x2="22" y2="32" stroke="#2a2a2a" strokeWidth="1.5" strokeLinecap="round" style={{ animation: 'lineReveal 0.4s 0.3s ease both' }} />
              </>
            ) : (
              <>
                <rect x="8" y="4" width="28" height="36" rx="3" fill="none" stroke="#333" strokeWidth="1.5" strokeDasharray="4 3" />
                <line x1="15" y1="16" x2="33" y2="16" stroke="#444" strokeWidth="1.5" strokeLinecap="round" />
                <line x1="15" y1="22" x2="33" y2="22" stroke="#333" strokeWidth="1.5" strokeLinecap="round" />
                <line x1="15" y1="28" x2="26" y2="28" stroke="#2a2a2a" strokeWidth="1.5" strokeLinecap="round" />
              </>
            )}
          </svg>
          <div style={{
            position: 'absolute', top: -4, right: -4,
            width: 10, height: 10, borderRadius: '50%', background: '#fff',
            animation: 'orbitPulse 1.4s ease-in-out infinite',
          }} />
        </div>

        <div style={{ textAlign: 'center' }}>
          <p style={{ fontSize: 14, fontWeight: 500, color: '#fff', margin: '0 0 6px', letterSpacing: '-0.02em' }}>
            {isOpen ? 'Opening notebook' : 'Creating notebook'}
          </p>
          <p style={{ fontSize: 12, color: 'rgba(255,255,255,0.3)', margin: 0, letterSpacing: '-0.01em' }}>
            {isOpen ? 'Loading your sources…' : 'Setting up your workspace…'}
          </p>
        </div>

        <div style={{ display: 'flex', gap: 5 }}>
          {[0, 1, 2].map(i => (
            <div key={i} style={{
              width: 4, height: 4, borderRadius: '50%', background: 'rgba(255,255,255,0.4)',
              animation: `dotPulse 1.2s ease-in-out ${i * 0.2}s infinite`,
            }} />
          ))}
        </div>
      </div>
    </div>
  );
}

function NoteIcon({ size = 20 }: { size?: number }) {  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
      <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" stroke="rgba(255,255,255,0.35)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      <polyline points="14 2 14 8 20 8" stroke="rgba(255,255,255,0.35)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function BookCard({ book, view, openMenu, setOpenMenu, onOpen, onDelete, onRename }: {
  book: Book; view: 'grid' | 'list';
  openMenu: string | null; setOpenMenu: (id: string | null) => void;
  onOpen: (id: string) => void;
  onDelete: (id: string) => void;
  onRename: (id: string) => void;
}) {
  const [hovered, setHovered] = useState(false);

  return (
    <div style={{ position: 'relative' }}
      onClick={e => e.stopPropagation()}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <div onClick={() => onOpen(book.id)} style={{ textDecoration: 'none', cursor: 'pointer' }}>
        <div style={{
          height: view === 'grid' ? 172 : 64,
          borderRadius: 8,
          border: hovered ? '1px solid #333' : '1px solid #1f1f1f',
          background: hovered ? '#111' : '#0a0a0a',
          padding: view === 'grid' ? '16px' : '0 16px',
          cursor: 'pointer',
          display: 'flex',
          flexDirection: view === 'grid' ? 'column' : 'row',
          alignItems: view === 'grid' ? 'flex-start' : 'center',
          justifyContent: view === 'grid' ? 'space-between' : 'flex-start',
          gap: view === 'list' ? 14 : 0,
          position: 'relative',
          overflow: 'hidden',
          transition: 'border-color 0.15s ease, background 0.15s ease',
          minWidth: 0,
        }}>
          {view === 'grid' && (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }}>
              <NoteIcon />
              <button onClick={e => { e.preventDefault(); e.stopPropagation(); setOpenMenu(openMenu === book.id ? null : book.id); }}
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: hovered ? 'rgba(255,255,255,0.5)' : 'rgba(255,255,255,0.2)', padding: 4, borderRadius: 4, display: 'flex', alignItems: 'center', transition: 'color 0.15s' }}>
                <svg width="14" height="14" fill="currentColor" viewBox="0 0 24 24">
                  <circle cx="12" cy="5" r="1.5" /><circle cx="12" cy="12" r="1.5" /><circle cx="12" cy="19" r="1.5" />
                </svg>
              </button>
            </div>
          )}

          {view === 'grid' ? (
            <div style={{ width: '100%' }}>
              <p style={{ fontSize: 13, fontWeight: 500, color: hovered ? '#fff' : 'rgba(255,255,255,0.8)', margin: '0 0 10px', lineHeight: 1.45, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', letterSpacing: '-0.01em' }}>
                {book.title}
              </p>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.25)' }}>{book.sources} sources</span>
              </div>
            </div>
          ) : (
            <>
              <NoteIcon />
              <div style={{ flex: 1, minWidth: 0 }}>
                <p style={{ fontSize: 13, fontWeight: 500, color: hovered ? '#fff' : 'rgba(255,255,255,0.8)', margin: 0, overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis', letterSpacing: '-0.01em' }}>
                  {book.title}
                </p>
                <p style={{ fontSize: 11, color: 'rgba(255,255,255,0.25)', margin: '3px 0 0' }}>{book.date}</p>
              </div>
              <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.25)', flexShrink: 0, minWidth: 64, textAlign: 'right' }}>
                {book.sources} sources
              </span>
              <button onClick={e => { e.preventDefault(); e.stopPropagation(); setOpenMenu(openMenu === book.id ? null : book.id); }}
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: hovered ? 'rgba(255,255,255,0.5)' : 'rgba(255,255,255,0.2)', padding: 4, borderRadius: 4, flexShrink: 0, display: 'flex', alignItems: 'center', transition: 'color 0.15s' }}>
                <svg width="14" height="14" fill="currentColor" viewBox="0 0 24 24">
                  <circle cx="12" cy="5" r="1.5" /><circle cx="12" cy="12" r="1.5" /><circle cx="12" cy="19" r="1.5" />
                </svg>
              </button>
            </>
          )}
        </div>
      </div>

      {openMenu === book.id && (
        <div style={{ position: 'absolute', top: view === 'grid' ? 42 : 36, right: 8, zIndex: 100, background: '#111', border: '1px solid #222', borderRadius: 8, padding: 4, boxShadow: '0 8px 24px rgba(0,0,0,0.5)', minWidth: 140 }}>
          <DropdownItem label="Rename" icon="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" onClick={() => { setOpenMenu(null); onRename(book.id); }} />
          <DropdownItem label="Delete" icon="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" isDelete onClick={() => onDelete(book.id)} />
        </div>
      )}
    </div>
  );
}

function DropdownItem({ label, icon, isDelete, onClick }: { label: string; icon: string; isDelete?: boolean; onClick?: () => void }) {
  const [hov, setHov] = useState(false);
  return (
    <button onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}
      onClick={e => { e.preventDefault(); e.stopPropagation(); onClick?.(); }}
      style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', textAlign: 'left', background: hov ? '#1a1a1a' : 'none', border: 'none', cursor: 'pointer', padding: '7px 10px', fontSize: 12, color: isDelete ? (hov ? '#f87171' : '#ef4444') : (hov ? '#fff' : 'rgba(255,255,255,0.6)'), borderRadius: 6, fontFamily: 'inherit', transition: 'all 0.1s' }}>
      <svg width="12" height="12" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d={icon} />
      </svg>
      {label}
    </button>
  );
}

export default function BooksPage() {
  const router = useRouter();
  const [books, setBooks]       = useState<Book[]>([]);
  const [loading, setLoading]   = useState(true);
  const [search, setSearch]     = useState('');
  const [view, setView]         = useState<'grid' | 'list'>('grid');
  const [sort, setSort]         = useState<'recent' | 'alpha' | 'sources'>('recent');
  const [sortOpen, setSortOpen] = useState(false);
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const [tab, setTab]           = useState<'all' | 'mine'>('all');
  const [searchFocused, setSearchFocused] = useState(false);
  const [creating, setCreating] = useState(false);
  const [opening, setOpening]   = useState(false);
  const [renaming, setRenaming] = useState<{ id: string; title: string } | null>(null);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [user, setUser] = useState<{ name?: string; email?: string; image?: string } | null>(null);

  const SORT_OPTIONS: { key: typeof sort; label: string }[] = [
    { key: 'recent',  label: 'Most recent' },
    { key: 'alpha',   label: 'Alphabetical' },
    { key: 'sources', label: 'Most sources' },
  ];

  const fetchBooks = useCallback(async () => {
    try {
      const nbs = await listNotebooks();
      setBooks(nbs.map(nb => ({
        id: nb.id,
        title: nb.title,
        date: nb.updated_at ? new Date(nb.updated_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : '',
        sources: nb.source_count ?? 0,
      })));
    } catch {
      /* API may not be running yet — keep empty list */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchBooks(); }, [fetchBooks]);

  useEffect(() => {
    authClient.getSession().then(({ data }) => {
      if (data?.user) setUser(data.user);
    });
  }, []);

  const handleSignOut = async () => {
    try {
      await authClient.signOut();
    } catch {
      // ignore errors — clear session regardless
    }
    // Hard redirect to clear any cached state
    window.location.href = '/';
  };

  const { success: toastSuccess, error: toastError } = useToast();

  const handleCreate = async (e: React.MouseEvent) => {
    e.preventDefault();
    setCreating(true);
    try {
      const nb = await createNotebook();
      toastSuccess('Notebook created');
      router.push(`/dashboard?notebook=${nb.id}`);
    } catch {
      toastError('Failed to create notebook');
      setCreating(false);
    }
  };

  const handleOpen = (id: string) => {
    setOpening(true);
    setTimeout(() => router.push(`/dashboard?notebook=${id}`), 400);
  };

  const handleDelete = async (id: string) => {
    const name = books.find(b => b.id === id)?.title ?? 'Notebook';
    try {
      await deleteNotebook(id);
      setBooks(prev => prev.filter(b => b.id !== id));
      setOpenMenu(null);
      toastSuccess(`"${name}" deleted`);
    } catch {
      toastError(`Failed to delete "${name}"`);
    }
  };

  const handleRenameStart = (id: string) => {
    const book = books.find(b => b.id === id);
    if (book) setRenaming({ id, title: book.title });
  };

  const handleRenameSubmit = async () => {
    if (!renaming || !renaming.title.trim()) return;
    try {
      await updateNotebookTitle(renaming.id, renaming.title.trim());
      setBooks(prev => prev.map(b => b.id === renaming.id ? { ...b, title: renaming.title.trim() } : b));
      toastSuccess('Notebook renamed');
    } catch {
      toastError('Failed to rename notebook');
    }
    setRenaming(null);
  };

  const filtered = books
    .filter(b => b.title.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => {
      if (sort === 'alpha')   return a.title.localeCompare(b.title);
      if (sort === 'sources') return b.sources - a.sources;
      return new Date(b.date).getTime() - new Date(a.date).getTime();
    });

  return (
    <div
      style={{ minHeight: '100vh', background: '#000', color: '#fff', fontFamily: "var(--font-inria), 'Inria Sans', sans-serif" }}
      onClick={() => { setOpenMenu(null); setSortOpen(false); setUserMenuOpen(false); }}
    >
      <LoadingOverlay visible={creating} mode="create" />
      <LoadingOverlay visible={opening} mode="open" />
      {/* Header */}
      <header style={{ height: 56, background: '#000', borderBottom: '1px solid #1a1a1a', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 24px', position: 'sticky', top: 0, zIndex: 50 }}>
        <Link href="/" style={{ textDecoration: 'none', display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{ width: 110, height: 32, overflow: 'hidden', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <img src="/logo.png" alt="MindSync" style={{ height: 70, width: 154, objectFit: 'contain', flexShrink: 0 }} />
          </div>
        </Link>
        <div style={{ position: 'relative' }}>
          <div
            onClick={(e) => { e.stopPropagation(); setUserMenuOpen(o => !o); }}
            style={{ width: 32, height: 32, borderRadius: '50%', background: '#1a1a1a', border: '1px solid #2a2a2a', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 600, color: 'rgba(255,255,255,0.7)', cursor: 'pointer', overflow: 'hidden' }}
          >
            {user?.image
              ? <img src={user.image} alt={user.name ?? 'User'} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
              : (user?.name?.[0] ?? user?.email?.[0] ?? 'U').toUpperCase()
            }
          </div>
          {userMenuOpen && (
            <div
              onClick={e => e.stopPropagation()}
              style={{ position: 'absolute', top: 40, right: 0, background: '#111', border: '1px solid #222', borderRadius: 8, minWidth: 200, boxShadow: '0 8px 32px rgba(0,0,0,0.6)', zIndex: 100, overflow: 'hidden' }}
            >
              {user && (
                <div style={{ padding: '12px 14px', borderBottom: '1px solid #1f1f1f' }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: '#fff', marginBottom: 2 }}>{user.name ?? 'User'}</div>
                  <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)' }}>{user.email}</div>
                </div>
              )}
              <button
                onClick={handleSignOut}
                style={{ width: '100%', padding: '10px 14px', background: 'none', border: 'none', color: '#ff6b6b', fontSize: 13, fontFamily: 'inherit', cursor: 'pointer', textAlign: 'left', display: 'flex', alignItems: 'center', gap: 8, transition: 'background 0.15s' }}
                onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,107,107,0.08)')}
                onMouseLeave={e => (e.currentTarget.style.background = 'none')}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>
                </svg>
                Sign out
              </button>
            </div>
          )}
        </div>
      </header>

      {/* Toolbar */}
      <div style={{ background: '#000', borderBottom: '1px solid #1a1a1a', padding: '0 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', height: 52, gap: 12, position: 'sticky', top: 56, zIndex: 40 }}>
        {/* Tabs */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 0 }}>
          {(['all', 'mine'] as const).map(t => (
            <button key={t} onClick={() => setTab(t)} style={{ padding: '6px 14px', border: 'none', background: 'none', color: tab === t ? '#fff' : 'rgba(255,255,255,0.35)', fontSize: 13, fontWeight: tab === t ? 500 : 400, cursor: 'pointer', fontFamily: 'inherit', borderBottom: tab === t ? '1px solid #fff' : '1px solid transparent', transition: 'color 0.15s, border-color 0.15s', letterSpacing: '-0.01em' }}>
              {t === 'all' ? 'All notebooks' : 'My notebooks'}
            </button>
          ))}
        </div>

        {/* Right controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {/* Search */}
          <div style={{ position: 'relative' }}>
            <svg style={{ position: 'absolute', left: 9, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }} width="13" height="13" fill="none" stroke="rgba(255,255,255,0.3)" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input type="text" placeholder="Search…" value={search} onChange={e => setSearch(e.target.value)} onFocus={() => setSearchFocused(true)} onBlur={() => setSearchFocused(false)}
              style={{ background: '#0a0a0a', border: `1px solid ${searchFocused ? '#333' : '#1f1f1f'}`, borderRadius: 6, padding: '6px 12px 6px 28px', fontSize: 12, color: '#fff', outline: 'none', width: 180, fontFamily: 'inherit', transition: 'border-color 0.15s' }} />
          </div>

          {/* View toggle */}
          <div style={{ display: 'flex', background: '#0a0a0a', borderRadius: 6, padding: 2, border: '1px solid #1f1f1f', gap: 2 }}>
            {(['grid', 'list'] as const).map(v => (
              <button key={v} onClick={() => setView(v)} style={{ width: 28, height: 26, borderRadius: 4, border: 'none', background: view === v ? '#1f1f1f' : 'transparent', color: view === v ? '#fff' : 'rgba(255,255,255,0.3)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', transition: 'all 0.1s' }}>
                {v === 'grid'
                  ? <svg width="12" height="12" fill="currentColor" viewBox="0 0 24 24"><path d="M3 3h8v8H3V3zm10 0h8v8h-8V3zM3 13h8v8H3v-8zm10 0h8v8h-8v-8z" /></svg>
                  : <svg width="12" height="12" fill="currentColor" viewBox="0 0 24 24"><path d="M3 4h18v2H3V4zm0 7h18v2H3v-2zm0 7h18v2H3v-2z" /></svg>}
              </button>
            ))}
          </div>

          {/* Sort */}
          <div style={{ position: 'relative' }} onClick={e => e.stopPropagation()}>
            <button
              onClick={() => setSortOpen(o => !o)}
              style={{
                display: 'flex', alignItems: 'center', gap: 6,
                background: sortOpen ? '#111' : '#0a0a0a',
                border: `1px solid ${sortOpen ? '#333' : '#1f1f1f'}`,
                borderRadius: 6, padding: '6px 10px',
                fontSize: 12, color: 'rgba(255,255,255,0.55)',
                cursor: 'pointer', fontFamily: 'inherit',
                transition: 'border-color 0.15s, background 0.15s',
                whiteSpace: 'nowrap',
              }}
            >
              <svg width="11" height="11" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 6h18M7 12h10M11 18h2" />
              </svg>
              {SORT_OPTIONS.find(o => o.key === sort)?.label}
              <svg width="10" height="10" fill="none" stroke="currentColor" viewBox="0 0 24 24" style={{ opacity: 0.4, transform: sortOpen ? 'rotate(180deg)' : 'none', transition: 'transform 0.15s' }}>
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            {sortOpen && (
              <div style={{
                position: 'absolute', top: 'calc(100% + 6px)', right: 0,
                background: '#111', border: '1px solid #222',
                borderRadius: 8, padding: 4,
                boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
                minWidth: 148, zIndex: 100,
                display: 'flex', flexDirection: 'column', gap: 2,
              }}>
                {SORT_OPTIONS.map(opt => (
                  <button
                    key={opt.key}
                    onClick={() => { setSort(opt.key); setSortOpen(false); }}
                    style={{
                      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                      gap: 8, width: '100%', textAlign: 'left',
                      background: sort === opt.key ? '#1a1a1a' : 'none',
                      border: 'none', cursor: 'pointer',
                      padding: '7px 10px', fontSize: 12,
                      color: sort === opt.key ? '#fff' : 'rgba(255,255,255,0.55)',
                      borderRadius: 6, fontFamily: 'inherit',
                      transition: 'background 0.1s, color 0.1s',
                    }}
                    className="dropdown-item"
                  >
                    {opt.label}
                    {sort === opt.key && (
                      <svg width="11" height="11" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                      </svg>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>

          <button onClick={handleCreate} className="new-book-btn" style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 14px', background: '#fff', border: 'none', borderRadius: 6, color: '#000', fontSize: 12, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit', letterSpacing: '-0.01em', transition: 'background 0.15s, transform 0.15s, box-shadow 0.15s' }}>
            <svg width="11" height="11" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 4v16m8-8H4" />
            </svg>
            New notebook
          </button>
        </div>
      </div>

      {/* Main */}
      <main style={{ padding: '32px 24px', maxWidth: 1200, margin: '0 auto' }}>
        <div style={{ marginBottom: 24 }}>
          <p style={{ fontSize: 11, fontWeight: 500, color: 'rgba(255,255,255,0.3)', letterSpacing: '0.08em', textTransform: 'uppercase', margin: '0 0 6px' }}>Workspace</p>
          <h1 style={{ fontSize: 20, fontWeight: 600, color: '#fff', margin: 0, letterSpacing: '-0.03em' }}>
            Notebooks
            <span style={{ fontSize: 13, fontWeight: 400, color: 'rgba(255,255,255,0.25)', marginLeft: 8 }}>{filtered.length}</span>
          </h1>
        </div>

        <div style={view === 'grid' ? { display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 } : { display: 'flex', flexDirection: 'column', gap: 6 }}>
          <CreateCard view={view} onCreate={handleCreate} />
          {filtered.map(book => (
            <BookCard key={book.id} book={book} view={view} openMenu={openMenu} setOpenMenu={setOpenMenu} onOpen={handleOpen} onDelete={handleDelete} onRename={handleRenameStart} />
          ))}
        </div>
      </main>

      {/* Rename modal */}
      {renaming && (
        <div
          onClick={() => setRenaming(null)}
          style={{
            position: 'fixed', inset: 0, zIndex: 9000,
            background: 'rgba(0,0,0,0.45)', backdropFilter: 'blur(2px)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          <div
            onClick={e => e.stopPropagation()}
            style={{
              width: 380, background: '#0a0a0a', border: '1px solid #222',
              borderRadius: 12, padding: '22px 24px', boxShadow: '0 24px 60px rgba(0,0,0,0.6)',
              display: 'flex', flexDirection: 'column', gap: 16,
            }}
          >
            <p style={{ fontSize: 14, fontWeight: 600, color: 'rgba(255,255,255,0.9)', margin: 0 }}>
              Rename notebook
            </p>
            <input
              autoFocus
              value={renaming.title}
              onChange={e => setRenaming({ ...renaming, title: e.target.value })}
              onKeyDown={e => { if (e.key === 'Enter') handleRenameSubmit(); if (e.key === 'Escape') setRenaming(null); }}
              style={{
                width: '100%', padding: '9px 12px', borderRadius: 6,
                background: '#111', border: '1px solid #2a2a2a', outline: 'none',
                color: '#fff', fontSize: 13, fontFamily: 'inherit',
              }}
            />
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button
                onClick={() => setRenaming(null)}
                style={{
                  padding: '7px 14px', borderRadius: 6, border: '1px solid #2a2a2a',
                  background: 'transparent', color: 'rgba(255,255,255,0.5)',
                  fontSize: 12, fontFamily: 'inherit', cursor: 'pointer',
                }}
              >
                Cancel
              </button>
              <button
                onClick={handleRenameSubmit}
                style={{
                  padding: '7px 14px', borderRadius: 6, border: 'none',
                  background: '#fff', color: '#000',
                  fontSize: 12, fontWeight: 600, fontFamily: 'inherit', cursor: 'pointer',
                }}
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function CreateButton() {
  const [hov, setHov] = useState(false);
  return (
    <button onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}
      style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 14px', background: hov ? '#f0f0f0' : '#fff', border: 'none', borderRadius: 6, color: '#000', fontSize: 12, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit', transition: 'background 0.1s', letterSpacing: '-0.01em' }}>
      <svg width="11" height="11" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 4v16m8-8H4" />
      </svg>
      New notebook
    </button>
  );
}

function CreateCard({ view, onCreate }: { view: 'grid' | 'list'; onCreate: (e: React.MouseEvent) => void }) {
  const [hov, setHov] = useState(false);
  return (
    <div onClick={onCreate} onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}
      style={{ height: view === 'grid' ? 172 : 64, borderRadius: 8, border: `1px dashed ${hov ? '#333' : '#1f1f1f'}`, background: hov ? '#0a0a0a' : 'transparent', display: 'flex', flexDirection: view === 'grid' ? 'column' : 'row', alignItems: 'center', justifyContent: 'center', gap: 8, cursor: 'pointer', transition: 'border-color 0.15s, background 0.15s' }}>
      <div style={{ width: 28, height: 28, borderRadius: '50%', background: hov ? '#1a1a1a' : 'transparent', border: `1px solid ${hov ? '#333' : '#222'}`, display: 'flex', alignItems: 'center', justifyContent: 'center', color: hov ? 'rgba(255,255,255,0.6)' : 'rgba(255,255,255,0.2)', fontSize: 18, fontWeight: 300, transition: 'all 0.15s' }}>+</div>
      <span style={{ fontSize: 12, color: hov ? 'rgba(255,255,255,0.5)' : 'rgba(255,255,255,0.2)', transition: 'color 0.15s' }}>New notebook</span>
    </div>
  );
}
