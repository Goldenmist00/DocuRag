'use client';

import { useState, useEffect, useCallback, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import {
  listRepos,
  createRepo,
  deleteRepo,
  getGitHubStatus,
  getGitHubAuthUrl,
  disconnectGitHub,
  type Repo,
  type GitHubStatus,
} from '@/lib/api';
import { useToast } from '@/components/ui/toast';
import { authClient } from '@/lib/auth/client';

type RepoCard = {
  id: string;
  name: string;
  remoteUrl: string;
  status: string;
  phase: string;
  progress: number;
  detail: string;
  totalFiles: number;
  indexedFiles: number;
  lastIndexed: string | null;
};

function RepoIcon({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
      <path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 00-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0020 4.77 5.07 5.07 0 0019.91 1S18.73.65 16 2.48a13.38 13.38 0 00-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 005 4.77a5.44 5.44 0 00-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 009 18.13V22"
        stroke="rgba(255,255,255,0.35)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function StatusBadge({ status, progress }: { status: string; progress: number }) {
  const isComplete = status === 'completed' || status === 'ready';
  const isIndexing = status === 'indexing' || status === 'cloning' || status === 'consolidating';
  const isFailed = status === 'failed' || status === 'error';

  const bg = isComplete ? 'rgba(34,197,94,0.1)' : isIndexing ? 'rgba(234,179,8,0.1)' : isFailed ? 'rgba(239,68,68,0.1)' : 'rgba(255,255,255,0.05)';
  const color = isComplete ? '#22c55e' : isIndexing ? '#eab308' : isFailed ? '#ef4444' : 'rgba(255,255,255,0.4)';
  const label = isComplete ? 'Ready' : isIndexing ? `${status.charAt(0).toUpperCase() + status.slice(1)} ${progress > 0 ? `${progress}%` : ''}`.trim() : isFailed ? 'Failed' : status;

  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      padding: '3px 8px', borderRadius: 4,
      background: bg, color, fontSize: 10, fontWeight: 500,
      letterSpacing: '0.02em',
    }}>
      {isIndexing && (
        <span style={{
          width: 6, height: 6, borderRadius: '50%', background: color,
          animation: 'dotPulse 1.2s ease-in-out infinite',
        }} />
      )}
      {label}
    </span>
  );
}

