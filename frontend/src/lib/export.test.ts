import { describe, expect, it } from 'vitest'

import type { Recommendation } from '../api/types'
import { formatRecommendationsAsCsv } from './export'

function rec(overrides: Partial<Recommendation> = {}): Recommendation {
  return {
    rank: 1,
    item_type: 'album',
    score: 3.5,
    album_id: 10,
    track_id: null,
    title: 'Some Album',
    band_id: 20,
    band_name: 'Some Band',
    url: 'https://someband.bandcamp.com/album/some-album',
    art_url: null,
    reasons: { co_owners: 2, tag_affinity: 0.5, matched_tags: ['ambient'], seed_tags: [] },
    recompute_generation: 1,
    ...overrides,
  }
}

/** Minimal RFC-4180 parser, test-only — round-trips whatever
 *  `formatRecommendationsAsCsv` produces back into rows of plain strings,
 *  so the escaping tests below check real CSV semantics rather than just
 *  eyeballing the raw string. */
function parseCsv(text: string): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let field = ''
  let inQuotes = false
  let i = 0
  while (i < text.length) {
    const c = text[i]
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') {
          field += '"'
          i += 2
          continue
        }
        inQuotes = false
        i++
        continue
      }
      field += c
      i++
      continue
    }
    if (c === '"') {
      inQuotes = true
      i++
      continue
    }
    if (c === ',') {
      row.push(field)
      field = ''
      i++
      continue
    }
    if (c === '\r' && text[i + 1] === '\n') {
      row.push(field)
      rows.push(row)
      row = []
      field = ''
      i += 2
      continue
    }
    field += c
    i++
  }
  row.push(field)
  rows.push(row)
  return rows
}

describe('formatRecommendationsAsCsv', () => {
  it('starts with the expected header row', () => {
    const rows = parseCsv(formatRecommendationsAsCsv([]))
    expect(rows[0]).toEqual([
      'Rank',
      'Type',
      'Title',
      'Artist',
      'Score',
      'Co-owners',
      'Genre match',
      'URL',
    ])
  })

  it('produces one row per recommendation, with the header column count', () => {
    const csv = formatRecommendationsAsCsv([rec(), rec({ rank: 2, item_type: 'track' })])
    const rows = parseCsv(csv)
    expect(rows).toHaveLength(3) // header + 2
    for (const row of rows) expect(row).toHaveLength(8)
    expect(rows[1]?.[1]).toBe('album')
    expect(rows[2]?.[1]).toBe('track')
  })

  it('round-trips a title containing a comma', () => {
    const csv = formatRecommendationsAsCsv([rec({ title: 'Live, Vol. 2' })])
    const rows = parseCsv(csv)
    expect(rows[1]?.[2]).toBe('Live, Vol. 2')
  })

  it('round-trips a title containing a quote', () => {
    const csv = formatRecommendationsAsCsv([rec({ title: 'The "Lost" Sessions' })])
    const rows = parseCsv(csv)
    expect(rows[1]?.[2]).toBe('The "Lost" Sessions')
  })

  it('round-trips an artist name containing an embedded newline', () => {
    const csv = formatRecommendationsAsCsv([rec({ band_name: 'Two\nWords' })])
    const rows = parseCsv(csv)
    expect(rows[1]?.[3]).toBe('Two\nWords')
  })

  it('falls back to an empty field for a null title/artist/url', () => {
    const csv = formatRecommendationsAsCsv([rec({ title: null, band_name: null, url: null })])
    const rows = parseCsv(csv)
    expect(rows[1]?.[2]).toBe('')
    expect(rows[1]?.[3]).toBe('')
    expect(rows[1]?.[7]).toBe('')
  })

  it('produces header-only output for an empty list', () => {
    const csv = formatRecommendationsAsCsv([])
    expect(parseCsv(csv)).toHaveLength(1)
  })
})
