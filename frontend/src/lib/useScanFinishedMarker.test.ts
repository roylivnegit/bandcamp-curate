import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { useScanFinishedMarker } from './useScanFinishedMarker'

function setHidden(hidden: boolean) {
  Object.defineProperty(document, 'hidden', { configurable: true, value: hidden })
}

describe('useScanFinishedMarker', () => {
  afterEach(() => {
    setHidden(false)
  })

  it('marks true on a running->done transition while the tab is hidden', () => {
    setHidden(true)
    const { result, rerender } = renderHook(({ status }) => useScanFinishedMarker(status), {
      initialProps: { status: 'running' as string | null },
    })
    expect(result.current).toBe(false)

    rerender({ status: 'done' })
    expect(result.current).toBe(true)
  })

  it('clears once the tab becomes visible again', () => {
    setHidden(true)
    const { result, rerender } = renderHook(({ status }) => useScanFinishedMarker(status), {
      initialProps: { status: 'running' as string | null },
    })
    rerender({ status: 'done' })
    expect(result.current).toBe(true)

    act(() => {
      setHidden(false)
      document.dispatchEvent(new Event('visibilitychange'))
    })
    expect(result.current).toBe(false)
  })

  it('does not mark a scan that was already done on mount', () => {
    setHidden(true)
    const { result } = renderHook(() => useScanFinishedMarker('done'))
    expect(result.current).toBe(false)
  })

  it('does not mark a running->done transition while the tab is visible', () => {
    setHidden(false)
    const { result, rerender } = renderHook(({ status }) => useScanFinishedMarker(status), {
      initialProps: { status: 'running' as string | null },
    })

    rerender({ status: 'done' })
    expect(result.current).toBe(false)
  })

  it('ignores a visibilitychange event while nothing is marked', () => {
    setHidden(true)
    const { result } = renderHook(() => useScanFinishedMarker('running'))

    act(() => {
      setHidden(false)
      document.dispatchEvent(new Event('visibilitychange'))
    })
    expect(result.current).toBe(false)
  })
})
