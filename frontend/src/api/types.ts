/* Mirrors the FastAPI response models. Kept hand-written (rather than generated
 * from the OpenAPI schema) because it's a handful of shapes and the explicit
 * types double as documentation of the contract. */

export type ItemType = 'album' | 'track'
export type ScanKind = 'collection' | 'custom'
export type ScanStatus = 'draft' | 'queued' | 'running' | 'done' | 'error'
export type SortKey = 'score' | 'neighbours' | 'affinity'

export interface Reasons {
  co_owners: number
  tag_affinity: number
  matched_tags: string[]
  seed_tags: string[]
}

export interface Recommendation {
  rank: number
  item_type: ItemType
  score: number
  album_id: number | null
  track_id: number | null
  title: string | null
  band_id: number | null
  band_name: string | null
  url: string | null
  reasons: Reasons
  /** The scan's recompute_generation at fetch time — every row in one
   *  response shares it (see backend migration 0013). */
  recompute_generation: number
}

export interface Facet {
  value: string
  label: string
  count: number
}

export interface Facets {
  tags: Facet[]
  labels: Facet[]
  seed_tags: Facet[]
}

export interface Stats {
  recommendations: number
  fans: number
  neighbours: number
  albums: number
  tracks: number
  my_owned: number
  my_wishlist: number
  follows: number
  liked: number
  requests_used: number
  request_budget: number
  recompute_generation: number | null
}

export interface ScanSeed {
  url: string
  seed_type: ItemType
  resolved_album_id: number | null
  resolved_track_id: number | null
}

export interface Scan {
  id: number
  name: string
  kind: ScanKind
  status: ScanStatus
  error: string | null
  seed_count: number
  rec_count: number
  last_run_at: string | null
  stats: { recommendations?: number; credits?: number }
  /** Bumped on every recompute — see backend migration 0013. Changes strictly
   *  more often than `stats.recommendations`: a swap (one item in, one out)
   *  reorders the feed without moving the total count. */
  recompute_generation: number
}

export interface ScanDetail extends Scan {
  seeds: ScanSeed[]
}

export interface Blocked {
  id: number
  band_id: number
  band_name: string | null
  band_url: string | null
  reason: string | null
}

export interface Liked {
  id: number
  item_type: ItemType
  album_id: number | null
  track_id: number | null
  title: string | null
  band_name: string | null
  url: string | null
}

export interface CollectionScanRef {
  id: number
  status: ScanStatus
}

export interface Me {
  id: number
  username: string
  bandcamp_fan_url: string | null
  /** Whether the collection crawl has run — false right after signup. */
  has_crawled: boolean
  collection_scan: CollectionScanRef | null
}

export interface TokenResponse {
  access_token: string
  token_type: string
}

/** Item identity for like/unlike — exactly one of the two ids, as the API requires. */
export type ItemRef = { album_id: number } | { track_id: number }
