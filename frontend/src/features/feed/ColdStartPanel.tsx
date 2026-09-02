import type { ColdStart } from '../../api/types'
import { count, plural } from '../../lib/format'

/** Explains *why* the feed is empty using the backend's own cold-start
 *  diagnostics, instead of leaving the reader looking at a bare "no
 *  recommendations yet" with no way to tell "still crawling" from "everything
 *  got excluded" from "nobody to compare against yet". Renders nothing until
 *  that data has loaded. */
export function ColdStartPanel({ coldStart }: { coldStart: ColdStart | null | undefined }) {
  if (!coldStart) return null

  const {
    neighbour_count,
    candidates,
    excluded_owned,
    excluded_wishlisted,
    excluded_followed,
    excluded_blacklisted,
  } = coldStart

  if (neighbour_count === 0) {
    return (
      <p className="coldstart hint">
        No taste-neighbours found yet — once the crawl discovers other collectors who own the
        same records you do, recommendations start appearing here.
      </p>
    )
  }

  return (
    <div className="coldstart">
      <p>
        <b className="num">{count(neighbour_count)}</b> {plural(neighbour_count, 'taste-neighbour')}{' '}
        found, <b className="num">{count(candidates)}</b> {plural(candidates, 'candidate')} evaluated.
      </p>
      {candidates > 0 && (
        <p className="hint">
          All excluded: <b className="num">{count(excluded_owned)}</b> owned ·{' '}
          <b className="num">{count(excluded_wishlisted)}</b> wishlisted ·{' '}
          <b className="num">{count(excluded_followed)}</b> followed ·{' '}
          <b className="num">{count(excluded_blacklisted)}</b> blocked.
        </p>
      )}
    </div>
  )
}
