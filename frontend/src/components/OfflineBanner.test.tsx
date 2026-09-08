import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { resetToastsForTests, useToasts } from '../lib/toast'
import { OfflineBanner } from './OfflineBanner'

function setNavigatorOnLine(value: boolean) {
  Object.defineProperty(window.navigator, 'onLine', {
    configurable: true,
    value,
  })
}

function ToastMessages() {
  return <>{useToasts().map((t) => t.message)}</>
}

describe('OfflineBanner', () => {
  beforeEach(() => resetToastsForTests())
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

  it('shows a "Back online" toast after a real offline→online transition', () => {
    render(
      <>
        <OfflineBanner />
        <ToastMessages />
      </>,
    )

    act(() => window.dispatchEvent(new Event('offline')))
    expect(screen.queryByText('Back online.')).not.toBeInTheDocument()

    act(() => window.dispatchEvent(new Event('online')))
    expect(screen.getByText('Back online.')).toBeInTheDocument()
  })

  it('does not toast on initial mount, even when starting online', () => {
    render(
      <>
        <OfflineBanner />
        <ToastMessages />
      </>,
    )
    expect(screen.queryByText('Back online.')).not.toBeInTheDocument()
  })

  it('does not toast on initial mount when starting offline', () => {
    setNavigatorOnLine(false)
    render(
      <>
        <OfflineBanner />
        <ToastMessages />
      </>,
    )
    expect(screen.queryByText('Back online.')).not.toBeInTheDocument()
  })
})
