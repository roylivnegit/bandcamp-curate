import { Navigate, Route, Routes } from 'react-router-dom'

import { useAuth } from './auth/context'
import { LoginPage } from './auth/LoginPage'
import { SignupPage } from './auth/SignupPage'
import { AppHeader } from './components/AppHeader'
import { ScanFeedPage } from './features/feed/ScanFeedPage'
import { ScanListPage } from './features/scans/ScanListPage'

export default function App() {
  const { me, loading } = useAuth()

  // Don't flash the login screen while a stored token is still being resolved.
  if (loading) {
    return (
      <div className="wrap">
        <p className="empty">Loading…</p>
      </div>
    )
  }

  if (!me) {
    return (
      <Routes>
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    )
  }

  return (
    <>
      <AppHeader />
      <Routes>
        <Route path="/scans" element={<ScanListPage />} />
        <Route path="/scans/:scanId" element={<ScanFeedPage />} />
        {/* Signed in: /login and /signup have nothing left to offer. */}
        <Route path="*" element={<Navigate to="/scans" replace />} />
      </Routes>
    </>
  )
}
