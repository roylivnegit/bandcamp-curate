import { useState } from 'react'
import { Link } from 'react-router-dom'

import { ApiError } from '../api/client'
import { AuthLayout } from './AuthLayout'
import { useAuth } from './context'

export function LoginPage() {
  const { login, authError } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (busy) return
    setBusy(true)
    setError('')
    try {
      await login(username, password)
      // No redirect needed: App swaps to the signed-in routes once `me` is set.
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 503
          ? "This server isn't set up for sign-in yet (no auth key configured)."
          : err instanceof Error
            ? err.message
            : 'Sign-in failed.',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthLayout
      title="Sign in"
      blurb="Your crates, your neighbours, your feed."
      footer={
        <>
          No account? <Link to="/signup">Sign up with an invite</Link>
        </>
      }
    >
      {authError && !error && (
        <p className="banner queued authnotice">
          {authError} Your sign-in wasn&rsquo;t lost — try again in a moment.
        </p>
      )}
      <form onSubmit={submit} noValidate>
        <div className="field">
          <label className="label" htmlFor="username">
            Username
          </label>
          <input
            id="username"
            className="input"
            autoComplete="username"
            autoFocus
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </div>
        <div className="field">
          <label className="label" htmlFor="password">
            Password
          </label>
          <input
            id="password"
            className="input"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        {error && (
        <p className="err" role="alert">
          {error}
        </p>
      )}
        <button
          type="submit"
          className="btn block authsubmit"
          disabled={busy || !username || !password}
        >
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </AuthLayout>
  )
}
