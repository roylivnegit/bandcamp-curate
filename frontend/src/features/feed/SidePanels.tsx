import { useState } from 'react'
import type { Blocked, Liked } from '../../api/types'
import { Dropdown } from '../../components/Dropdown'
import { BLOCK_DURATIONS, RENEW_WINDOW_MS, SIDEPANEL_PAGE_SIZE } from '../../config'
import { expiresLabel } from '../../lib/format'

/** Ascending by expiry — soonest-to-lapse first, permanent blocks (no
 *  `expires_at`) last, since there's nothing there to act on soon. */
function byExpirySoonestFirst(a: Blocked, b: Blocked): number {
  if (a.expires_at === null && b.expires_at === null) return 0
  if (a.expires_at === null) return 1
  if (b.expires_at === null) return -1
  return new Date(a.expires_at).getTime() - new Date(b.expires_at).getTime()
}

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
  const [visibleCount, setVisibleCount] = useState(SIDEPANEL_PAGE_SIZE)
  const visible = items.slice(0, visibleCount)
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
            {visible.map((r) => {
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
          {visibleCount < items.length && (
            <button
              type="button"
              className="btn ghost"
              onClick={() => setVisibleCount((n) => n + SIDEPANEL_PAGE_SIZE)}
            >
              Show more
            </button>
          )}
        </>
      )}
    </div>
  )
}

export function BlockedPanel({
  items,
  onUnblock,
  onRenew,
  busy,
}: {
  items: Blocked[]
  onUnblock: (bandId: number) => void
  /** Re-block the same band with a fresh `expires_at` — offered only on a
   *  row whose current block is about to lapse (see `RENEW_WINDOW_MS`). */
  onRenew: (bandId: number, expiresAt: string) => void
  /** Whether this band's unblock is in flight — see `LikedPanel`'s `busy`. */
  busy: (bandId: number) => boolean
}) {
  const [visibleCount, setVisibleCount] = useState(SIDEPANEL_PAGE_SIZE)
  const sorted = [...items].sort(byExpirySoonestFirst)
  const visible = sorted.slice(0, visibleCount)
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
            {visible.map((b) => {
              const rowBusy = busy(b.band_id)
              const expiry = expiresLabel(b.expires_at)
              const bandLabel = b.band_name || `band ${b.band_id}`
              const expiresSoon =
                b.expires_at !== null &&
                new Date(b.expires_at).getTime() - Date.now() <= RENEW_WINDOW_MS &&
                new Date(b.expires_at).getTime() > Date.now()
              return (
                <li className="row" key={b.id}>
                  <span className="row-main">
                    <b>{bandLabel}</b>
                    {expiry && <span className="hint"> · {expiry}</span>}
                  </span>
                  {b.band_url && (
                    // Icon-only link, same pattern as LikedPanel's — the glyph is
                    // decorative, so the accessible name comes from aria-label.
                    <a
                      className="listen sm"
                      href={b.band_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      aria-label={`Open ${bandLabel} on Bandcamp`}
                    >
                      <span aria-hidden="true">↗</span>
                    </a>
                  )}
                  {expiresSoon && !rowBusy && (
                    <Dropdown label="renew ▾" width={140}>
                      {(close) => (
                        <div>
                          {BLOCK_DURATIONS.map((d) => (
                            <button
                              key={d.label}
                              type="button"
                              className="ddrow"
                              onClick={() => {
                                onRenew(b.band_id, new Date(Date.now() + d.ms).toISOString())
                                close()
                              }}
                            >
                              <span className="nm">{d.label}</span>
                            </button>
                          ))}
                        </div>
                      )}
                    </Dropdown>
                  )}
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
          {visibleCount < sorted.length && (
            <button
              type="button"
              className="btn ghost"
              onClick={() => setVisibleCount((n) => n + SIDEPANEL_PAGE_SIZE)}
            >
              Show more
            </button>
          )}
        </>
      )}
    </div>
  )
}
