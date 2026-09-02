import type { Blocked, Liked } from '../../api/types'

/** Liked and blocked are per-user but shared across all of that user's scans —
 *  the copy says so, since it's otherwise surprising. */

export function LikedPanel({
  items,
  onUnlike,
  busy,
}: {
  items: Liked[]
  onUnlike: (item: Liked) => void
  /** Whether this item's unlike is in flight — the panel has no state of its
   *  own for this; it's a lookup into `ScanFeedPage`'s single source of
   *  truth, the same shape `like`/`block` already use for feed cards. */
  busy: (item: Liked) => boolean
}) {
  return (
    <div className="panel sidepanel">
      {items.length === 0 ? (
        <p className="hint">
          Nothing liked yet. Use <b>♥ like</b> on a card once you&rsquo;ve wishlisted, bought, or
          followed it.
        </p>
      ) : (
        <>
          <p className="hint">
            Liked — kept out of every scan. Your next collection crawl picks up the real
            wishlist/purchase/follow.
          </p>
          <ul className="rows">
            {items.map((r) => {
              const rowBusy = busy(r)
              return (
                <li className="row" key={r.id}>
                  <span className="row-main">
                    <b>{r.title || r.item_type}</b>
                    {r.band_name && <span className="hint"> {r.band_name}</span>}
                  </span>
                  {r.url && (
                    // Icon-only link: the glyph is decorative, so the accessible
                    // name has to come from aria-label or it announces as "↗".
                    <a
                      className="listen sm"
                      href={r.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      aria-label={`Open ${r.title || r.item_type} on Bandcamp`}
                    >
                      <span aria-hidden="true">↗</span>
                    </a>
                  )}
                  <button
                    type="button"
                    className="act"
                    disabled={rowBusy}
                    onClick={() => onUnlike(r)}
                  >
                    {rowBusy ? 'Unliking…' : 'unlike'}
                  </button>
                </li>
              )
            })}
          </ul>
        </>
      )}
    </div>
  )
}

export function BlockedPanel({
  items,
  onUnblock,
  busy,
}: {
  items: Blocked[]
  onUnblock: (bandId: number) => void
  /** Whether this band's unblock is in flight — see `LikedPanel`'s `busy`. */
  busy: (bandId: number) => boolean
}) {
  return (
    <div className="panel sidepanel">
      {items.length === 0 ? (
        <p className="hint">
          Nothing blocked yet. Use <b>⊘ block</b> on a card to hide an artist or label.
        </p>
      ) : (
        <>
          <p className="hint">Blocked artists and labels — never appear in any of your scans.</p>
          <ul className="rows">
            {items.map((b) => {
              const rowBusy = busy(b.band_id)
              return (
                <li className="row" key={b.id}>
                  <span className="row-main">
                    <b>{b.band_name || `band ${b.band_id}`}</b>
                    {b.band_url && <span className="hint"> {b.band_url}</span>}
                  </span>
                  <button
                    type="button"
                    className="act"
                    disabled={rowBusy}
                    onClick={() => onUnblock(b.band_id)}
                  >
                    {rowBusy ? 'Unblocking…' : 'unblock'}
                  </button>
                </li>
              )
            })}
          </ul>
        </>
      )}
    </div>
  )
}
