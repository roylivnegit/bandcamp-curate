import { describe, expect, it } from 'vitest'

import { isValidFanUrl } from './format'

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
