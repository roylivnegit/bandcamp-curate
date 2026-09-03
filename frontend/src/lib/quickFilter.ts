import type { Recommendation } from '../api/types'

/** Pure client-side view filter over already-loaded rows — no API call, just
 *  a case-insensitive substring match against title/band name. An empty (or
 *  all-whitespace) query matches everything, so callers can always run rows
 *  through this rather than branching on "is a query active". */
export function matchesQuery(rec: Recommendation, query: string): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return true
  const title = rec.title?.toLowerCase() ?? ''
  const band = rec.band_name?.toLowerCase() ?? ''
  return title.includes(q) || band.includes(q)
}
