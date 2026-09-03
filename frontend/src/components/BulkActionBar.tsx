/** Floating bar shown while one or more feed cards are selected in bulk-select
 *  mode — "N selected", then Cancel / Block selected. Renders nothing once
 *  the selection is empty, so mounting it unconditionally is safe. */
export function BulkActionBar({
  count,
  busy,
  onBlock,
  onCancel,
}: {
  count: number
  busy: boolean
  onBlock: () => void
  onCancel: () => void
}) {
  if (count === 0) return null

  return (
    <div className="bulkbar" role="status">
      <span>
        <b className="num">{count}</b> selected
      </span>
      <button type="button" className="btn ghost" onClick={onCancel} disabled={busy}>
        Cancel
      </button>
      <button type="button" className="btn" onClick={onBlock} disabled={busy}>
        {busy ? 'Blocking…' : 'Block selected'}
      </button>
    </div>
  )
}
