import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { expiresLabel, isValidFanUrl } from './format'

describe('isValidFanUrl', () => {
  it('accepts a plain bandcamp.com fan URL', () => {
    expect(isValidFanUrl('https://bandcamp.com/guron')).toBe(true)
  })

  it('accepts http, a trailing slash, and surrounding whitespace', () => {
    expect(isValidFanUrl('http://bandcamp.com/guron/')).toBe(true)
    expect(isValidFanUrl('  https://bandcamp.com/guron  ')).toBe(true)
  })

  it('accepts a query string tacked onto the handle (e.g. a copied share link)', () => {
    expect(isValidFanUrl('https://bandcamp.com/guron?from=nav')).toBe(true)
  })

  it('is case-insensitive on the host', () => {
    expect(isValidFanUrl('https://BandCamp.com/guron')).toBe(true)
  })

  it('rejects a non-URL string', () => {
    expect(isValidFanUrl('not a url')).toBe(false)
  })

  it('rejects an artist/label subdomain — that is a storefront, not a fan page', () => {
    expect(isValidFanUrl('https://someartist.bandcamp.com/album/x')).toBe(false)
  })

  it('rejects bandcamp.com with no handle', () => {
    expect(isValidFanUrl('https://bandcamp.com/')).toBe(false)
    expect(isValidFanUrl('https://bandcamp.com')).toBe(false)
  })

  it('rejects a non-bandcamp host', () => {
    expect(isValidFanUrl('https://example.com/guron')).toBe(false)
  })

  it('rejects an empty string', () => {
    expect(isValidFanUrl('')).toBe(false)
  })
})

describe('expiresLabel', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-03T00:00:00Z'))
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('returns empty for a permanent block (null)', () => {
    expect(expiresLabel(null)).toBe('')
  })

  it('returns empty for a lapsed expiry (already in the past)', () => {
    expect(expiresLabel('2026-09-02T00:00:00Z')).toBe('')
  })

  it('formats a same-day expiry in hours', () => {
    expect(expiresLabel('2026-09-03T05:00:00Z')).toBe('expires in 5h')
  })

  it('formats a sub-hour expiry in minutes, rounding up to at least 1m', () => {
    expect(expiresLabel('2026-09-03T00:00:10Z')).toBe('expires in 1m')
  })

  it('formats a multi-day expiry in days', () => {
    expect(expiresLabel('2026-09-06T00:00:00Z')).toBe('expires in 3d')
  })
})
