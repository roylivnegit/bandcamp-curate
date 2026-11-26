import { describe, expect, it } from 'vitest'

import type { SearchHit, SearchResponse } from '../api/types'
import { searchRows } from './searchHits'

function hit(over: Partial<SearchHit> = {}): SearchHit {
  return {
    kind: 'collection',
    title: 'Drukqs',
    band_name: 'Aphex Twin',
    item_type: 'album',
    album_id: 1,
    track_id: null,
    url: 'https://aphex.bandcamp.com/album/drukqs',
    art_url: null,
    scan_id: null,
    scan_name: null,
    sections: ['owned'],
    ...over,
  }
}

function response(over: Partial<SearchResponse> = {}): SearchResponse {
  return { query: 'q', collection: [], feed: [], truncated: false, ...over }
}

describe('searchRows', () => {
  it('puts what the user already has before what the feed suggests', () => {
    const rows = searchRows(
      response({
        collection: [hit()],
        feed: [hit({ kind: 'feed', title: 'Xtal', scan_id: 7, scan_name: 'Psy dig' })],
      }),
    )
    expect(rows.map((r) => r.label)).toEqual(['Drukqs — Aphex Twin', 'Xtal — Aphex Twin'])
  })

  it('sends a collection row to the Collection page pre-filtered to that title', () => {
    const [row] = searchRows(response({ collection: [hit({ title: 'Music Has the Right' })] }))
    expect(row.to).toBe('/collection?q=Music%20Has%20the%20Right')
  })

  it('labels every list a collection row is in', () => {
    const [row] = searchRows(response({ collection: [hit({ sections: ['owned', 'liked'] })] }))
    expect(row.hint).toBe('owned · liked')
  })

  it('opens a feed row on Bandcamp, and says so to a screen reader', () => {
    const [row] = searchRows(
      response({
        feed: [hit({ kind: 'feed', scan_id: 7, scan_name: 'Psy dig', url: 'https://x.test/a' })],
      }),
    )
    expect(row.openUrl).toBe('https://x.test/a')
    expect(row.to).toBeUndefined()
    expect(row.hint).toBe('in Psy dig ↗')
    expect(row.srHint).toContain('opens Bandcamp in a new tab')
  })

  it('falls back to the scan when a feed row has no URL', () => {
    const [row] = searchRows(
      response({ feed: [hit({ kind: 'feed', scan_id: 7, scan_name: 'Psy dig', url: null })] }),
    )
    expect(row.openUrl).toBeUndefined()
    expect(row.to).toBe('/scans/7')
    expect(row.hint).toBe('in Psy dig')
  })

  it('reads a record with only one of title/artist, and never renders an empty label', () => {
    const rows = searchRows(
      response({
        collection: [
          hit({ title: 'Untitled 3', band_name: null, album_id: 1 }),
          hit({ title: null, band_name: 'Boards of Canada', album_id: 2 }),
          hit({ title: null, band_name: null, album_id: 3 }),
        ],
      }),
    )
    expect(rows.map((r) => r.label)).toEqual(['Untitled 3', 'Boards of Canada', 'Untitled'])
  })

  it('keys a track row off the track id, so an album and a track never collide', () => {
    const rows = searchRows(
      response({
        collection: [
          hit({ item_type: 'album', album_id: 5, track_id: null }),
          hit({ item_type: 'track', album_id: null, track_id: 5 }),
        ],
      }),
    )
    expect(new Set(rows.map((r) => r.id)).size).toBe(2)
  })
})
