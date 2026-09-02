import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { VISITED_CAP } from '../config'
import { isVisited, markVisited } from './visited'

describe('visited', () => {
  beforeEach(() => localStorage.clear())

  it('is not visited until marked', () => {
    expect(isVisited('album:1')).toBe(false)
    markVisited('album:1')
    expect(isVisited('album:1')).toBe(true)
  })

  it('leaves unrelated keys unaffected', () => {
    markVisited('album:1')
    expect(isVisited('album:2')).toBe(false)
  })

  it('marking the same key twice does not duplicate it', () => {
    markVisited('album:1')
    markVisited('album:1')
    const stored = JSON.parse(localStorage.getItem('crate-digger.visited') ?? '[]')
    expect(stored).toEqual(['album:1'])
  })

  it('evicts the oldest entry once the cap is exceeded', () => {
    for (let i = 0; i < VISITED_CAP; i++) markVisited(`album:${i}`)
    expect(isVisited('album:0')).toBe(true)

    markVisited('album:overflow')

    expect(isVisited('album:0')).toBe(false)
    expect(isVisited('album:overflow')).toBe(true)
    const stored = JSON.parse(localStorage.getItem('crate-digger.visited') ?? '[]')
    expect(stored).toHaveLength(VISITED_CAP)
  })

  it('falls back to "not visited" on a corrupted stored value', () => {
    localStorage.setItem('crate-digger.visited', '{"not":"an array"}')
    expect(isVisited('album:1')).toBe(false)
  })

  describe('when localStorage throws (private mode / storage disabled)', () => {
    afterEach(() => vi.restoreAllMocks())

    it('isVisited falls back to false instead of throwing', () => {
      vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
        throw new Error('storage disabled')
      })
      expect(isVisited('album:1')).toBe(false)
    })

    it('markVisited is a silent no-op instead of throwing', () => {
      vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
        throw new Error('storage disabled')
      })
      expect(() => markVisited('album:1')).not.toThrow()
    })
  })
})
