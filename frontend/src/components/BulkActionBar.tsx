import { useEffect, useRef, useState } from 'react'

import { BULK_CONFIRM_THRESHOLD, BULK_CONFIRM_WINDOW_MS } from '../config'

/** Floating bar shown while one or more feed cards are selected in bulk-select
 *  mode — "N selected", then Cancel / Like selected / Block selected.
 *  Renders nothing once the selection is empty, so mounting it
 *  unconditionally is safe.
 *
 *  Above `BULK_CONFIRM_THRESHOLD`, "Block selected" arms a "Block N bands?"
 *  confirm step (same two-click, auto-reverting shape as `DeleteScanButton`)
 *  instead of firing immediately — undo already exists for a single
 *  mis-click, but a large bulk block is a bigger blast radius than that. At
 *  or below the threshold, the click still fires right away. "Like selected"
 *  has no confirm step at any count — liking isn't destructive the way
 *  blocking is, so the extra click would only add friction. */
export function BulkActionBar({
  count,
  busyAction,
  onLike,
  onBlock,
  onCancel,
}: {
  count: number
  busyAction: 'like' | 'block' | null
  onLike: () => void
  onBlock: () => void
  onCancel: () => void
}) {
  const busy = busyAction !== null
  const [confirming, setConfirming] = useState(false)
  const revertTimer = useRef<number | null>(null)

  useEffect(() => {
    return () => {
      if (revertTimer.current !== null) window.clearTimeout(revertTimer.current)
    }
  }, [])

  // A changed selection size invalidates a pending confirm — left armed
  // against a stale N would block the wrong count of cards.
  useEffect(() => {
    if (revertTimer.current !== null) window.clearTimeout(revertTimer.current)
    setConfirming(false)
  }, [count])

  if (count === 0) return null

  function arm() {
    setConfirming(true)
    revertTimer.current = window.setTimeout(() => setConfirming(false), BULK_CONFIRM_WINDOW_MS)
  }

  function cancelConfirm() {
    if (revertTimer.current !== null) window.clearTimeout(revertTimer.current)
    setConfirming(false)
  }

  function handleBlockClick() {
    if (count > BULK_CONFIRM_THRESHOLD) arm()
    else onBlock()
  }

  function handleConfirmClick() {
    if (revertTimer.current !== null) window.clearTimeout(revertTimer.current)
    setConfirming(false)
    onBlock()
  }

  return (
    <div className="bulkbar" role="status">
      <span>
        <b className="num">{count}</b> selected
      </span>
      {confirming ? (
        <>
          <button type="button" className="btn ghost danger" onClick={handleConfirmClick} disabled={busy}>
            {busyAction === 'block' ? 'Blocking…' : `Block ${count} bands?`}
          </button>
          <button type="button" className="btn ghost" onClick={cancelConfirm} disabled={busy}>
            Cancel
          </button>
        </>
      ) : (
        <>
          <button type="button" className="btn ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button type="button" className="btn ghost" onClick={onLike} disabled={busy}>
            {busyAction === 'like' ? 'Liking…' : 'Like selected'}
          </button>
          <button type="button" className="btn" onClick={handleBlockClick} disabled={busy}>
            {busyAction === 'block' ? 'Blocking…' : 'Block selected'}
          </button>
        </>
      )}
    </div>
  )
}
