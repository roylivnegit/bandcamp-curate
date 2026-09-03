import { act, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { SCAN_POLL_MS } from '../config'
import { resetToastsForTests } from '../lib/toast'
import { fakeMe, fakeScan, mockFetch, renderApp } from '../test/renderApp'

describe('auth flow', () => {
  beforeEach(() => {
    localStorage.clear()
    resetToastsForTests()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('shows the login form when there is no token', async () => {
    mockFetch([])
    renderApp('/scans')
    // Any route redirects to login while signed out.
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
  })

  it('signs in, stores the token, and lands on the scan list', async () => {
    mockFetch([
      ['/api/auth/login', { access_token: 'tok-123', token_type: 'bearer' }],
      ['/api/auth/me', fakeMe],
      ['/api/scans', []],
    ])
    renderApp('/login')
    const user = userEvent.setup()

    await user.type(screen.getByLabelText('Username'), 'digger')
    await user.type(screen.getByLabelText('Password'), 'hunter22')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByText('Your scans')).toBeInTheDocument()
    // The token must persist, or a reload would bounce the user back to login.
    expect(localStorage.getItem('crate-digger.token')).toBe('tok-123')
  })

  it("surfaces the API's message on bad credentials and stays put", async () => {
    mockFetch([['/api/auth/login', { detail: 'invalid username or password' }, 401]])
    renderApp('/login')
    const user = userEvent.setup()

    await user.type(screen.getByLabelText('Username'), 'digger')
    await user.type(screen.getByLabelText('Password'), 'wrong')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    // A 401 on login is a wrong password, not an expired session — the login
    // screen must not be replaced by a session-expired message.
    expect(await screen.findByText(/invalid username or password/i)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    // role="alert" — a sighted user sees the red text appear; a screen-reader
    // user gets nothing unless it's announced.
    expect(await screen.findByRole('alert')).toHaveTextContent(/invalid username or password/i)
  })

  it('reports a rejected invite code on signup', async () => {
    mockFetch([['/api/auth/signup', { detail: 'invalid invite code' }, 403]])
    renderApp('/signup')
    const user = userEvent.setup()

    // findBy, not getBy: routes are lazy-loaded, so the form arrives a tick
    // after the first paint (behind App's Suspense fallback).
    await user.type(await screen.findByLabelText('Invite code'), 'nope')
    await user.type(screen.getByLabelText('Username'), 'newbie')
    await user.type(screen.getByLabelText('Password'), 'pw12345')
    await user.type(screen.getByLabelText('Your Bandcamp collection'), 'https://bandcamp.com/n')
    await user.click(screen.getByRole('button', { name: 'Create account' }))

    expect(await screen.findByText(/invalid invite code/i)).toBeInTheDocument()
  })

  it('flags a malformed Bandcamp collection URL before any network call', async () => {
    const fetchMock = mockFetch([])
    renderApp('/signup')
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText('Invite code'), 'ok')
    await user.type(screen.getByLabelText('Username'), 'newbie')
    await user.type(screen.getByLabelText('Password'), 'pw12345')
    const fanUrlInput = screen.getByLabelText('Your Bandcamp collection')
    await user.type(fanUrlInput, 'not a url')

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/doesn.t look like a Bandcamp collection URL/i)
    expect(fanUrlInput).toHaveAttribute('aria-invalid', 'true')
    expect(fanUrlInput.getAttribute('aria-describedby')).toBe(alert.id)
    expect(screen.getByRole('button', { name: 'Create account' })).toBeDisabled()

    // Never called: submit must be gated on the client, not left to the server 400.
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('accepts a well-formed Bandcamp collection URL with no error shown', async () => {
    mockFetch([['/api/auth/signup', { access_token: 'tok-123', token_type: 'bearer' }]])
    renderApp('/signup')
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText('Invite code'), 'ok')
    await user.type(screen.getByLabelText('Username'), 'newbie')
    await user.type(screen.getByLabelText('Password'), 'pw12345')
    const fanUrlInput = screen.getByLabelText('Your Bandcamp collection')
    await user.type(fanUrlInput, 'https://bandcamp.com/newbie')

    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(fanUrlInput).not.toHaveAttribute('aria-invalid')
    expect(screen.getByRole('button', { name: 'Create account' })).toBeEnabled()
  })

  it('drops a stale stored token instead of hanging on a spinner', async () => {
    localStorage.setItem('crate-digger.token', 'expired')
    mockFetch([['/api/auth/me', { detail: 'Not authenticated' }, 401]])
    renderApp('/scans')

    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    await waitFor(() => expect(localStorage.getItem('crate-digger.token')).toBeNull())
  })

  it('keeps the token when the server is unreachable, and says so', async () => {
    // Regression: any failed /me used to clear the token. The API cold-starts
    // for ~30-60s on the free tier, so "unreachable" is routine — throwing the
    // session away there signs people out for no reason.
    localStorage.setItem('crate-digger.token', 'still-good')
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch')
      }),
    )
    renderApp('/scans')

    expect(await screen.findByText(/reach the server/i)).toBeInTheDocument()
    expect(screen.getByText(/wasn’t lost/i)).toBeInTheDocument()
    expect(localStorage.getItem('crate-digger.token')).toBe('still-good')
  })

  it('keeps the token when /me returns a 5xx', async () => {
    localStorage.setItem('crate-digger.token', 'still-good')
    mockFetch([['/api/auth/me', { detail: 'boom' }, 500]])
    renderApp('/scans')

    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(localStorage.getItem('crate-digger.token')).toBe('still-good')
  })

  it('toasts when a 401 mid-session drops the user back to login', async () => {
    // Distinct from "drops a stale stored token instead of hanging on a
    // spinner" above: that 401 happens before there was ever a real session
    // (`me` is still null), so it must NOT toast. This one signs in first,
    // then a later poll's 401 ends a session that was actually live.
    // Uses ScanFeedPage's poll (a single `/api/scans/1` request) rather than
    // ScanListPage's (which also fires a parallel `refresh()` `/api/auth/me`
    // call each tick) so there's no race between two concurrent responses
    // over which `setMe` call lands last.
    localStorage.setItem('crate-digger.token', 'tok-123')
    const json = (body: unknown, status = 200) =>
      new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
    let scanCall = 0
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: string | URL | Request) => {
        const url = String(input)
        if (url.includes('/api/auth/me')) return json(fakeMe)
        if (url.includes('/api/scans/1')) {
          scanCall += 1
          // First call (initial load) succeeds with a running scan, so the
          // page polls again; the second call (the poll) is the mid-session 401.
          if (scanCall === 1) return json({ ...fakeScan, status: 'running', seeds: [] })
          return json({ detail: 'Not authenticated' }, 401)
        }
        if (url.includes('/api/likes') || url.includes('/api/blacklist')) return json([])
        if (url.includes('/api/facets')) return json({ tags: [], labels: [], seed_tags: [] })
        if (url.includes('/api/recommendations/count')) return json({ count: 0 })
        if (url.includes('/api/recommendations')) return json([])
        throw new Error(`no mock route for ${url}`)
      }),
    )
    vi.useFakeTimers({ shouldAdvanceTime: true })

    renderApp('/scans/1')
    expect(await screen.findByRole('heading', { name: /my collection/i })).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(SCAN_POLL_MS)
    })

    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(await screen.findByRole('alert')).toHaveTextContent(/session expired/i)
  })

  it('does not toast on an explicit logout', async () => {
    mockFetch([
      ['/api/auth/login', { access_token: 'tok-123', token_type: 'bearer' }],
      ['/api/auth/me', fakeMe],
      ['/api/scans', []],
    ])
    renderApp('/login')
    const user = userEvent.setup()

    await user.type(screen.getByLabelText('Username'), 'digger')
    await user.type(screen.getByLabelText('Password'), 'hunter22')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Your scans')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Sign out' }))

    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
