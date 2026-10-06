import { memo, useState } from 'react'

import { bandcampHandle } from '../../lib/format'
import { SECTION_LABELS, type CollectionEntry } from '../../lib/collection'

/** One row of the collection.
 *
 *  Memoized with item-taking callbacks, same contract as `FeedCard`: a
 *  collection is thousands of rows, and without both halves every keystroke in
 *  the search box would re-render every row still on screen. */
export const CollectionRow = memo(function CollectionRow({
  entry,
  busy,
  onArtistClick,
  onUnlike,
}: {
  entry: CollectionEntry
  busy: boolean
  /** Puts the artist's name in the search box. Note this is a text search, not
   *  an exact artist filter: a short name ("Air", "Low") also matches titles
   *  that merely contain those letters. It only ever over-includes your own
   *  items, never hides one. A real `?band=` filter is the fix, and it is a
   *  feature rather than a repair. */
  onArtistClick: (entry: CollectionEntry) => void
  onUnlike: (entry: CollectionEntry) => void
}) {
  const handle = bandcampHandle(entry.url)
  // Not every crawled item has a stored art_id, and a URL that resolved at
  // crawl time can still 404 later (CDN churn) — same fallback as FeedCard,
  // minus the score box it falls back to.
  const [artFailed, setArtFailed] = useState(false)
  const showArt = Boolean(entry.art_url) && !artFailed
  const liked = entry.sections.includes('liked')

  return (
    <article className="crow">
      {showArt ? (
        // Decorative: the title and artist beside it already say what this is,
        // so an alt would make a screen reader read every row twice.
        <img
          className="crow-art"
          src={entry.art_url ?? undefined}
          alt=""
          loading="lazy"
          onError={() => setArtFailed(true)}
        />
      ) : (
        <div className="crow-art empty" aria-hidden="true" />
      )}

      <div className="crow-body">
        {/* h2: the page h1 is "Collection". Styling is on `.crow-title`. */}
        <h2 className="crow-title">{entry.title || 'Untitled'}</h2>

        {entry.band_name ? (
          <button type="button" className="crow-band" onClick={() => onArtistClick(entry)}>
            {entry.band_name}
            {handle && <span className="handle">{handle}</span>}
          </button>
        ) : (
          <div className="crow-band static">Unknown artist</div>
        )}
      </div>

      <div className="crow-side">
        <div className="crow-tags">
          {entry.sections.map((s) => (
            <span key={s} className={`chip sect ${s}`}>
              {SECTION_LABELS[s]}
            </span>
          ))}
        </div>
        <div className="crow-actions">
          {liked && (
            <button
              type="button"
              className="act unlike"
              disabled={busy}
              onClick={() => onUnlike(entry)}
            >
              {busy ? 'Removing…' : 'Unlike'}
            </button>
          )}
          {entry.url && (
            <a className="listen" href={entry.url} target="_blank" rel="noopener noreferrer">
              Bandcamp ↗
            </a>
          )}
        </div>
      </div>
    </article>
  )
})

/** Shaped like a real row so the first paint doesn't shift when data lands.
 *  Decorative — the announcement comes from the `role="status"` count line. */
export function CollectionRowSkeleton() {
  return (
    <article className="crow skeleton" aria-hidden="true">
      <div className="sk crow-art" />
      <div className="crow-body">
        <div className="sk sk-title" />
        <div className="sk sk-band" />
      </div>
    </article>
  )
}
