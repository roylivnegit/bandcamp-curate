import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { api } from '../../api/client'
import type { Blocked, Facet, Liked, Recommendation, ScanDetail } from '../../api/types'
import { CARD_EXIT_MS, FEED_PAGE_SIZE, SCAN_POLL_MS } from '../../config'
import { count, plural } from '../../lib/format'
import { FeedCard, FeedCardSkeleton } from './FeedCard'
import { FilterBar } from './FilterBar'
import { BlockedPanel, LikedPanel } from './SidePanels'
import { useFeedFilters } from './useFeedFilters'
import './feed.css'

const LIMIT = FEED_PAGE_SIZE
const SKELETON_KEYS = ['sk-0', 'sk-1', 'sk-2', 'sk-3', 'sk-4']

/** Module scope, not a closure over render state — the like/block handlers stay
 *  referentially stable only if nothing they call is re-created per render. */
const keyOf = (r: Recommendation) => `${r.item_type}:${r.album_id ?? r.track_id}`

/** True only for a genuine mid-session reflow — `prev` was a real generation
 *  (not the initial `null`) and it differs from `next`. A scan's very first
 *  observed generation must not itself count as a "reflow": there is nothing
 *  to reflow away from yet. */
const generationChanged = (prev: number | null, next: number | null): boolean =>
  prev !== null && next !== null && prev !== next

