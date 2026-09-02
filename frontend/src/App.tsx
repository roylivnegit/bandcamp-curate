import { Suspense, lazy } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

import { useAuth } from './auth/context'
import { AppHeader } from './components/AppHeader'
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

  // Don't flash the login screen while a stored token is still being resolved.
  if (loading) {
    return <div className="wrap">{Loading}</div>
  }

  if (!me) {
    return (
      <Suspense fallback={<div className="wrap">{Loading}</div>}>
        <Routes>
          <Route path="/signup" element={<SignupPage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </Suspense>
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
      <main id="main-content">
        <Suspense fallback={<div className="wrap">{Loading}</div>}>
          <Routes>
            <Route path="/scans" element={<ScanListPage />} />
            <Route path="/scans/:scanId" element={<ScanFeedPage />} />
            {/* Signed in: /login and /signup have nothing left to offer. */}
            <Route path="*" element={<Navigate to="/scans" replace />} />
          </Routes>
        </Suspense>
      </main>
    </>
  )
}
