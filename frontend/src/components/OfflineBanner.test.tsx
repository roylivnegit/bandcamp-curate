import { act, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { OfflineBanner } from './OfflineBanner'

function setNavigatorOnLine(value: boolean) {
  Object.defineProperty(window.navigator, 'onLine', {
    configurable: true,
    value,
  })
}

describe('OfflineBanner', () => {
  afterEach(() => setNavigatorOnLine(true))

  it('renders nothing while online', () => {
    render(<OfflineBanner />)
    expect(screen.queryByText(/you’re offline/i)).not.toBeInTheDocument()
  })

  it('appears on an "offline" event and disappears again on "online"', () => {
    render(<OfflineBanner />)

    act(() => window.dispatchEvent(new Event('offline')))
    expect(screen.getByRole('status')).toHaveTextContent(/you’re offline/i)

    act(() => window.dispatchEvent(new Event('online')))
    expect(screen.queryByText(/you’re offline/i)).not.toBeInTheDocument()
  })

  it('starts visible when the page mounts already offline', () => {
    setNavigatorOnLine(false)
    render(<OfflineBanner />)
    expect(screen.getByRole('status')).toHaveTextContent(/you’re offline/i)
  })
})