export function ScanFeedPage() {
  const { scanId: raw } = useParams()
  // A hand-typed or stale URL can put anything here. Number('abc') is NaN, which
  // would otherwise be sent as literal /api/scans/NaN.
  const parsed = Number(raw)
  const scanId = Number.isInteger(parsed) && parsed > 0 ? parsed : null
  const filters = useFeedFilters(scanId)
  /* Destructured so the handlers below can depend on the individual stable
   * callbacks. `filters` itself is a fresh object every render, so depending on
   * it would defeat the point. */
  const { includeTag, setLabel } = filters

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
  const [listUpdated, setListUpdated] = useState(false)

  /* Bumped by every first-page load. A response whose ticket no longer matches is
   * stale — the filters moved on while it was in flight — so it must not land.
   * Toggling two genre pills quickly is enough to make responses arrive out of
   * order, and the loser would otherwise overwrite the winner's rows. */
  const feedSeq = useRef(0)
  /* In-flight like/block keys. A ref, not state: this only guards re-entry, and
   * as state it would force the handlers to depend on it, un-memoizing every card
   * on each click. `busyKeys` below is the render-visible half. */
  const inFlight = useRef<Set<string>>(new Set())
  /* The generation the currently-rendered page was fetched under. A ref, not
   * state: it only feeds the reflow check below, never renders on its own. */
  const prevGeneration = useRef<number | null>(null)

  /* The feed no longer waits for the scan to finish. The backend re-curates after
   * every slice, so recommendations accrue while the crawl runs and there is no
   * reason to sit on them — a long scan used to show nothing for hours. Recomputes
   * are wholesale inside one transaction, so a fetch lands on a complete set.
   * `queued`/`draft` still show nothing, because nothing has been curated yet. */
  const showFeed = scan !== null && scan.status !== 'queued' && scan.status !== 'draft'
  /* Re-fetch when the count moves, rather than on every 4s poll tick: the scan
   * poll re-runs regardless, but the feed only changes when a slice curates. */
  const recCount = scan?.stats?.recommendations ?? 0
  /* The re-arm signal for `loadFirstPage` below — see `generationChanged`.
   * Bumped by every recompute, strictly more often than `recCount`: a swap
   * (one item in, one out) reorders the feed without moving the total. */
  const generation = scan?.recompute_generation ?? null

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
    // The id stays in the closure rather than a ref: under StrictMode's double
    // invoke, a shared ref holds only the second timer, so the cleanup leaks the
    // first one. `scan` in the deps is what re-arms the poll — loadScan sets a
    // fresh object, which re-runs this effect.
    const id = window.setTimeout(loadScan, SCAN_POLL_MS)
    return () => window.clearTimeout(id)
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
    if (showFeed) void loadFacets().catch(() => {})
  }, [showFeed, loadFacets, recCount])

  // ── the feed itself ──────────────────────────────────────────────────────
  const loadFirstPage = useCallback(async () => {
    const req = ++feedSeq.current
    setLoading(true)
    setError('')
    try {
      const [page, c] = await Promise.all([
        api.recommendations(filters.params, { sort: filters.sort, limit: LIMIT, offset: 0 }),
        api.recommendationsCount(filters.params),
      ])
      if (feedSeq.current !== req) return
      setRows(page)
      setTotal(c.count)
      setDone(page.length < LIMIT)
    } catch (err) {
      if (feedSeq.current !== req) return
      setError(err instanceof Error ? err.message : 'Could not load the feed.')
    } finally {
      if (feedSeq.current === req) setLoading(false)
    }
  }, [filters.params, filters.sort])

  useEffect(() => {
    if (!showFeed) return
    // A real change from the generation we last rendered (not the first one
    // ever observed) means a recompute reshuffled the feed underneath
    // whatever page the reader has scrolled to — surface the note, not just
    // silently reset. `recCount` alone missed this: a swap (one item in, one
    // out) bumps `generation` without moving the total.
    if (generationChanged(prevGeneration.current, generation)) setListUpdated(true)
    prevGeneration.current = generation
    void loadFirstPage()
    // `generation` is the re-arm signal: each slice curates, the poll picks up
    // the new value, and the feed refreshes. Not a stray dep — removing it
    // freezes the feed at whatever the first slice produced.
  }, [showFeed, loadFirstPage, generation])

  async function loadMore() {
    if (loading || done) return
    // Reads the current ticket without claiming one: if the filters change while
    // this page is in flight, these rows belong to the old query and are dropped
    // rather than appended to the new list.
    const req = feedSeq.current
    setLoading(true)
    try {
      const page = await api.recommendations(filters.params, {
        sort: filters.sort,
        limit: LIMIT,
        offset: rows.length,
      })
      if (feedSeq.current !== req) return
      setRows((prev) => [...prev, ...page])
      if (page.length < LIMIT) setDone(true)
    } catch (err) {
      if (feedSeq.current !== req) return
      setError(err instanceof Error ? err.message : 'Could not load more.')
    } finally {
      if (feedSeq.current === req) setLoading(false)
    }
  }

  // ── like / block ─────────────────────────────────────────────────────────
  /* Every handler below is dependency-free (functional setState + the in-flight
   * ref), so `FeedCard`'s memo actually holds across unrelated re-renders. */
  const markBusy = useCallback((key: string, on: boolean) => {
    setBusyKeys((prev) => {
      const next = new Set(prev)
      if (on) next.add(key)
      else next.delete(key)
      return next
    })
  }, [])

  /** Animate the card out, then drop it and any sibling by the same band —
   *  curation excludes the whole band, so the live feed should match. */
  const retire = useCallback((rec: Recommendation, kind: 'like' | 'block') => {
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
  }, [])

  const like = useCallback(
    async (rec: Recommendation) => {
      const key = keyOf(rec)
      if (inFlight.current.has(key)) return
      inFlight.current.add(key)
      markBusy(key, true)
      try {
        const ref = rec.album_id !== null ? { album_id: rec.album_id } : { track_id: rec.track_id! }
        await api.like(ref)
        retire(rec, 'like')
        await Promise.all([loadLiked(), loadFacets()])
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Could not save that like.')
      } finally {
        inFlight.current.delete(key)
        markBusy(key, false)
      }
    },
    [markBusy, retire, loadLiked, loadFacets],
  )

  const block = useCallback(
    async (rec: Recommendation) => {
      const key = keyOf(rec)
      if (rec.band_id === null || inFlight.current.has(key)) return
      inFlight.current.add(key)
      markBusy(key, true)
      try {
        await api.block(rec.band_id)
        retire(rec, 'block')
        await Promise.all([loadBlocked(), loadFacets()])
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Could not block that artist.')
      } finally {
        inFlight.current.delete(key)
        markBusy(key, false)
      }
    },
    [markBusy, retire, loadBlocked, loadFacets],
  )

  const onBandClick = useCallback(
    (rec: Recommendation) => {
      if (rec.band_id !== null) {
        setLabel({ id: rec.band_id, name: rec.band_name ?? 'unknown' })
      }
    },
    [setLabel],
  )

  const dismissListUpdated = useCallback(() => setListUpdated(false), [])

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
            {scan.status === 'running' &&
              (recCount > 0
                ? `Running — ${recCount} found so far, more on the way…`
                : 'Running — crawling seeds now…')}
            {scan.status === 'error' && `Scan failed: ${scan.error ?? 'unknown error'}`}
            {scan.status === 'draft' && 'Draft — not queued yet.'}
          </span>
        </div>
      )}

      {showFeed && (
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

            {error && (
        <p className="err" role="alert">
          {error}
        </p>
      )}

            {listUpdated && (
              <p className="banner reflow" role="status">
                <span aria-hidden="true">◎</span>
                <span>The list updated — showing the latest order.</span>
                <button type="button" className="rm" aria-label="Dismiss" onClick={dismissListUpdated}>
                  ✕
                </button>
              </p>
            )}

            {/* First page only (`rows.length === 0`) — `loadMore`'s `loading` shares
                this flag but has real rows already on screen, so it must not
                re-trigger the skeleton. Shaped like real cards so nothing shifts
                when they land. */}
            {loading && rows.length === 0 && !error && (
              <div role="status" aria-label="Loading recommendations…">
                {SKELETON_KEYS.map((k) => (
                  <FeedCardSkeleton key={k} />
                ))}
              </div>
            )}

            {/* Every prop here is either the row itself, a per-row primitive, or a
                stable callback — nothing is re-created per render, so a card only
                re-renders when its own row or flags change. */}
            {rows.map((r) => {
              const key = keyOf(r)
              return (
                <FeedCard
                  key={key}
                  rec={r}
                  exiting={exiting[key] ?? null}
                  busy={busyKeys.has(key)}
                  onLike={like}
                  onBlock={block}
                  onTagClick={includeTag}
                  onBandClick={onBandClick}
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
