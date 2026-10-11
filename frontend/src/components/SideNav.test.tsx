import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { fakeMe, mockFetch, renderApp } from '../test/renderApp'

const signedIn = () => localStorage.setItem('crate-digger.token', 'tok')

const routes: Array<[string, unknown, number?]> = [
  ['/api/auth/me', fakeMe],
  ['/api/scans', []],
]

beforeEach(() => {
  localStorage.clear()
  signedIn()
})

afterEach(() => vi.unstubAllGlobals())

describe('SideNav', () => {
  it('is closed until asked for', async () => {
    mockFetch(routes)
    renderApp('/scans')
    await screen.findByRole('heading', { name: 'Your scans' })

    expect(screen.getByRole('button', { name: 'Menu' })).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument()
  })

  it('opens on hover and closes again when the pointer leaves', async () => {
    mockFetch(routes)
    renderApp('/scans')
    await screen.findByRole('heading', { name: 'Your scans' })
    const toggle = screen.getByRole('button', { name: 'Menu' })

    await userEvent.hover(toggle)
    expect(await screen.findByRole('navigation', { name: 'Main' })).toBeInTheDocument()

    // Leaving without clicking puts it back — a glance should not stick.
    // Closing is deliberately delayed (CLOSE_GRACE_MS) so the pointer can
    // cross the gap between the trigger and the panel.
    await userEvent.unhover(toggle)
    await waitFor(() =>
      expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument(),
    )
  })

  it('a second click closes it, even with the pointer still on the button', async () => {
    mockFetch(routes)
    renderApp('/scans')
    await screen.findByRole('heading', { name: 'Your scans' })
    const toggle = screen.getByRole('button', { name: 'Menu' })

    await userEvent.click(toggle)
    expect(screen.getByRole('navigation', { name: 'Main' })).toBeInTheDocument()

    // Clicking requires hovering, and hovering opens — so without suppressing
    // the hover the panel would reopen the instant the click dismissed it.
    await userEvent.click(toggle)
    expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument()
    expect(toggle).toHaveAttribute('aria-expanded', 'false')

    // And it must STAY closed as the pointer leaves. Clearing the hover
    // suppression eagerly here, while the transient clear was only scheduled,
    // flipped it back open for a render — the panel flickered back and
    // replayed its entry animation.
    await userEvent.unhover(toggle)
    expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument()
    await new Promise((r) => setTimeout(r, 350))
    expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument()
  })

  it('a click pins it open, so the pointer can leave', async () => {
    mockFetch(routes)
    renderApp('/scans')
    await screen.findByRole('heading', { name: 'Your scans' })
    const toggle = screen.getByRole('button', { name: 'Menu' })

    await userEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')

    await userEvent.unhover(toggle)
    await new Promise((r) => setTimeout(r, 350))
    expect(screen.getByRole('navigation', { name: 'Main' })).toBeInTheDocument()
  })

  it('Escape closes a pinned panel', async () => {
    mockFetch(routes)
    renderApp('/scans')
    await screen.findByRole('heading', { name: 'Your scans' })

    await userEvent.click(screen.getByRole('button', { name: 'Menu' }))
    expect(screen.getByRole('navigation', { name: 'Main' })).toBeInTheDocument()

    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument()
  })

  it('marks the route you are on', async () => {
    mockFetch([...routes, ['/api/collection', { owned: [], wishlist: [], liked: [], truncated: false }]])
    renderApp('/collection')
    await screen.findByRole('heading', { name: 'Collection', level: 1 })

    await userEvent.click(screen.getByRole('button', { name: 'Menu' }))

    // The old dropdown gave no indication of where you were.
    const current = screen.getByRole('link', { name: /Collection/ })
    expect(current).toHaveAttribute('aria-current', 'page')
    // `on`, not `active` — feed.css owns a global `.active`.
    expect(current.className).toContain('on')
    expect(screen.getByRole('link', { name: /Scans/ })).not.toHaveAttribute('aria-current')
  })

  it('navigates and closes itself', async () => {
    mockFetch([...routes, ['/api/collection', { owned: [], wishlist: [], liked: [], truncated: false }]])
    renderApp('/scans')
    await screen.findByRole('heading', { name: 'Your scans' })

    await userEvent.click(screen.getByRole('button', { name: 'Menu' }))
    await userEvent.click(screen.getByRole('link', { name: /Collection/ }))

    expect(await screen.findByRole('heading', { name: 'Collection', level: 1 })).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument()
  })
})
