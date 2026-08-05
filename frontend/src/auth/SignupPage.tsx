import { useState } from 'react'
import { Link } from 'react-router-dom'

import { ApiError } from '../api/client'
import { AuthLayout } from './AuthLayout'
import { useAuth } from './context'

export function SignupPage() {
  const { signup } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [fanUrl, setFanUrl] = useState('')
  const [invite, setInvite] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const complete = username && password && fanUrl && invite

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (busy || !complete) return
    setBusy(true)
    setError('')
    try {
      await signup({
        username,
        password,
        bandcamp_fan_url: fanUrl.trim(),
        invite_code: invite,
      })
    } catch (err) {
      // The API's own messages are already user-facing (bad invite, name taken,
      // password too long) — only 503 needs translating out of server-speak.
      setError(
        err instanceof ApiError && err.status === 503
          ? "This server isn't accepting sign-ups yet (no auth key configured)."
          : err instanceof Error
            ? err.message
            : 'Sign-up failed.',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthLayout
      title="Create an account"
      blurb="Sign-up is invite-only — each new account queues a crawl of your Bandcamp collection."
      footer={
        <>
          Already have an account? <Link to="/login">Sign in</Link>
        </>
      }
    >
      <form onSubmit={submit} noValidate>
        <div className="field">
          <label className="label" htmlFor="su-invite">
            Invite code
          </label>
          <input
            id="su-invite"
            className="input"
            autoFocus
            value={invite}
            onChange={(e) => setInvite(e.target.value)}
          />
        </div>
        <div className="field">
          <label className="label" htmlFor="su-username">
            Username
          </label>
          <input
            id="su-username"
            className="input"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </div>
        <div className="field">
          <label className="label" htmlFor="su-password">
            Password
          </label>
          <input
            id="su-password"
            className="input"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <div className="field">
          <label className="label" htmlFor="su-fanurl">
            Your Bandcamp collection
          </label>
          <input
            id="su-fanurl"
            className="input"
            inputMode="url"
            placeholder="https://bandcamp.com/yourusername"
            value={fanUrl}
            onChange={(e) => setFanUrl(e.target.value)}
          />
          <p className="field-hint">
            We crawl this to learn your taste. Nothing is posted to your account.
          </p>
        </div>
        {error && (
        <p className="err" role="alert">
          {error}
        </p>
      )}
        <button type="submit" className="btn block authsubmit" disabled={busy || !complete}>
          {busy ? 'Creating…' : 'Create account'}
        </button>
      </form>
    </AuthLayout>
  )
}
