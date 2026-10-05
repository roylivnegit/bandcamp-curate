import { describe, expect, it } from 'vitest'

import type { CollectionItem } from '../api/types'
import { entryKey, matchesTerms, mergeCollection, normalize, searchTerms } from './collection'

function item(over: Partial<CollectionItem> = {}): CollectionItem {
  return {
    item_type: 'album',
    album_id: 1,
    track_id: null,
    title: 'A Title',
    band_name: 'A Band',
    url: null,
    art_id: null,
    art_url: null,
    ...over,
  }
}

const empty = { owned: [], wishlist: [], liked: [], truncated: false }

describe('entryKey', () => {
  it('keys albums and tracks in separate namespaces', () => {
    // Same numeric id, different kind of thing — these must not collide.
    expect(entryKey(item({ album_id: 7 }))).toBe('album:7')
    expect(entryKey(item({ item_type: 'track', album_id: null, track_id: 7 }))).toBe('track:7')
  })
})

describe('normalize / searchTerms', () => {
  it('strips accents and case so "bjork" matches "Björk"', () => {
    expect(normalize('Björk')).toBe('bjork')
    expect(normalize('Sigur Rós')).toBe('sigur ros')
    expect(normalize('MÚM')).toBe('mum')
  })

  it('splits a query into terms and ignores stray whitespace', () => {
    expect(searchTerms('  aphex   drukqs ')).toEqual(['aphex', 'drukqs'])
    expect(searchTerms('   ')).toEqual([])
  })
})

describe('matchesTerms', () => {
  const entry = mergeCollection({
    ...empty,
    owned: [item({ title: 'Drukqs', band_name: 'Aphex Twin' })],
  })[0]

  it('requires every term, in any order', () => {
    expect(matchesTerms(entry, searchTerms('drukqs aphex'))).toBe(true)
    expect(matchesTerms(entry, searchTerms('aphex drukqs'))).toBe(true)
    expect(matchesTerms(entry, searchTerms('aphex geogaddi'))).toBe(false)
  })

  it('treats an empty query as matching everything', () => {
    expect(matchesTerms(entry, searchTerms(''))).toBe(true)
  })
})

describe('mergeCollection', () => {
  it('collapses an item present in several lists and records every section', () => {
    const drukqs = item({ album_id: 10, title: 'Drukqs' })
    const merged = mergeCollection({ ...empty, owned: [drukqs], liked: [drukqs] })

    expect(merged).toHaveLength(1)
    // Fixed order, so the label always reads "owned · liked".
    expect(merged[0].sections).toEqual(['owned', 'liked'])
  })

  it('keeps distinct items apart', () => {
    const merged = mergeCollection({
      ...empty,
      owned: [item({ album_id: 1, title: 'One' }), item({ album_id: 2, title: 'Two' })],
    })
    expect(merged.map((e) => e.title)).toEqual(['One', 'Two'])
  })

  it('sorts by artist then title, ignoring case', () => {
    // Byte-order sorting would put every capital first and so lead with
    // "Boards of Canada"; case-insensitive collation leads with aphex.
    const merged = mergeCollection({
      ...empty,
      owned: [
        item({ album_id: 1, title: 'Geogaddi', band_name: 'Boards of Canada' }),
        item({ album_id: 2, title: 'Windowlicker', band_name: 'aphex twin' }),
        item({ album_id: 3, title: 'Drukqs', band_name: 'aphex twin' }),
      ],
    })
    expect(merged.map((e) => e.title)).toEqual(['Drukqs', 'Windowlicker', 'Geogaddi'])
  })

  it('sorts a missing artist first rather than crashing', () => {
    // Matches the API's `lower(coalesce(band_name, ''))`: no artist becomes ''.
    const merged = mergeCollection({
      ...empty,
      owned: [
        item({ album_id: 1, title: 'Known', band_name: 'Someone' }),
        item({ album_id: 2, title: null, band_name: null }),
      ],
    })
    expect(merged.map((e) => e.band_name)).toEqual([null, 'Someone'])
  })

  it('builds a haystack from a row with no title and no artist', () => {
    const merged = mergeCollection({ ...empty, owned: [item({ title: null, band_name: null })] })
    expect(merged[0].haystack.trim()).toBe('')
  })
})
