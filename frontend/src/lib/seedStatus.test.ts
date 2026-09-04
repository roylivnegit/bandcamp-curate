import { describe, expect, it } from 'vitest'

import type { ScanSeed, ScanStatus } from '../api/types'
import { seedStatus } from './seedStatus'

function seed(overrides: Partial<ScanSeed> = {}): ScanSeed {
  return {
    url: 'https://x.bandcamp.com/album/y',
    seed_type: 'album',
    resolved_album_id: null,
    resolved_track_id: null,
    ...overrides,
  }
}

const STATUSES: ScanStatus[] = ['draft', 'queued', 'running', 'done', 'error']

describe('seedStatus', () => {
  it('is resolved regardless of scan status once resolved_album_id is set', () => {
    for (const status of STATUSES) {
      expect(seedStatus(seed({ resolved_album_id: 1 }), status)).toBe('resolved')
    }
  })

  it('is resolved regardless of scan status once resolved_track_id is set', () => {
    for (const status of STATUSES) {
      expect(seedStatus(seed({ resolved_track_id: 1 }), status)).toBe('resolved')
    }
  })

  it.each(['draft', 'queued', 'running'] as const)(
    'is pending while unresolved and the scan is %s',
    (status) => {
      expect(seedStatus(seed(), status)).toBe('pending')
    },
  )

  it.each(['done', 'error'] as const)(
    'is unresolved while still unresolved once the scan is %s',
    (status) => {
      expect(seedStatus(seed(), status)).toBe('unresolved')
    },
  )
})
