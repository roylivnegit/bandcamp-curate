import type { ColdStart } from '../../api/types'
import { count, plural } from '../../lib/format'

/** Explains *why* the feed is empty using the backend's own cold-start
 *  diagnostics, instead of leaving the reader looking at a bare "no
 *  recommendations yet" with no way to tell "still crawling" from "everything
 *  got excluded" from "nobody to compare against yet". Renders nothing until
 *  that data has loaded. */
export function ColdStartPanel({
  coldStart,
  requestsUsed,
  requestBudget,
}: {
  coldStart: ColdStart | null | undefined
  /** From the same `/api/stats` response as `coldStart` (`Stats.requests_used`
   *  / `.request_budget`) — shown here, not elsewhere, because an empty feed
   *  is exactly when a reader wants to know whether the crawl is still
   *  running or has simply used up its budget. `null`/`undefined`/a zero
   *  budget renders nothing extra. */
  requestsUsed?: number | null
  requestBudget?: number | null
}) {
  if (!coldStart) return null

  const {
    neighbour_count,
    candidates,
    excluded_owned,
    excluded_wishlisted,
    excluded_followed,
    excluded_blacklisted,
    excluded_liked,
  } = coldStart

  const budgetLine =
    requestsUsed != null && requestBudget != null && requestBudget > 0 ? (
      <p className="hint">
        <b className="num">{count(requestsUsed)}</b> of <b className="num">{count(requestBudget)}</b>{' '}
        crawl requests used this scan.
      </p>
    ) : null

  if (neighbour_count === 0) {
    return (
      <div className="coldstart">
        <p className="hint">
          No taste-neighbours found yet — once the crawl discovers other collectors who own the
          same records you do, recommendations start appearing here.
        </p>
        {budgetLine}
      </div>
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
          <b className="num">{count(excluded_blacklisted)}</b> blocked ·{' '}
          <b className="num">{count(excluded_liked)}</b> liked.
        </p>
      )}
      {budgetLine}
    </div>
  )
}
