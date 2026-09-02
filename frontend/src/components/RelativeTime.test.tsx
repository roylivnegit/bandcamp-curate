import { act, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { RELATIVE_TIME_REFRESH_MS } from '../config'
import { RelativeTime } from './RelativeTime'

describe('RelativeTime', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('re-renders on its own interval, with no prop change or remount', async () => {
    vi.useFakeTimers()
    const iso = new Date().toISOString()
    render(<RelativeTime iso={iso} />)

    expect(screen.getByText('just now')).toBeInTheDocument()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(61_000)
    })

    expect(screen.getByText('1m ago')).toBeInTheDocument()
  })

  it('does not start a timer for a null iso, and renders empty', () => {
    vi.useFakeTimers()
    const setIntervalSpy = vi.spyOn(window, 'setInterval')
    render(<RelativeTime iso={null} />)

    expect(screen.queryByText(/ago/)).not.toBeInTheDocument()
    expect(setIntervalSpy).not.toHaveBeenCalled()
  })

  it('clears its interval on unmount', () => {
    vi.useFakeTimers()
    const clearIntervalSpy = vi.spyOn(window, 'clearInterval')
    const { unmount } = render(<RelativeTime iso={new Date().toISOString()} />)

    unmount()

    expect(clearIntervalSpy).toHaveBeenCalled()
  })

  it('ticks every RELATIVE_TIME_REFRESH_MS, not on some other cadence', async () => {
    vi.useFakeTimers()
    const iso = new Date(Date.now() - 59_000).toISOString()
    render(<RelativeTime iso={iso} />)

    expect(screen.getByText('just now')).toBeInTheDocument()

    // One tick short of crossing the 60s "just now" -> "1m ago" boundary.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(RELATIVE_TIME_REFRESH_MS - 1)
    })
    expect(screen.getByText('just now')).toBeInTheDocument()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1)
    })
    expect(screen.getByText('1m ago')).toBeInTheDocument()
  })
})
