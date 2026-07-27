import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { api } from '../../api/client'
import type { Blocked, Facet, Liked, Recommendation, ScanDetail } from '../../api/types'
import { CARD_EXIT_MS, FEED_PAGE_SIZE, SCAN_POLL_MS } from '../../config'
import { count, plural } from '../../lib/format'
import { FeedCard } from './FeedCard'
import { FilterBar } from './FilterBar'
import { BlockedPanel, LikedPanel } from './SidePanels'
import { useFeedFilters } from './useFeedFilters'
import './feed.css'

const LIMIT = FEED_PAGE_SIZE

export function ScanFeedPage() {
  const { scanId: raw } = useParams()
  // A hand-typed or stale URL can put anything here. Number('abc') is NaN, which
  // would otherwise be sent as literal /api/scans/NaN.
  const parsed = Number(raw)
  const scanId = Number.isInteger(parsed) && parsed > 0 ? parsed : null
  const filters = useFeedFilters(scanId)

  const [scan, setScan] = useState<ScanDetail | null>(null)
  const [rows, setRows] = useState<Recommendation[]>([])
  const [total, setTotal] = useState<number | null>(null)
  const [facetTags, setFacetTags] = useState<Facet[]>([])
  const [liked, setLiked] = useState<Liked[]>([])
  const [blocked, setBlocked] = useState<Blocked[]>([])
  const [panel, setPanel] = useState<'liked' | 'blocked' | null>(null)
  const [exiting, setExiting] = useState<Record<string, 'like' | 'block'>>({})
  const [busyKeys, setBusyKeys] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(false)
  const [done, setDone] = useState(false)
  const [error, setError] = useState('')
  const pollTimer = useRef<number | undefined>(undefined)

  const ready = scan?.status === 'done'

  // ── scan metadata, polled while the crawl is still in flight ──────────────
  const loadScan = useCallback(async () => {
    if (scanId === null) return
    try {
      setScan(await api.getScan(scanId))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load this scan.')
    }
  }, [scanId])

  useEffect(() => {
    void loadScan()
  }, [loadScan])

  useEffect(() => {
    if (!scan || scan.status === 'done' || scan.status === 'error') return
    pollTimer.current = window.setTimeout(loadScan, SCAN_POLL_MS)
    return () => window.clearTimeout(pollTimer.current)
  }, [scan, loadScan])

  // ── side lists ───────────────────────────────────────────────────────────
  const loadLiked = useCallback(async () => setLiked(await api.listLikes()), [])
  const loadBlocked = useCallback(async () => setBlocked(await api.listBlocked()), [])
  const loadFacets = useCallback(async () => {
    setFacetTags((await api.facets(scanId)).tags)
  }, [scanId])

  useEffect(() => {
    void loadLiked().catch(() => {})
    void loadBlocked().catch(() => {})
  }, [loadLiked, loadBlocked])

  useEffect(() => {
    if (ready) void loadFacets().catch(() => {})
  }, [ready, loadFacets])

  // ── the feed itself ──────────────────────────────────────────────────────
  const loadFirstPage = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [page, c] = await Promise.all([
        api.recommendations(filters.params, { sort: filters.sort, limit: LIMIT, offset: 0 }),
        api.recommendationsCount(filters.params),
      ])
      setRows(page)
      setTotal(c.count)
      setDone(page.length < LIMIT)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load the feed.')
    } finally {
      setLoading(false)
    }
  }, [filters.params, filters.sort])

  useEffect(() => {
    if (ready) void loadFirstPage()
  }, [ready, loadFirstPage])

  async function loadMore() {
    if (loading || done) return
    setLoading(true)
    try {
      const page = await api.recommendations(filters.params, {
        sort: filters.sort,
        limit: LIMIT,
        offset: rows.length,
      })
      setRows((prev) => [...prev, ...page])
      if (page.length < LIMIT) setDone(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load more.')
    } finally {
      setLoading(false)
    }
  }

  // ── like / block ─────────────────────────────────────────────────────────
  const keyOf = (r: Recommendation) => `${r.item_type}:${r.album_id ?? r.track_id}`

  function markBusy(key: string, on: boolean) {
    setBusyKeys((prev) => {
      const next = new Set(prev)
      if (on) next.add(key)
      else next.delete(key)
      return next
    })
  }

  /** Animate the card out, then drop it and any sibling by the same band —
   *  curation excludes the whole band, so the live feed should match. */
  function retire(rec: Recommendation, kind: 'like' | 'block') {
    const key = keyOf(rec)
    setExiting((prev) => ({ ...prev, [key]: kind }))
    window.setTimeout(() => {
      setRows((prev) =>
        prev.filter((r) =>
          rec.band_id !== null ? r.band_id !== rec.band_id : keyOf(r) !== key,
        ),
      )
      setExiting((prev) => {
        const next = { ...prev }
        delete next[key]
        return next
      })
      setTotal((t) => (t === null ? t : Math.max(0, t - 1)))
    }, CARD_EXIT_MS)
  }

  async function like(rec: Recommendation) {
    const key = keyOf(rec)
    if (busyKeys.has(key)) return
    markBusy(key, true)
    try {
      const ref = rec.album_id !== null ? { album_id: rec.album_id } : { track_id: rec.track_id! }
      await api.like(ref)
      retire(rec, 'like')
      await Promise.all([loadLiked(), loadFacets()])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save that like.')
    } finally {
      markBusy(key, false)
    }
  }

  async function block(rec: Recommendation) {
    const key = keyOf(rec)
    if (rec.band_id === null || busyKeys.has(key)) return
    markBusy(key, true)
    try {
      await api.block(rec.band_id)
      retire(rec, 'block')
      await Promise.all([loadBlocked(), loadFacets()])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not block that artist.')
    } finally {
      markBusy(key, false)
    }
  }

  async function unlike(item: Liked) {
    const ref = item.album_id !== null ? { album_id: item.album_id } : { track_id: item.track_id! }
    await api.unlike(ref)
    await Promise.all([loadLiked(), loadFirstPage()])
  }

  async function unblock(bandId: number) {
    await api.unblock(bandId)
    await Promise.all([loadBlocked(), loadFirstPage()])
  }

  // ── render ───────────────────────────────────────────────────────────────
  const kindWord = filters.itemType
    ? filters.itemType === 'album'
      ? 'albums'
      : 'tracks'
    : 'results'

  if (scanId === null) {
    return (
      <div className="wrap feedpage">
        <nav className="feednav">
          <Link to="/scans" className="back">
            ← Scans
          </Link>
        </nav>
        <p className="empty">That isn&rsquo;t a valid scan address.</p>
      </div>
    )
  }

  return (
    <div className="wrap feedpage">
      <nav className="feednav">
        <Link to="/scans" className="back">
          ← Scans
        </Link>
        <h1 className="scantitle">
          {scan?.name ?? 'Loading…'}
          {scan && <span className="ktag">{scan.kind}</span>}
        </h1>
      </nav>

      {scan && scan.status !== 'done' && (
        <div className={`banner ${scan.status}`}>
          <span aria-hidden="true">{scan.status === 'error' ? '⚠' : '◴'}</span>
          <span>
            {scan.status === 'queued' &&
              'Queued — waiting for the crawl worker to pick this up.'}
            {scan.status === 'running' && 'Running — crawling seeds now…'}
            {scan.status === 'error' && `Scan failed: ${scan.error ?? 'unknown error'}`}
            {scan.status === 'draft' && 'Draft — not queued yet.'}
          </span>
        </div>
      )}

      {ready && (
        <>
          <FilterBar
            filters={filters}
            facetTags={facetTags}
            likedCount={liked.length}
            blockedCount={blocked.length}
            panel={panel}
            onTogglePanel={(p) => setPanel((cur) => (cur === p ? null : p))}
          />

          {panel === 'liked' && <LikedPanel items={liked} onUnlike={(i) => void unlike(i)} />}
          {panel === 'blocked' && (
            <BlockedPanel items={blocked} onUnblock={(id) => void unblock(id)} />
          )}

          <main>
            {total !== null && (
              <p className="countline">
                <b className="num">{count(total)}</b> {kindWord}
                {filters.anyActive ? ' match your filters' : ''}
              </p>
            )}

            {error && <p className="err">{error}</p>}

            {rows.map((r) => {
              const key = keyOf(r)
              return (
                <FeedCard
                  key={key}
                  rec={r}
                  exiting={exiting[key] ?? null}
                  busy={busyKeys.has(key)}
                  onLike={() => void like(r)}
                  onBlock={() => void block(r)}
                  onTagClick={(t) => filters.includeTag(t)}
                  onBandClick={() =>
                    r.band_id !== null &&
                    filters.setLabel({ id: r.band_id, name: r.band_name ?? 'unknown' })
                  }
                />
              )
            })}

            {rows.length === 0 && !loading && !error && (
              <p className="empty">
                {filters.anyActive
                  ? 'Nothing matches these filters — try clearing one.'
                  : 'No recommendations in this scan yet.'}
              </p>
            )}

            {!done && rows.length > 0 && (
              <button type="button" className="btn ghost more" onClick={loadMore} disabled={loading}>
                {loading ? 'Loading…' : `Load ${plural(LIMIT, 'more')}`}
              </button>
            )}
          </main>
        </>
      )}
    </div>
  )
}
