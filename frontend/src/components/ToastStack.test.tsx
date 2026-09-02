import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { TOAST_DURATION_MS } from '../config'
import { resetToastsForTests, showToast } from '../lib/toast'
import { ToastStack } from './ToastStack'

describe('ToastStack', () => {
  beforeEach(() => {
    resetToastsForTests()
  })

  afterEach(async () => {
    // Drain whatever's left in the module-scope queue so one test's toasts
    // never bleed into the next.
    if (vi.isFakeTimers()) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(TOAST_DURATION_MS)
      })
    }
    vi.useRealTimers()
  })

  it('renders nothing when the queue is empty', () => {
    render(<ToastStack />)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('shows a status toast, then auto-dismisses it after the configured duration', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    render(<ToastStack />)

    act(() => showToast('Link copied'))
    expect(screen.getByRole('status')).toHaveTextContent('Link copied')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(TOAST_DURATION_MS)
    })
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('renders an alert-variant toast with role="alert" instead of "status"', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    render(<ToastStack />)

    act(() => showToast('Something failed', 'alert'))
    expect(screen.getByRole('alert')).toHaveTextContent('Something failed')
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('stacks multiple toasts, each dismissible independently', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    render(<ToastStack />)

    act(() => showToast('First'))
    act(() => showToast('Second'))
    expect(screen.getAllByRole('status')).toHaveLength(2)

    const [firstDismiss] = screen.getAllByRole('button', { name: 'Dismiss notification' })
    act(() => firstDismiss.click())

    const remaining = screen.getAllByRole('status')
    expect(remaining).toHaveLength(1)
    expect(remaining[0]).toHaveTextContent('Second')
  })
})
