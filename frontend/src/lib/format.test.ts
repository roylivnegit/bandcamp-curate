import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { expiresLabel, isDuplicateScanName, isValidFanUrl, normalizeSeedUrl } from './format'

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

describe('normalizeSeedUrl', () => {
  it('treats a trailing slash as equivalent to none', () => {
    expect(normalizeSeedUrl('https://a.bandcamp.com/album/x/')).toBe(
      normalizeSeedUrl('https://a.bandcamp.com/album/x'),
    )
  })

  it('is case-insensitive on the host only, not the path', () => {
    expect(normalizeSeedUrl('https://A.BandCamp.com/album/X')).toBe(
      normalizeSeedUrl('https://a.bandcamp.com/album/X'),
    )
    // the path's case is preserved, not lowercased, since a slug could
    // plausibly be case-sensitive server-side
    expect(normalizeSeedUrl('https://a.bandcamp.com/album/X')).not.toBe(
      normalizeSeedUrl('https://a.bandcamp.com/album/x'),
    )
  })

  it('leaves two genuinely different URLs distinct', () => {
    expect(normalizeSeedUrl('https://a.bandcamp.com/album/x')).not.toBe(
      normalizeSeedUrl('https://a.bandcamp.com/album/y'),
    )
  })

  it('falls back to the trimmed raw string for something that does not parse as a URL', () => {
    expect(normalizeSeedUrl('  not a url  ')).toBe('not a url')
  })
})

describe('isDuplicateScanName', () => {
  it('matches case-insensitively', () => {
    expect(isDuplicateScanName('deep HOUSE', ['Deep house'])).toBe(true)
  })

  it('matches ignoring leading/trailing whitespace on both sides', () => {
    expect(isDuplicateScanName('  Deep house  ', ['Deep house '])).toBe(true)
  })

  it('returns false for a name not in the list', () => {
    expect(isDuplicateScanName('Ambient dig', ['Deep house'])).toBe(false)
  })

  it('returns false for an empty list', () => {
    expect(isDuplicateScanName('Deep house', [])).toBe(false)
  })

  it('returns false for a blank name even if the list contains a blank', () => {
    expect(isDuplicateScanName('   ', [''])).toBe(false)
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

  it('rolls over to the next unit instead of rounding onto its own bucket boundary', () => {
    // 59m50s left rounds to "60m", which reads as a full hour under the wrong
    // unit; 23h45m rounds to "24h" the same way at the day boundary.
    expect(expiresLabel('2026-09-03T00:59:50Z')).toBe('expires in 1h')
    expect(expiresLabel('2026-09-03T23:45:00Z')).toBe('expires in 1d')
  })
})
