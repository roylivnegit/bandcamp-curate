import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { fakeMe, mockFetch, renderApp } from '../test/renderApp'

describe('auth flow', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => vi.unstubAllGlobals())

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
  })

  it('reports a rejected invite code on signup', async () => {
    mockFetch([['/api/auth/signup', { detail: 'invalid invite code' }, 403]])
    renderApp('/signup')
    const user = userEvent.setup()

    await user.type(screen.getByLabelText('Invite code'), 'nope')
    await user.type(screen.getByLabelText('Username'), 'newbie')
    await user.type(screen.getByLabelText('Password'), 'pw12345')
    await user.type(screen.getByLabelText('Your Bandcamp collection'), 'https://bandcamp.com/n')
    await user.click(screen.getByRole('button', { name: 'Create account' }))

    expect(await screen.findByText(/invalid invite code/i)).toBeInTheDocument()
  })

  it('drops a stale stored token instead of hanging on a spinner', async () => {
    localStorage.setItem('crate-digger.token', 'expired')
    mockFetch([['/api/auth/me', { detail: 'Not authenticated' }, 401]])
    renderApp('/scans')

    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    await waitFor(() => expect(localStorage.getItem('crate-digger.token')).toBeNull())
  })
})
