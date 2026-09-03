import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  getLastSeenGeneration,
  isUpdatedSinceLastVisit,
  setLastSeenGeneration,
} from './lastSeenGeneration'

describe('lastSeenGeneration storage', () => {
  beforeEach(() => localStorage.clear())

  it('has nothing stored for a scan that was never recorded', () => {
    expect(getLastSeenGeneration(1)).toBeNull()
  })

  it('round-trips a written generation', () => {
    setLastSeenGeneration(1, 3)
    expect(getLastSeenGeneration(1)).toBe(3)
  })

  it('keeps different scans on separate keys', () => {
    setLastSeenGeneration(1, 3)
    setLastSeenGeneration(2, 7)
    expect(getLastSeenGeneration(1)).toBe(3)
    expect(getLastSeenGeneration(2)).toBe(7)
  })

  it('falls back to null on a corrupted stored value', () => {
    localStorage.setItem('crate-digger.lastSeenGeneration:1', 'not-a-number')
    expect(getLastSeenGeneration(1)).toBeNull()
  })

  describe('when localStorage throws (private mode / storage disabled)', () => {
    afterEach(() => vi.restoreAllMocks())

    it('getLastSeenGeneration falls back to null instead of throwing', () => {
      vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
        throw new Error('storage disabled')
      })
      expect(getLastSeenGeneration(1)).toBeNull()
    })

    it('setLastSeenGeneration is a silent no-op instead of throwing', () => {
      vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
        throw new Error('storage disabled')
      })
      expect(() => setLastSeenGeneration(1, 3)).not.toThrow()
    })
  })
})

describe('isUpdatedSinceLastVisit', () => {
  it('is false on a scan with no recorded prior visit', () => {
    expect(isUpdatedSinceLastVisit(5, null)).toBe(false)
  })

  it('is false when nothing has changed since the last visit', () => {
    expect(isUpdatedSinceLastVisit(5, 5)).toBe(false)
  })

  it('is false when the current generation is missing', () => {
    expect(isUpdatedSinceLastVisit(null, 5)).toBe(false)
  })

  it('is true when the generation has moved on since the last visit', () => {
    expect(isUpdatedSinceLastVisit(6, 5)).toBe(true)
  })
})
