import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { getDensity, setDensity } from './density'

describe('density', () => {
  beforeEach(() => localStorage.clear())

  it('defaults to comfortable when nothing is stored', () => {
    expect(getDensity()).toBe('comfortable')
  })

  it('round-trips a written value', () => {
    setDensity('compact')
    expect(getDensity()).toBe('compact')
    expect(localStorage.getItem('crate-digger.density')).toBe('compact')
  })

  it('falls back to comfortable for a corrupted stored value', () => {
    localStorage.setItem('crate-digger.density', 'huge')
    expect(getDensity()).toBe('comfortable')
  })

  describe('when localStorage throws (private mode / storage disabled)', () => {
    afterEach(() => vi.restoreAllMocks())

    it('getDensity falls back to the default instead of throwing', () => {
      vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
        throw new Error('storage disabled')
      })
      expect(getDensity()).toBe('comfortable')
    })

    it('setDensity is a silent no-op instead of throwing', () => {
      vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
        throw new Error('storage disabled')
      })
      expect(() => setDensity('compact')).not.toThrow()
    })
  })
})
