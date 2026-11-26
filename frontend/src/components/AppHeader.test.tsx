import { screen } from '@testing-library/react'
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

describe('AppHeader search button', () => {
  it('is named for what it searches, not for its glyph', async () => {
    mockFetch(routes)
    renderApp('/scans')
    await screen.findByRole('heading', { name: 'Your scans' })

    expect(
      screen.getByRole('button', { name: 'Search scans, records and artists' }),
    ).toBeInTheDocument()
  })

  it('opens the palette on click — the only way in on a device with no Ctrl key', async () => {
    mockFetch(routes)
    renderApp('/scans')
    await screen.findByRole('heading', { name: 'Your scans' })

    await userEvent.click(screen.getByRole('button', { name: /^Search/ }))

    expect(await screen.findByRole('dialog', { name: 'Command palette' })).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Search' })).toHaveFocus()
  })

  it('a second click re-opens it rather than toggling it shut behind your back', async () => {
    /* Ctrl+K toggles, because the same keypress is the obvious way back out.
     * A button is not: the palette covers it, so a click can only ever mean
     * "open" — a toggle here would make a visible control do nothing. */
    mockFetch(routes)
    renderApp('/scans')
    await screen.findByRole('heading', { name: 'Your scans' })
    const button = screen.getByRole('button', { name: /^Search/ })

    await userEvent.click(button)
    await screen.findByRole('dialog', { name: 'Command palette' })
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    await userEvent.click(button)
    expect(await screen.findByRole('dialog', { name: 'Command palette' })).toBeInTheDocument()
  })
})
