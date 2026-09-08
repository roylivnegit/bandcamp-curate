import { Suspense, lazy, useCallback, useState } from 'react'
import { Navigate, Route, Routes, useMatch, useNavigate } from 'react-router-dom'

import { api } from './api/client'
import type { Scan } from './api/types'
import { useAuth } from './auth/context'
import { AppHeader } from './components/AppHeader'
import { CommandPalette, type CommandAction } from './components/CommandPalette'
import { ErrorBoundary } from './components/ErrorBoundary'
import { OfflineBanner } from './components/OfflineBanner'
import { ShortcutsHelp } from './components/ShortcutsHelp'
import { ToastStack } from './components/ToastStack'

/* Split on the auth boundary. The two branches below never render together, so
 * neither should ship in the other's chunk: a signed-out visitor downloading the
 * feed page (and its CSS) is pure waste, and vice versa. The static imports these
 * replace put all four pages plus every stylesheet in one entry chunk. */
const LoginPage = lazy(() => import('./auth/LoginPage').then((m) => ({ default: m.LoginPage })))
const SignupPage = lazy(() => import('./auth/SignupPage').then((m) => ({ default: m.SignupPage })))
const ScanListPage = lazy(() =>
  import('./features/scans/ScanListPage').then((m) => ({ default: m.ScanListPage })),
)
const ScanFeedPage = lazy(() =>
  import('./features/feed/ScanFeedPage').then((m) => ({ default: m.ScanFeedPage })),
)

const Loading = <p className="empty">Loading…</p>

export default function App() {
  const { me, loading } = useAuth()
  const navigate = useNavigate()
  const [scans, setScans] = useState<Scan[]>([])
  // Only the feed page has cards/quick-filter/menus for the feed-only rows in
  // ShortcutsHelp's list to describe — everywhere else in the signed-in shell
  // gets the palette/panel-toggle rows only.
  const onFeedPage = useMatch('/scans/:scanId') !== null

  // The command palette only ever needs a fresh scan list while it's open —
  // refetching on every render (or on a poll) would be wasted work the rest
  // of the time. `[]` deps: this never depends on anything that changes.
  const loadScansForPalette = useCallback(() => {
    void api.listScans().then(setScans).catch(() => {})
  }, [])

  // Built fresh each render (cheap: at most a handful of scans), not memoized
  // — `run` closures capture `navigate`, which react-router already keeps
  // referentially stable, so there's no unstable-identity churn to guard
  // against here the way there is for the per-row feed-card callbacks.
  const paletteActions: CommandAction[] = [
    { id: 'nav-scans', label: 'Go to Scans', run: () => navigate('/scans') },
    ...scans.map((s) => ({
      id: `nav-scan-${s.id}`,
      label: s.name,
      hint: s.kind === 'collection' ? 'your collection' : 'scan',
      run: () => navigate(`/scans/${s.id}`),
    })),
  ]

  // Don't flash the login screen while a stored token is still being resolved.
  if (loading) {
    return <div className="wrap">{Loading}</div>
  }

  if (!me) {
    return (
      <>
        {/* A mid-session 401 lands here in the same commit it toasts from
         * (AuthContext) — this instance must exist to pick up that toast, not
         * just the signed-in shell's. */}
        <ToastStack />
        <OfflineBanner />
        <Suspense fallback={<div className="wrap">{Loading}</div>}>
          <Routes>
            <Route path="/signup" element={<SignupPage />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="*" element={<Navigate to="/login" replace />} />
          </Routes>
        </Suspense>
      </>
    )
  }

  return (
    <>
      {/* First focusable element in the signed-in shell: a keyboard/screen-reader
       * user landing on any page can skip the header instead of tabbing through
       * it every load. Targets the `<main>` below — the one shared landmark both
       * routed pages render into, so this lives here once rather than per page. */}
      <a className="sr-only" href="#main-content">
        Skip to content
      </a>
      <AppHeader />
      <ToastStack />
      <OfflineBanner />
      <CommandPalette actions={paletteActions} onOpen={loadScansForPalette} />
      <ShortcutsHelp feedShortcuts={onFeedPage} />
      <main id="main-content">
        <ErrorBoundary>
          <Suspense fallback={<div className="wrap">{Loading}</div>}>
            <Routes>
              <Route path="/scans" element={<ScanListPage />} />
              <Route path="/scans/:scanId" element={<ScanFeedPage />} />
              {/* Signed in: /login and /signup have nothing left to offer. */}
              <Route path="*" element={<Navigate to="/scans" replace />} />
            </Routes>
          </Suspense>
        </ErrorBoundary>
      </main>
    </>
  )
}
