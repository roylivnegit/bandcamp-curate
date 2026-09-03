import type { ColdStart } from '../../api/types'
import { ColdStartPanel } from './ColdStartPanel'

interface EmptyStateProps {
  anyActive: boolean
  coldStart: ColdStart | null | undefined
  onClearFilters: () => void
}

/** The zero-result view once the feed has genuinely finished loading (no
 *  `loading`, no `error`, `rows.length === 0`) — extracted from `ScanFeedPage`
 *  so the two real causes carry a stable `data-testid` each, rather than being
 *  told apart only by matching on copy. `filtered-empty`: an active filter
 *  narrowed the server-side result set to nothing, a click away from fixing.
 *  `cold-start`: no filter at all, so `ColdStartPanel`'s own diagnostics (or,
 *  before those have loaded, nothing) explain why the scan itself hasn't
 *  produced anything yet. */
export function EmptyState({ anyActive, coldStart, onClearFilters }: EmptyStateProps) {
  if (anyActive) {
    return (
      <div data-testid="empty-filtered">
        <p className="empty">Nothing matches these filters — try clearing one.</p>
        <button type="button" className="btn ghost" onClick={onClearFilters}>
          Clear filters
        </button>
      </div>
    )
  }

  return (
    <div data-testid="empty-cold-start">
      <p className="empty">No recommendations in this scan yet.</p>
      <ColdStartPanel coldStart={coldStart} />
    </div>
  )
}
