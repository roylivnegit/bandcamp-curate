import { afterEach, describe, expect, it, vi } from 'vitest'

import { REQUEST_TIMEOUT_MS } from '../config'
import { api, filterQuery } from './client'

/** The filter contract is the fiddliest part of the API surface: the backend
 *  reads repeated keys (tag=a&tag=b), and include/exclude are *different* keys
 *  rather than a value. Getting this wrong silently returns the wrong feed. */
describe('filterQuery', () => {
  it('sends repeated keys rather than a joined list', () => {
    const q = filterQuery({ tags: { rock: 'by', jazz: 'by' } })
    expect(q.getAll('tag')).toEqual(['rock', 'jazz'])
    expect(q.toString()).not.toContain('rock%2Cjazz')
  })

  it('routes include vs exclude to their own parameters', () => {
    const q = filterQuery({ tags: { rock: 'by', metal: 'out' } })
    expect(q.getAll('tag')).toEqual(['rock'])
    expect(q.getAll('exclude_tag')).toEqual(['metal'])
  })

  it('keeps substring filters on the *_contains parameters', () => {
    const q = filterQuery({ tagContains: { psy: 'by', live: 'out' } })
    expect(q.getAll('tag_contains')).toEqual(['psy'])
    expect(q.getAll('exclude_tag_contains')).toEqual(['live'])
    expect(q.getAll('tag')).toEqual([])
  })

  it('includes scan and label ids, and omits empty filters entirely', () => {
    const q = filterQuery({ scanId: 7, labelId: 42, itemType: 'album' })
    expect(q.get('scan_id')).toBe('7')
    expect(q.get('label_id')).toBe('42')
    expect(q.get('item_type')).toBe('album')

    const empty = filterQuery({ scanId: null, itemType: '', labelId: null })
    expect(empty.toString()).toBe('')
  })

  it('treats scan 0 as a real id, not as absent', () => {
    // Guards the `!= null` check against a truthiness regression.
    expect(filterQuery({ scanId: 0 }).get('scan_id')).toBe('0')
  })
})

describe('request timeout', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('aborts a hung request and throws a friendly ApiError once REQUEST_TIMEOUT_MS elapses', async () => {
    vi.useFakeTimers()
    // A real hung connection never rejects on its own — it only rejects once
    // something aborts it. This mock mirrors that: it listens for the signal
    // client.ts passes to fetch() and rejects only when that fires, so the
    // test actually exercises the abort wiring rather than a bare unresolved
    // promise (which would just hang forever under fake timers).
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_input: string | URL | Request, init?: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            init?.signal?.addEventListener('abort', () => {
              reject(new DOMException('The user aborted a request.', 'AbortError'))
            })
          }),
      ),
    )

    const pending = api.listScans()
    const assertion = expect(pending).rejects.toMatchObject({
      message: 'The request timed out. Please try again.',
    })

    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS)
    await assertion
  })

  it('does not time out a request that resolves before REQUEST_TIMEOUT_MS', async () => {
    vi.useFakeTimers()
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(JSON.stringify([]), { status: 200, headers: { 'Content-Type': 'application/json' } }),
      ),
    )

    const pending = api.listScans()
    await vi.advanceTimersByTimeAsync(0)

    await expect(pending).resolves.toEqual([])
  })
})
