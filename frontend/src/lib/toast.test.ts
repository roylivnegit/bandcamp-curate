import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { TOAST_DURATION_MS, TOAST_STACK_CAP } from '../config'
import { pauseToast, resetToastsForTests, resumeToast, showToast, useToasts } from './toast'

describe('toast stack cap', () => {
  beforeEach(() => {
    resetToastsForTests()
    vi.useFakeTimers({ shouldAdvanceTime: true })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('never grows past the cap, evicting the oldest toast first', () => {
    const { result } = renderHook(() => useToasts())

    for (let i = 0; i < 6; i++) {
      act(() => showToast(`toast ${i}`))
    }

    expect(result.current).toHaveLength(TOAST_STACK_CAP)
    expect(result.current.map((t) => t.message)).toEqual(['toast 2', 'toast 3', 'toast 4', 'toast 5'])
  })

  it('never evicts a toast with a pending action', () => {
    const { result } = renderHook(() => useToasts())

    act(() =>
      showToast('Could not save that like.', 'alert', TOAST_DURATION_MS, {
        label: 'Retry',
        onClick: () => {},
      }),
    )
    for (let i = 0; i < 4; i++) {
      act(() => showToast(`plain ${i}`))
    }

    expect(result.current).toHaveLength(TOAST_STACK_CAP)
    expect(result.current[0].message).toBe('Could not save that like.')
    expect(result.current.slice(1).map((t) => t.message)).toEqual(['plain 1', 'plain 2', 'plain 3'])
  })
})

describe('toast pause/resume', () => {
  beforeEach(() => {
    resetToastsForTests()
    vi.useFakeTimers({ shouldAdvanceTime: true })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('freezes the dismiss countdown while paused, then resumes for exactly the time left', async () => {
    const { result } = renderHook(() => useToasts())
    act(() => showToast('Undo?'))
    const id = result.current[0].id

    // 3000 of the 4000ms duration elapse before the reader hovers it.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000)
    })
    expect(result.current).toHaveLength(1)

    act(() => pauseToast(id))
    // Time the reader spends with the pointer on it doesn't count down —
    // far past the original duration, it's still there.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000)
    })
    expect(result.current).toHaveLength(1)

    act(() => resumeToast(id))
    // Only 1000ms was left when it paused.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(999)
    })
    expect(result.current).toHaveLength(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1)
    })
    expect(result.current).toHaveLength(0)
  })

  it('only resumes once every pauseToast call has a matching resumeToast (hover + focus overlap)', async () => {
    const { result } = renderHook(() => useToasts())
    act(() => showToast('Undo?'))
    const id = result.current[0].id

    act(() => pauseToast(id)) // hover
    act(() => pauseToast(id)) // focus, while still hovered
    act(() => resumeToast(id)) // pointer leaves, focus remains

    await act(async () => {
      await vi.advanceTimersByTimeAsync(TOAST_DURATION_MS + 1000)
    })
    expect(result.current).toHaveLength(1)

    act(() => resumeToast(id)) // focus leaves too
    await act(async () => {
      await vi.advanceTimersByTimeAsync(TOAST_DURATION_MS)
    })
    expect(result.current).toHaveLength(0)
  })

  it('pauseToast/resumeToast on an id that no longer exists is a harmless no-op', () => {
    expect(() => pauseToast(999)).not.toThrow()
    expect(() => resumeToast(999)).not.toThrow()
  })
})