function RepoCardComponent({ repo, view, openMenu, setOpenMenu, onOpen, onDelete }: {
  repo: RepoCard;
  view: 'grid' | 'list';
  openMenu: string | null;
  setOpenMenu: (id: string | null) => void;
  onOpen: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  const [hovered, setHovered] = useState(false);

  const repoNameFromUrl = (url: string): string => {
    const match = url.match(/([^/]+?)(\.git)?$/);
    return match ? match[1] : url;
  };

  const displayName = repo.name || repoNameFromUrl(repo.remoteUrl);

  return (
    <div style={{ position: 'relative' }}
      onClick={e => e.stopPropagation()}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <div onClick={() => onOpen(repo.id)} style={{ textDecoration: 'none', cursor: 'pointer' }}>
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
              <RepoIcon />
              <button onClick={e => { e.preventDefault(); e.stopPropagation(); setOpenMenu(openMenu === repo.id ? null : repo.id); }}
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: hovered ? 'rgba(255,255,255,0.5)' : 'rgba(255,255,255,0.2)', padding: 4, borderRadius: 4, display: 'flex', alignItems: 'center', transition: 'color 0.15s' }}>
                <svg width="14" height="14" fill="currentColor" viewBox="0 0 24 24">
                  <circle cx="12" cy="5" r="1.5" /><circle cx="12" cy="12" r="1.5" /><circle cx="12" cy="19" r="1.5" />
                </svg>
              </button>
            </div>
          )}

          {view === 'grid' ? (
            <div style={{ width: '100%' }}>
              <p style={{ fontSize: 13, fontWeight: 500, color: hovered ? '#fff' : 'rgba(255,255,255,0.8)', margin: '0 0 8px', lineHeight: 1.45, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', letterSpacing: '-0.01em' }}>
                {displayName}
              </p>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <StatusBadge status={repo.status} progress={repo.progress} />
                <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.25)' }}>{repo.totalFiles} files</span>
              </div>
            </div>
          ) : (
            <>
              <RepoIcon />
              <div style={{ flex: 1, minWidth: 0 }}>
                <p style={{ fontSize: 13, fontWeight: 500, color: hovered ? '#fff' : 'rgba(255,255,255,0.8)', margin: 0, overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis', letterSpacing: '-0.01em' }}>
                  {displayName}
                </p>
                <p style={{ fontSize: 11, color: 'rgba(255,255,255,0.25)', margin: '3px 0 0', overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' }}>
                  {repo.remoteUrl}
                </p>
              </div>
              <StatusBadge status={repo.status} progress={repo.progress} />
              <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.25)', flexShrink: 0, minWidth: 64, textAlign: 'right' }}>
                {repo.totalFiles} files
              </span>
              <button onClick={e => { e.preventDefault(); e.stopPropagation(); setOpenMenu(openMenu === repo.id ? null : repo.id); }}
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: hovered ? 'rgba(255,255,255,0.5)' : 'rgba(255,255,255,0.2)', padding: 4, borderRadius: 4, flexShrink: 0, display: 'flex', alignItems: 'center', transition: 'color 0.15s' }}>
                <svg width="14" height="14" fill="currentColor" viewBox="0 0 24 24">
                  <circle cx="12" cy="5" r="1.5" /><circle cx="12" cy="12" r="1.5" /><circle cx="12" cy="19" r="1.5" />
                </svg>
              </button>
            </>
          )}

          {/* Indexing progress bar for grid view */}
          {view === 'grid' && (repo.status === 'indexing' || repo.status === 'cloning' || repo.status === 'consolidating') && (
            <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, height: 2, background: '#1a1a1a' }}>
              <div style={{ height: '100%', width: `${repo.progress}%`, background: '#eab308', transition: 'width 0.3s ease' }} />
            </div>
          )}
        </div>
      </div>

      {openMenu === repo.id && (
        <div style={{ position: 'absolute', top: view === 'grid' ? 42 : 36, right: 8, zIndex: 100, background: '#111', border: '1px solid #222', borderRadius: 8, padding: 4, boxShadow: '0 8px 24px rgba(0,0,0,0.5)', minWidth: 140 }}>
          <DropdownItem label="Delete" icon="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" isDelete onClick={() => onDelete(repo.id)} />
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

/**
 * Maps raw Repo API data to the display-friendly RepoCard type.
 * @param repo - Raw repo object from the API
 * @returns RepoCard for rendering
 */
function toRepoCard(repo: Repo): RepoCard {
  return {
    id: repo.id,
    name: repo.name,
    remoteUrl: repo.remote_url,
    status: repo.indexing_status,
    phase: repo.indexing_phase,
    progress: repo.indexing_progress,
    detail: repo.indexing_detail,
    totalFiles: repo.total_files,
    indexedFiles: repo.indexed_files,
    lastIndexed: repo.last_indexed_at,
  };
}

export default function ReposPage() {
  return (
    <Suspense>
      <ReposPageInner />
    </Suspense>
  );
}

function ReposPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const notebookId = searchParams.get('notebook');

  const [repos, setRepos] = useState<RepoCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [view, setView] = useState<'grid' | 'list'>('grid');
  const [sort, setSort] = useState<'recent' | 'alpha' | 'files'>('recent');
  const [sortOpen, setSortOpen] = useState(false);
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const [searchFocused, setSearchFocused] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [user, setUser] = useState<{ name?: string; email?: string; image?: string } | null>(null);

  const [addOpen, setAddOpen] = useState(false);
  const [repoUrl, setRepoUrl] = useState('');
  const [authToken, setAuthToken] = useState('');
  const [adding, setAdding] = useState(false);

  const [ghStatus, setGhStatus] = useState<GitHubStatus>({ connected: false });
  useEffect(() => {
    getGitHubStatus().then(setGhStatus).catch(() => {});
    const onFocus = () => { getGitHubStatus().then(setGhStatus).catch(() => {}); };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, []);

  const SORT_OPTIONS: { key: typeof sort; label: string }[] = [
    { key: 'recent', label: 'Most recent' },
    { key: 'alpha', label: 'Alphabetical' },
    { key: 'files', label: 'Most files' },
  ];

  const { success: toastSuccess, error: toastError } = useToast();

  const fetchRepos = useCallback(async () => {
    try {
      const raw = await listRepos();
      setRepos(raw.map(toRepoCard));
    } catch {
      /* API may not be running yet */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchRepos(); }, [fetchRepos]);

  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const raw = await listRepos();
        setRepos(raw.map(toRepoCard));
      } catch { /* ignore */ }
    }, 5000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    authClient.getSession().then(({ data }) => {
      if (data?.user) setUser(data.user);
    });
  }, []);

  const handleSignOut = async () => {
    try {
      await authClient.signOut();
    } catch { /* ignore */ }
    window.location.href = '/';
  };

  const handleAddRepo = async () => {
    if (!repoUrl.trim()) return;
    setAdding(true);
    try {
      const newRepo = await createRepo(repoUrl.trim(), authToken.trim() || undefined);
      setRepos(prev => [toRepoCard(newRepo), ...prev]);
      toastSuccess('Repository added — indexing started');
      setAddOpen(false);
      setRepoUrl('');
      setAuthToken('');
    } catch (err) {
      toastError(err instanceof Error ? err.message : 'Failed to add repository');
    } finally {
      setAdding(false);
    }
  };

  const handleDelete = async (id: string) => {
    const name = repos.find(r => r.id === id)?.name ?? 'Repository';
    try {
      await deleteRepo(id);
      setRepos(prev => prev.filter(r => r.id !== id));
      setOpenMenu(null);
      toastSuccess(`"${name}" deleted`);
    } catch {
      toastError(`Failed to delete "${name}"`);
    }
  };

  const handleOpen = (id: string) => {
    const params = notebookId ? `?notebook=${notebookId}` : '';
    router.push(`/repos/${id}${params}`);
  };

  const filtered = repos
    .filter(r => {
      const q = search.toLowerCase();
      return r.name.toLowerCase().includes(q) || r.remoteUrl.toLowerCase().includes(q);
    })
    .sort((a, b) => {
      if (sort === 'alpha') return a.name.localeCompare(b.name);
      if (sort === 'files') return b.totalFiles - a.totalFiles;
      return (b.lastIndexed ?? '').localeCompare(a.lastIndexed ?? '');
    });

  return (
    <div
      style={{ minHeight: '100vh', paddingTop: 52, background: '#000', color: '#fff', fontFamily: "var(--font-inria), 'Inria Sans', sans-serif" }}
      onClick={() => { setOpenMenu(null); setSortOpen(false); setUserMenuOpen(false); }}
    >
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
                  <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><polyline points="16 17 21 12 16 7" /><line x1="21" y1="12" x2="9" y2="12" />
                </svg>
                Sign out
              </button>
            </div>
          )}
        </div>
      </header>

      {/* Toolbar */}
      <div style={{ background: '#000', borderBottom: '1px solid #1a1a1a', padding: '0 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', height: 52, gap: 12, position: 'sticky', top: 56, zIndex: 40 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 0 }}>
          <Link href="/books" style={{
            padding: '6px 14px', textDecoration: 'none',
            color: 'rgba(255,255,255,0.35)', fontSize: 13, fontWeight: 400,
            borderBottom: '1px solid transparent', transition: 'color 0.15s',
          }}>
            Notebooks
          </Link>
          <span style={{
            padding: '6px 14px', color: '#fff', fontSize: 13, fontWeight: 500,
            borderBottom: '1px solid #fff', cursor: 'default',
          }}>
            Repositories
          </span>
          {notebookId && (
            <>
              <div style={{ width: 1, height: 16, background: 'rgba(255,255,255,0.08)', margin: '0 8px' }} />
              <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.3)', padding: '4px 8px', background: 'rgba(255,255,255,0.04)', borderRadius: 4 }}>
                Linking to notebook
              </span>
            </>
          )}
        </div>

        {/* Right controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {/* Search */}
          <div style={{ position: 'relative' }}>
            <svg style={{ position: 'absolute', left: 9, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }} width="13" height="13" fill="none" stroke="rgba(255,255,255,0.3)" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input type="text" placeholder="Search..." value={search} onChange={e => setSearch(e.target.value)} onFocus={() => setSearchFocused(true)} onBlur={() => setSearchFocused(false)}
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

          {ghStatus.connected ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 0, borderRadius: 6, border: '1px solid rgba(255,255,255,0.1)', overflow: 'hidden' }}>
              <span style={{
                display: 'inline-flex', alignItems: 'center', gap: 4,
                fontSize: 11, color: 'rgba(255,255,255,0.45)',
                padding: '5px 10px',
                background: 'rgba(255,255,255,0.03)',
                letterSpacing: '0.02em',
              }}>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.374 0 0 5.373 0 12c0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23A11.509 11.509 0 0112 5.803c1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576C20.566 21.797 24 17.3 24 12c0-6.627-5.373-12-12-12z"/></svg>
                @{ghStatus.github_user}
              </span>
              <button
                onClick={async () => { await disconnectGitHub(); setGhStatus({ connected: false }); toastSuccess('GitHub disconnected'); }}
                style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  width: 26, height: 26, padding: 0,
                  background: 'none', border: 'none', borderLeft: '1px solid rgba(255,255,255,0.08)',
                  color: 'rgba(255,255,255,0.25)', cursor: 'pointer',
                  transition: 'color 0.15s, background 0.15s',
                }}
                title="Disconnect GitHub"
                onMouseEnter={e => { e.currentTarget.style.color = '#ef4444'; e.currentTarget.style.background = 'rgba(239,68,68,0.08)'; }}
                onMouseLeave={e => { e.currentTarget.style.color = 'rgba(255,255,255,0.25)'; e.currentTarget.style.background = 'none'; }}
              >
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M18 6L6 18M6 6l12 12"/></svg>
              </button>
            </div>
          ) : (
            <button
              onClick={async () => { const url = await getGitHubAuthUrl(); window.open(url, "github-auth", "width=600,height=700"); }}
              style={{
                display: 'flex', alignItems: 'center', gap: 6,
                fontSize: 11, color: 'rgba(255,255,255,0.45)',
                background: 'none', border: '1px solid rgba(255,255,255,0.1)',
                borderRadius: 6, padding: '5px 10px',
                cursor: 'pointer', fontFamily: 'inherit',
                transition: 'border-color 0.15s, color 0.15s',
              }}
              onMouseEnter={e => { e.currentTarget.style.borderColor = 'rgba(255,255,255,0.25)'; e.currentTarget.style.color = 'rgba(255,255,255,0.7)'; }}
              onMouseLeave={e => { e.currentTarget.style.borderColor = 'rgba(255,255,255,0.1)'; e.currentTarget.style.color = 'rgba(255,255,255,0.45)'; }}
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.374 0 0 5.373 0 12c0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23A11.509 11.509 0 0112 5.803c1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576C20.566 21.797 24 17.3 24 12c0-6.627-5.373-12-12-12z"/></svg>
              Connect GitHub
            </button>
          )}

          <button onClick={() => setAddOpen(true)} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 14px', background: '#fff', border: 'none', borderRadius: 6, color: '#000', fontSize: 12, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit', letterSpacing: '-0.01em', transition: 'background 0.15s, transform 0.15s, box-shadow 0.15s' }}>
            <svg width="11" height="11" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 4v16m8-8H4" />
            </svg>
            Add repo
          </button>
        </div>
      </div>

      {/* Main */}
      <main style={{ padding: '32px 24px', maxWidth: 1200, margin: '0 auto' }}>
        <div style={{ marginBottom: 24 }}>
          <p style={{ fontSize: 11, fontWeight: 500, color: 'rgba(255,255,255,0.3)', letterSpacing: '0.08em', textTransform: 'uppercase', margin: '0 0 6px' }}>Workspace</p>
          <h1 style={{ fontSize: 20, fontWeight: 600, color: '#fff', margin: 0, letterSpacing: '-0.03em' }}>
            Repositories
            <span style={{ fontSize: 13, fontWeight: 400, color: 'rgba(255,255,255,0.25)', marginLeft: 8 }}>{filtered.length}</span>
          </h1>
        </div>

        {loading ? (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 200 }}>
            <div style={{ display: 'flex', gap: 5 }}>
              {[0, 1, 2].map(i => (
                <div key={i} style={{
                  width: 5, height: 5, borderRadius: '50%', background: 'rgba(255,255,255,0.3)',
                  animation: `dotPulse 1.2s ease-in-out ${i * 0.2}s infinite`,
                }} />
              ))}
            </div>
          </div>
        ) : (
          <div style={view === 'grid' ? { display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 } : { display: 'flex', flexDirection: 'column', gap: 6 }}>
            <AddRepoCard view={view} onAdd={() => setAddOpen(true)} />
            {filtered.map(repo => (
              <RepoCardComponent key={repo.id} repo={repo} view={view} openMenu={openMenu} setOpenMenu={setOpenMenu} onOpen={handleOpen} onDelete={handleDelete} />
            ))}
          </div>
        )}
      </main>

      {/* Add repo modal */}
      {addOpen && (
        <div
          onClick={() => { if (!adding) { setAddOpen(false); setRepoUrl(''); setAuthToken(''); } }}
          style={{
            position: 'fixed', inset: 0, zIndex: 9000,
            background: 'rgba(0,0,0,0.45)', backdropFilter: 'blur(2px)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          <div
            onClick={e => e.stopPropagation()}
            style={{
              width: 420, background: '#0a0a0a', border: '1px solid #222',
              borderRadius: 12, padding: '22px 24px', boxShadow: '0 24px 60px rgba(0,0,0,0.6)',
              display: 'flex', flexDirection: 'column', gap: 16,
            }}
          >
            <p style={{ fontSize: 14, fontWeight: 600, color: 'rgba(255,255,255,0.9)', margin: 0 }}>
              Add repository
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div>
                <label style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', display: 'block', marginBottom: 4, letterSpacing: '0.04em' }}>
                  GITHUB URL
                </label>
                <input
                  autoFocus
                  placeholder="https://github.com/user/repo"
                  value={repoUrl}
                  onChange={e => setRepoUrl(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') handleAddRepo(); if (e.key === 'Escape') { setAddOpen(false); setRepoUrl(''); setAuthToken(''); } }}
                  style={{
                    width: '100%', padding: '9px 12px', borderRadius: 6,
                    background: '#111', border: '1px solid #2a2a2a', outline: 'none',
                    color: '#fff', fontSize: 13, fontFamily: 'inherit',
                    boxSizing: 'border-box',
                  }}
                />
              </div>
              <div>
                <label style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', display: 'block', marginBottom: 4, letterSpacing: '0.04em' }}>
                  AUTH TOKEN <span style={{ color: 'rgba(255,255,255,0.2)' }}>(optional, for private repos)</span>
                </label>
                <input
                  type="password"
                  placeholder="ghp_..."
                  value={authToken}
                  onChange={e => setAuthToken(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') handleAddRepo(); if (e.key === 'Escape') { setAddOpen(false); setRepoUrl(''); setAuthToken(''); } }}
                  style={{
                    width: '100%', padding: '9px 12px', borderRadius: 6,
                    background: '#111', border: '1px solid #2a2a2a', outline: 'none',
                    color: '#fff', fontSize: 13, fontFamily: 'inherit',
                    boxSizing: 'border-box',
                  }}
                />
              </div>
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button
                onClick={() => { setAddOpen(false); setRepoUrl(''); setAuthToken(''); }}
                disabled={adding}
                style={{
                  padding: '7px 14px', borderRadius: 6, border: '1px solid #2a2a2a',
                  background: 'transparent', color: 'rgba(255,255,255,0.5)',
                  fontSize: 12, fontFamily: 'inherit', cursor: adding ? 'not-allowed' : 'pointer',
                  opacity: adding ? 0.5 : 1,
                }}
              >
                Cancel
              </button>
              <button
                onClick={handleAddRepo}
                disabled={adding || !repoUrl.trim()}
                style={{
                  padding: '7px 14px', borderRadius: 6, border: 'none',
                  background: !repoUrl.trim() || adding ? '#555' : '#fff',
                  color: !repoUrl.trim() || adding ? '#999' : '#000',
                  fontSize: 12, fontWeight: 600, fontFamily: 'inherit',
                  cursor: adding || !repoUrl.trim() ? 'not-allowed' : 'pointer',
                  transition: 'background 0.15s',
                }}
              >
                {adding ? 'Adding...' : 'Add'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function AddRepoCard({ view, onAdd }: { view: 'grid' | 'list'; onAdd: () => void }) {
  const [hov, setHov] = useState(false);
  return (
    <div onClick={onAdd} onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}
      style={{ height: view === 'grid' ? 172 : 64, borderRadius: 8, border: `1px dashed ${hov ? '#333' : '#1f1f1f'}`, background: hov ? '#0a0a0a' : 'transparent', display: 'flex', flexDirection: view === 'grid' ? 'column' : 'row', alignItems: 'center', justifyContent: 'center', gap: 8, cursor: 'pointer', transition: 'border-color 0.15s, background 0.15s' }}>
      <div style={{ width: 28, height: 28, borderRadius: '50%', background: hov ? '#1a1a1a' : 'transparent', border: `1px solid ${hov ? '#333' : '#222'}`, display: 'flex', alignItems: 'center', justifyContent: 'center', color: hov ? 'rgba(255,255,255,0.6)' : 'rgba(255,255,255,0.2)', fontSize: 18, fontWeight: 300, transition: 'all 0.15s' }}>+</div>
      <span style={{ fontSize: 12, color: hov ? 'rgba(255,255,255,0.5)' : 'rgba(255,255,255,0.2)', transition: 'color 0.15s' }}>Add repository</span>
    </div>
  );
}
