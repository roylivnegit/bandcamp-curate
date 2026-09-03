import { describe, expect, it } from 'vitest'

import type { Recommendation } from '../api/types'
import { matchesQuery } from './quickFilter'

function rec(overrides: Partial<Recommendation> = {}): Recommendation {
  return {
    rank: 1,
    item_type: 'album',
    score: 1,
    album_id: 1,
    track_id: null,
    title: 'Deep Forest',
    band_id: 1,
    band_name: 'Psybient Collective',
    url: null,
    reasons: { co_owners: 1, tag_affinity: 0, matched_tags: [], seed_tags: [] },
    recompute_generation: 1,
    ...overrides,
  }
}

describe('matchesQuery', () => {
  it('matches on title, case-insensitively', () => {
    expect(matchesQuery(rec({ title: 'Deep Forest' }), 'deep')).toBe(true)
    expect(matchesQuery(rec({ title: 'Deep Forest' }), 'FOREST')).toBe(true)
  })

  it('matches on band name', () => {
    expect(matchesQuery(rec({ band_name: 'Psybient Collective' }), 'collective')).toBe(true)
  })

  it('rejects when neither title nor band name contains the query', () => {
    expect(matchesQuery(rec({ title: 'Deep Forest', band_name: 'Psybient Collective' }), 'techno')).toBe(
      false,
    )
  })

  it('treats an empty or whitespace-only query as matching everything', () => {
    expect(matchesQuery(rec(), '')).toBe(true)
    expect(matchesQuery(rec(), '   ')).toBe(true)
  })

  it('tolerates a null title or band name', () => {
    expect(matchesQuery(rec({ title: null, band_name: 'Psybient Collective' }), 'psybient')).toBe(true)
    expect(matchesQuery(rec({ title: null, band_name: null }), 'anything')).toBe(false)
  })
})
