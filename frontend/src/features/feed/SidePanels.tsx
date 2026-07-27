import type { Blocked, Liked } from '../../api/types'

/** Liked and blocked are per-user but shared across all of that user's scans —
 *  the copy says so, since it's otherwise surprising. */

export function LikedPanel({
  items,
  onUnlike,
}: {
  items: Liked[]
  onUnlike: (item: Liked) => void
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
            {items.map((r) => (
              <li className="row" key={r.id}>
                <span className="row-main">
                  <b>{r.title || r.item_type}</b>
                  {r.band_name && <span className="hint"> {r.band_name}</span>}
                </span>
                {r.url && (
                  <a className="listen sm" href={r.url} target="_blank" rel="noopener noreferrer">
                    ↗
                  </a>
                )}
                <button type="button" className="act" onClick={() => onUnlike(r)}>
                  unlike
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

export function BlockedPanel({
  items,
  onUnblock,
}: {
  items: Blocked[]
  onUnblock: (bandId: number) => void
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
            {items.map((b) => (
              <li className="row" key={b.id}>
                <span className="row-main">
                  <b>{b.band_name || `band ${b.band_id}`}</b>
                  {b.band_url && <span className="hint"> {b.band_url}</span>}
                </span>
                <button type="button" className="act" onClick={() => onUnblock(b.band_id)}>
                  unblock
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
