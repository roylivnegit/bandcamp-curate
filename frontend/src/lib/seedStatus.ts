import type { ScanSeed, ScanStatus } from '../api/types'

export type SeedResolution = 'resolved' | 'pending' | 'unresolved'

/** Pure derivation from data the API already returns — no network of its own.
 *  `ScanSeed` (see backend `ScanSeed` model) never carries a distinct "failed
 *  to resolve" signal, so a still-null seed on a scan that has already
 *  finished crawling (`done`/`error`) is a normal outcome (a stale link, a
 *  removed release) rather than a reportable error — labeled "unresolved",
 *  not something scarier. Before the crawl has had a chance to look at it
 *  (`draft`/`queued`/`running`), the same null pair just means "pending". */
export function seedStatus(seed: ScanSeed, scanStatus: ScanStatus): SeedResolution {
  if (seed.resolved_album_id !== null || seed.resolved_track_id !== null) return 'resolved'
  if (scanStatus === 'done' || scanStatus === 'error') return 'unresolved'
  return 'pending'
}
