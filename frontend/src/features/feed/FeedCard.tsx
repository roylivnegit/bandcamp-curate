import type { Recommendation } from '../../api/types'
import { bandcampHandle, plural } from '../../lib/format'

/** `exiting` drives the evaporate animation the old UI had: a liked/blocked card
 *  dissolves upward instead of vanishing, so you can see what you just acted on. */
export function FeedCard({
  rec,
  exiting,
  busy,
  onLike,
  onBlock,
  onTagClick,
  onBandClick,
}: {
  rec: Recommendation
  exiting: 'like' | 'block' | null
  busy: boolean
  onLike: () => void
  onBlock: () => void
  onTagClick: (tag: string) => void
  onBandClick: () => void
}) {
  const co = rec.reasons.co_owners ?? 0
  const handle = bandcampHandle(rec.url)
  const tags = rec.reasons.matched_tags ?? []
  const seedTags = rec.reasons.seed_tags ?? []

  return (
    <article className={`card${exiting ? ` ${exiting}ing` : ''}`}>
      <div className="score" title="Recommendation score">
        <b className="num">{rec.score.toFixed(1)}</b>
        <span>score</span>
      </div>

      <div className="card-body">
        <h3 className="card-title">
          {rec.title || 'Untitled'}
          <span className="type">{rec.item_type}</span>
        </h3>

        {rec.band_id ? (
          <button type="button" className="band" onClick={onBandClick}>
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

        {seedTags.length > 0 && (
          <p className="via" title="Genres of your own releases that surfaced this">
            via {seedTags.slice(0, 5).join(', ')}
            {seedTags.length > 5 ? ` +${seedTags.length - 5}` : ''}
          </p>
        )}

        <div className="card-actions">
          <button type="button" className="act like" disabled={busy} onClick={onLike}>
            ♥ like
          </button>
          {rec.band_id !== null && (
            <button type="button" className="act block" disabled={busy} onClick={onBlock}>
              ⊘ block
            </button>
          )}
          {rec.url && (
            <a className="listen" href={rec.url} target="_blank" rel="noopener noreferrer">
              Bandcamp ↗
            </a>
          )}
        </div>
      </div>
    </article>
  )
}
