import { memo, useState } from 'react'
import type { KeyboardEvent, MouseEvent } from 'react'

import type { Recommendation } from '../../api/types'
import { bandcampHandle, plural } from '../../lib/format'
import { isVisited, markVisited } from '../../lib/visited'

/** `exiting` drives the evaporate animation the old UI had: a liked/blocked card
 *  dissolves upward instead of vanishing, so you can see what you just acted on.
 *
 *  Memoized, and every callback takes the `rec` rather than closing over it. The
 *  feed grows to hundreds of rows via "load more", and without both halves of
 *  that every unrelated parent state change (a poll tick, one row's busy flag, a
 *  panel toggle) re-renders every card: per-row closures would be new props on
 *  each render, so `memo` alone would never hit. */
export const FeedCard = memo(function FeedCard({
  rec,
  cardId,
  active,
  exiting,
  busyAction,
  selectMode,
  selected,
  onLike,
  onBlock,
  onTagClick,
  onBandClick,
  onToggleSelect,
}: {
  rec: Recommendation
  /** DOM id, so the roving-tabindex handler in `ScanFeedPage` can focus this
   *  exact card by id after an Arrow/Home/End key, without holding a ref per
   *  row. */
  cardId: string
  /** Roving tabindex: only the active card is reachable by Tab (`tabIndex=0`);
   *  the rest are `-1` but stay focusable by script for arrow-key navigation. */
  active: boolean
  exiting: 'like' | 'block' | null
  /** Which in-flight action, if any, disables both buttons and swaps the
   *  acting one's label to "Liking…"/"Blocking…" — not just a bare disabled,
   *  which read as unresponsive for the gap before the card animates out. */
  busyAction: 'like' | 'block' | null
  /** Bulk-select mode, toggled from the filter bar. Only cards with a band
   *  can be selected — bulk-block, the only bulk action today, needs one. */
  selectMode: boolean
  selected: boolean
  onLike: (rec: Recommendation) => void
  /** `expiresAt` (an ISO string), when passed, makes this a temporary block —
   *  see the "block for… ▾" picker below. Omitted, it's the existing
   *  permanent block. */
  onBlock: (rec: Recommendation, expiresAt?: string | null) => void
  onTagClick: (tag: string) => void
  onBandClick: (rec: Recommendation) => void
  onToggleSelect: (rec: Recommendation) => void
}) {
  const busy = busyAction !== null
  const co = rec.reasons.co_owners ?? 0
  const handle = bandcampHandle(rec.url)
  const tags = rec.reasons.matched_tags ?? []
  // `cardId` is already a stable per-item key (see ScanFeedPage's `cardIdOf`),
  // so it doubles as the "seen" storage key with nothing extra to compute.
  // Local state (not a prop) because clicking "Bandcamp ↗" only changes what
  // this one card knows — nothing the parent tracks.
  const [visited, setVisited] = useState(() => isVisited(cardId))
  // Some crawled items have no stored art_id yet (see api/types.ts), and a
  // URL that resolves fine at crawl time can still 404 later (Bandcamp CDN
  // churn) — either way, fall back to the plain score box rather than a
  // broken-image icon.
  const [artFailed, setArtFailed] = useState(false)
  const showArt = Boolean(rec.art_url) && !artFailed

  /** Triaging a long feed is mouse-only otherwise. Scoped to the card via a
   *  single listener on the article — any focused element inside it (a chip,
   *  the band button, the action buttons themselves) already bubbles keydown
   *  up here, so no extra tabIndex/focus wiring is needed. A modifier held
   *  down means the key is doing something else (a browser/OS shortcut),
   *  and `busy` mirrors the action buttons' own `disabled` state. */
  const onCardKeyDown = (e: KeyboardEvent<HTMLElement>) => {
    if (busy || e.ctrlKey || e.metaKey || e.altKey) return
    const key = e.key.toLowerCase()
    if (key === 'l') {
      e.preventDefault()
      onLike(rec)
    } else if (key === 'b' && rec.band_id !== null) {
      e.preventDefault()
      onBlock(rec)
    }
  }

  const selectable = selectMode && rec.band_id !== null

  /** In select mode, a click anywhere on the card toggles it — except on
   *  something that already does its own thing when clicked (a button, a
   *  link, the checkbox itself). `closest` catches those regardless of which
   *  inner element the click actually landed on. */
  const onCardClick = (e: MouseEvent<HTMLElement>) => {
    if (!selectable) return
    if ((e.target as HTMLElement).closest('button, a, input')) return
    onToggleSelect(rec)
  }

  return (
    <article
      id={cardId}
      className={`card${exiting ? ` ${exiting}ing` : ''}${selectable ? ' selectable' : ''}${selected ? ' selected' : ''}`}
      tabIndex={active ? 0 : -1}
      onKeyDown={onCardKeyDown}
      onClick={onCardClick}
      data-visited={visited ? 'true' : undefined}
    >
      {selectMode && rec.band_id !== null && (
        <input
          type="checkbox"
          className="card-select"
          aria-label={`Select ${rec.title || 'this recommendation'}`}
          checked={selected}
          onChange={() => onToggleSelect(rec)}
        />
      )}

      {showArt && (
        // Decorative: the title/artist text right next to it already carries
        // the identifying information, so an empty alt avoids a screen
        // reader announcing a redundant "cover art for <title>" on every
        // single card in a feed of hundreds.
        <img
          className="card-art"
          src={rec.art_url ?? undefined}
          alt=""
          loading="lazy"
          onError={() => setArtFailed(true)}
        />
      )}

      <div className="score" title="Recommendation score">
        <b className="num">{rec.score.toFixed(1)}</b>
        <span>score</span>
      </div>

      <div className="card-body">
        {/* h2: the page's h1 is the scan title, so h3 skipped a level. Styling
            comes from `.card-title`, not the tag. */}
        <h2 className="card-title">
          {rec.title || 'Untitled'}
          <span className="type">{rec.item_type}</span>
        </h2>

        {rec.band_id ? (
          <button type="button" className="band" onClick={() => onBandClick(rec)}>
            {rec.band_name || 'unknown artist'}
            {handle && <span className="handle">{handle}</span>}
          </button>
        ) : (
          <div className="band static">{rec.band_name || 'unknown artist'}</div>
        )}

        <div className="card-meta">
          <span className="chip signal" title="Taste-neighbours who own this">
            ◈ {co} {plural(co, 'neighbour')} {co === 1 ? 'owns' : 'own'} this
          </span>
          {tags.map((t) => (
            <button key={t} type="button" className="chip tag" onClick={() => onTagClick(t)}>
              {t}
            </button>
          ))}
        </div>

        <div className="card-actions">
          <button
            type="button"
            className="act like"
            disabled={busy}
            aria-keyshortcuts="l"
            onClick={() => onLike(rec)}
          >
            {busyAction === 'like' ? 'Liking…' : '♥ like'}
          </button>
          {rec.band_id !== null && (
            <button
              type="button"
              className="act block"
              disabled={busy}
              aria-keyshortcuts="b"
              onClick={() => onBlock(rec)}
            >
              {busyAction === 'block' ? 'Blocking…' : '⊘ block'}
            </button>
          )}
          {rec.url && (
            <a
              className="listen"
              href={rec.url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => {
                markVisited(cardId)
                setVisited(true)
              }}
            >
              Bandcamp ↗
            </a>
          )}
          {visited && <span className="seen-tag">seen</span>}
        </div>
      </div>
    </article>
  )
})

/** Shaped like a real `FeedCard` so the first page doesn't cause a layout
 *  shift when the real rows land. Purely decorative — `aria-hidden` on each
 *  card, with the announcement carried by the `role="status"` wrapper in
 *  `ScanFeedPage`. */
export function FeedCardSkeleton() {
  return (
    <article className="card skeleton" aria-hidden="true">
      <div className="sk sk-score" />
      <div className="card-body">
        <div className="sk sk-title" />
        <div className="sk sk-band" />
        <div className="card-meta">
          <div className="sk sk-chip" />
        </div>
      </div>
    </article>
  )
}
