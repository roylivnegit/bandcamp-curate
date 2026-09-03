import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { TOAST_DURATION_MS, TOAST_STACK_CAP } from '../config'
import { resetToastsForTests, showToast, useToasts } from './toast'

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
