import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { SESSION_EXPIRY_WARNING_MS } from '../config'
import { resetToastsForTests, useToasts } from './toast'
import { SESSION_EXPIRING_MESSAGE, useSessionExpiryWarning } from './useSessionExpiryWarning'

function fakeJwt(expSeconds: number): string {
  const base64url = (obj: unknown) =>
    btoa(JSON.stringify(obj)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
  return `${base64url({ alg: 'HS256' })}.${base64url({ exp: expSeconds })}.sig`
}

describe('useSessionExpiryWarning', () => {
  beforeEach(() => {
    resetToastsForTests()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('fires the warning toast exactly once, SESSION_EXPIRY_WARNING_MS before the token expires', () => {
    const now = Date.now()
    const token = fakeJwt((now + 60 * 60 * 1000) / 1000) // expires in 1h
    const toasts = renderHook(() => useToasts())
    renderHook(() => useSessionExpiryWarning(token))

    expect(toasts.result.current).toHaveLength(0)

    act(() => {
      vi.advanceTimersByTime(60 * 60 * 1000 - SESSION_EXPIRY_WARNING_MS - 1)
    })
    expect(toasts.result.current).toHaveLength(0)

    act(() => {
      vi.advanceTimersByTime(1)
    })
    expect(toasts.result.current).toHaveLength(1)
    expect(toasts.result.current[0].message).toBe(SESSION_EXPIRING_MESSAGE)
    expect(toasts.result.current[0].variant).toBe('alert')
  })

  it('schedules nothing for a null token', () => {
    const setTimeoutSpy = vi.spyOn(window, 'setTimeout')
    renderHook(() => useSessionExpiryWarning(null))

    expect(setTimeoutSpy).not.toHaveBeenCalled()
  })

  it('schedules nothing for a token with no readable exp claim', () => {
    const setTimeoutSpy = vi.spyOn(window, 'setTimeout')
    renderHook(() => useSessionExpiryWarning('not-a-jwt'))

    expect(setTimeoutSpy).not.toHaveBeenCalled()
  })

  it('clears the timer on unmount, so a stale token never fires after the component is gone', () => {
    const clearTimeoutSpy = vi.spyOn(window, 'clearTimeout')
    const now = Date.now()
    const token = fakeJwt((now + 60 * 60 * 1000) / 1000)
    const { unmount } = renderHook(() => useSessionExpiryWarning(token))

    unmount()

    expect(clearTimeoutSpy).toHaveBeenCalled()
  })

  it('resets the timer when the token changes, rather than keeping the old one', () => {
    const now = Date.now()
    const shortLivedToken = fakeJwt((now + 6 * 60 * 1000) / 1000) // warns at t=60s
    const longLivedToken = fakeJwt((now + 60 * 60 * 1000) / 1000) // warns at t=55m
    const toasts = renderHook(() => useToasts())
    const { rerender } = renderHook(({ token }) => useSessionExpiryWarning(token), {
      initialProps: { token: shortLivedToken },
    })

    rerender({ token: longLivedToken })

    // The short-lived token's warning would have fired here if its timer
    // hadn't been cleared when the token changed.
    act(() => {
      vi.advanceTimersByTime(2 * 60 * 1000)
    })
    expect(toasts.result.current).toHaveLength(0)
  })
})
