import { useCallback, useEffect, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'

import { api } from '../../api/client'
import type { Blocked, Facet, Liked, Recommendation, ScanDetail, Stats } from '../../api/types'
import { ScrollTopButton } from '../../components/ScrollTopButton'
import { ShortcutsHelp } from '../../components/ShortcutsHelp'
import { CARD_EXIT_MS, FEED_PAGE_SIZE, SCAN_POLL_MS, UNDO_WINDOW_MS } from '../../config'
import { count, plural } from '../../lib/format'
import { useDocumentTitle } from '../../lib/useDocumentTitle'
import { ColdStartPanel } from './ColdStartPanel'
import { FeedCard, FeedCardSkeleton } from './FeedCard'
import { FilterBar } from './FilterBar'
import { BlockedPanel, LikedPanel } from './SidePanels'
import { useFeedFilters } from './useFeedFilters'
import { useResumeScroll } from './useResumeScroll'
import './feed.css'

const LIMIT = FEED_PAGE_SIZE
const SKELETON_KEYS = ['sk-0', 'sk-1', 'sk-2', 'sk-3', 'sk-4']

/** Module scope, not a closure over render state — the like/block handlers stay
 *  referentially stable only if nothing they call is re-created per render. */
const keyOf = (r: Recommendation) => `${r.item_type}:${r.album_id ?? r.track_id}`
/** A DOM id derived from `keyOf`, so the roving-tabindex handler can find and
 *  focus one exact card by id after an Arrow/Home/End key. */
const cardIdOf = (r: Recommendation) => `card-${keyOf(r)}`
/** Keys for the Liked/Blocked side-panel rows' own in-flight tracking — a
 *  distinct namespace from `keyOf` above (prefixed, not item-type-shaped) so
 *  they can share `inFlight`/`panelBusy` with nothing to collide against. */
const likedKeyOf = (item: Liked) => `liked-${item.id}`
const blockedKeyOf = (bandId: number) => `blocked-${bandId}`

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
  const location = useLocation()
  const filters = useFeedFilters(scanId)
  /* Destructured so the handlers below can depend on the individual stable
   * callbacks. `filters` itself is a fresh object every render, so depending on
   * it would defeat the point. */
  const { includeTag, setLabel } = filters

  const [scan, setScan] = useState<ScanDetail | null>(null)
  useDocumentTitle(scan?.name)
  const [rows, setRows] = useState<Recommendation[]>([])
  const [total, setTotal] = useState<number | null>(null)
  const [facetTags, setFacetTags] = useState<Facet[]>([])
  const [stats, setStats] = useState<Stats | null>(null)
  const [liked, setLiked] = useState<Liked[]>([])
  const [blocked, setBlocked] = useState<Blocked[]>([])
  const [panel, setPanel] = useState<'liked' | 'blocked' | null>(null)
  const [exiting, setExiting] = useState<Record<string, 'like' | 'block'>>({})
  /** Which action, if any, is in flight for a card — mirrors `exiting`'s
   *  per-key/per-action shape so `FeedCard` can swap its acting button's
   *  label to "Liking…"/"Blocking…" instead of just going inert. */
  const [busy, setBusy] = useState<Record<string, 'like' | 'block'>>({})
  /** The Liked/Blocked side panels' own in-flight set (`likedKeyOf`/
   *  `blockedKeyOf` keys) — same guard/busy shape as `busy` above, kept
   *  separate since a panel row's identity (a liked item's id, a blocked
   *  band's id) isn't a feed-card key. The panels hold no state of their
   *  own; this is the single source of truth threaded down as a lookup. */
  const [panelBusy, setPanelBusy] = useState<Record<string, true>>({})
  /** Roving tabindex over the card list: an index into `rows`, not a scan
   *  each card would otherwise have to do to know whether it's "the active
   *  one" — every card's `active` prop is a single `i === activeIndex`
   *  comparison in the `rows.map` below. Reset to 0 whenever `loadFirstPage`
   *  lands a fresh set (a new filter, a new scan); clamped at render time in
   *  case a like/block removes the currently-active row. */
  const [activeIndex, setActiveIndex] = useState(0)
  const [loading, setLoading] = useState(false)
  const [done, setDone] = useState(false)
  const [error, setError] = useState('')
  const [listUpdated, setListUpdated] = useState(false)
  const headingRef = useRef<HTMLHeadingElement>(null)
  /** The most recently retired card, restorable with "Undo". `index` is where
   *  it sat in `rows` at the moment it was removed, so undo re-inserts it back
   *  in roughly the same spot rather than at an arbitrary end. */
  const [undo, setUndo] = useState<{ rec: Recommendation; kind: 'like' | 'block'; index: number } | null>(
    null,
  )
  /* Timer id in a ref, not state: only `armUndo`/`clearUndo` touch it and
   * neither needs to re-render when it changes. */
  const undoTimer = useRef<number | null>(null)

  /* Bumped by every first-page load. A response whose ticket no longer matches is
   * stale — the filters moved on while it was in flight — so it must not land.
   * Toggling two genre pills quickly is enough to make responses arrive out of
   * order, and the loser would otherwise overwrite the winner's rows. */
  const feedSeq = useRef(0)
  /* In-flight like/block keys. A ref, not state: this only guards re-entry, and
   * as state it would force the handlers to depend on it, un-memoizing every card
   * on each click. `busy` above is the render-visible half. */
  const inFlight = useRef<Set<string>>(new Set())
  /* `retire`'s pending exit-animation timeout ids, keyed by card key — lets a
   * failed optimistic like/block cancel the animation before it removes the
   * row, instead of removing-then-reinserting. A ref: purely bookkeeping for
   * `cancelRetire`, never rendered. */
  const retireTimers = useRef<Record<string, number>>({})
  /* The index a card was actually spliced out of `rows` at, recorded once
   * `retire`'s timeout fires. `cancelRetire` reads this (not `undo` state,
   * which can be stale in a closure captured before `armUndo` ran) to splice
   * a failed optimistic retirement back into roughly the same spot. */
  const retiredIndex = useRef<Record<string, number>>({})
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

  /* Resume-scroll key is the scan id plus the filter query string — the same
   * filters live in `location.search` (useFeedFilters/useSearchParams), so a
   * different filter set is just a different key rather than something this
   * page has to explicitly detect and clear. Gated on rows actually being on
   * screen, not just `showFeed`, so it never fires against an empty page. */
  const scrollStorageKey = scanId === null ? null : `crate-digger.feedScroll:${scanId}${location.search}`
  useResumeScroll(scrollStorageKey, showFeed && rows.length > 0)

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

  // Same route element serves every /scans/:scanId, so navigating between two
  // scans' feeds (Link, not a full reload) never unmounts this component — a
  // mount-only effect wouldn't refire. Keying on scanId re-focuses the
  // heading each time the reader actually lands on a different scan.
  useEffect(() => {
    headingRef.current?.focus()
  }, [scanId])

  // Shared by <ScrollTopButton>: scrolls back up and, like a route change,
  // hands focus to the page heading rather than leaving it wherever it was
  // (often a card no longer near the viewport).
  const scrollToTop = useCallback(() => {
    window.scrollTo({ top: 0, behavior: 'smooth' })
    headingRef.current?.focus()
  }, [])

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
  const loadStats = useCallback(async () => {
    if (scanId === null) return
    setStats(await api.stats(scanId))
  }, [scanId])

  useEffect(() => {
    void loadLiked().catch(() => {})
    void loadBlocked().catch(() => {})
  }, [loadLiked, loadBlocked])

  useEffect(() => {
    if (showFeed) void loadFacets().catch(() => {})
  }, [showFeed, loadFacets, recCount])

  // `total` (not `rows.length`) is the stable "the whole result set is empty"
  // signal — a like/block animates a row out of `rows` locally without ever
  // touching `total`, so this only fires for a genuinely empty scan, not a
  // momentary gap while the last visible card exits.
  useEffect(() => {
    if (total === 0) void loadStats().catch(() => {})
  }, [total, loadStats])

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
      setActiveIndex(0)
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
  const markBusy = useCallback((key: string, action: 'like' | 'block' | null) => {
    setBusy((prev) => {
      if (action === null) {
        if (!(key in prev)) return prev
        const next = { ...prev }
        delete next[key]
        return next
      }
      return { ...prev, [key]: action }
    })
  }, [])

  const markPanelBusy = useCallback((key: string, on: boolean) => {
    setPanelBusy((prev) => {
      if (!on) {
        if (!(key in prev)) return prev
        const next = { ...prev }
        delete next[key]
        return next
      }
      return { ...prev, [key]: true }
    })
  }, [])

  const clearUndoTimer = useCallback(() => {
    if (undoTimer.current !== null) {
      window.clearTimeout(undoTimer.current)
      undoTimer.current = null
    }
  }, [])

  /** Offers "Undo" on the just-retired card for `UNDO_WINDOW_MS`. Only one at
   *  a time — a second like/block replaces whatever undo was already up. */
  const armUndo = useCallback(
    (rec: Recommendation, kind: 'like' | 'block', index: number) => {
      clearUndoTimer()
      setUndo({ rec, kind, index })
      undoTimer.current = window.setTimeout(() => {
        undoTimer.current = null
        setUndo(null)
      }, UNDO_WINDOW_MS)
    },
    [clearUndoTimer],
  )

  // A stale undo banner pointing at a different scan's card would be
  // confusing (and its `index` meaningless) once the reader lands on another
  // scan via the same route element, so drop it on every scanId change —
  // which also covers unmount, via the returned cleanup.
  useEffect(() => {
    setUndo(null)
    return clearUndoTimer
  }, [scanId, clearUndoTimer])

  /** Animate the card out, then drop it and any sibling by the same band —
   *  curation excludes the whole band, so the live feed should match. Called
   *  optimistically, before the like/block request resolves — `cancelRetire`
   *  below is what undoes this if that request then fails. */
  const retire = useCallback(
    (rec: Recommendation, kind: 'like' | 'block') => {
      const key = keyOf(rec)
      setExiting((prev) => ({ ...prev, [key]: kind }))
      const timerId = window.setTimeout(() => {
        delete retireTimers.current[key]
        let removedAt = -1
        setRows((prev) => {
          const next: Recommendation[] = []
          prev.forEach((r, i) => {
            const matches = rec.band_id !== null ? r.band_id === rec.band_id : keyOf(r) === key
            if (matches) {
              if (removedAt === -1) removedAt = i
            } else {
              next.push(r)
            }
          })
          return next
        })
        retiredIndex.current[key] = removedAt
        setExiting((prev) => {
          const next = { ...prev }
          delete next[key]
          return next
        })
        setTotal((t) => (t === null ? t : Math.max(0, t - 1)))
        armUndo(rec, kind, removedAt)
      }, CARD_EXIT_MS)
      retireTimers.current[key] = timerId
    },
    [armUndo],
  )

  /** Reverts an optimistic `retire()` whose like/block request then failed.
   *  If the exit animation hadn't finished yet, this just cancels its timer —
   *  the row was never actually removed from `rows`. If it had already fired
   *  (the row is gone and "Undo" may already be armed for it), splice the row
   *  back in at the index it was removed from and drop that now-meaningless
   *  undo offer — there's nothing left to undo, the failure already reverted
   *  it. Deliberately does not touch facets/liked/blocked: those are only
   *  ever loaded after a *successful* like/block, so there is nothing on
   *  that side to roll back. */
  const cancelRetire = useCallback(
    (rec: Recommendation) => {
      const key = keyOf(rec)
      const timerId = retireTimers.current[key]
      if (timerId !== undefined) {
        window.clearTimeout(timerId)
        delete retireTimers.current[key]
        setExiting((prev) => {
          if (!(key in prev)) return prev
          const next = { ...prev }
          delete next[key]
          return next
        })
        return
      }
      const index = retiredIndex.current[key]
      delete retiredIndex.current[key]
      setUndo((prev) => {
        if (prev && keyOf(prev.rec) === key) {
          clearUndoTimer()
          return null
        }
        return prev
      })
      setRows((prev) => {
        if (prev.some((r) => keyOf(r) === key)) return prev
        const next = [...prev]
        next.splice(index === undefined || index === -1 ? next.length : Math.min(index, next.length), 0, rec)
        return next
      })
      setTotal((t) => (t === null ? t : t + 1))
    },
    [clearUndoTimer],
  )

  const like = useCallback(
    async (rec: Recommendation) => {
      const key = keyOf(rec)
      if (inFlight.current.has(key)) return
      inFlight.current.add(key)
      markBusy(key, 'like')
      // Optimistic: animate the card out right away rather than waiting on
      // the round trip, and only revert if the request actually fails.
      retire(rec, 'like')
      try {
        const ref = rec.album_id !== null ? { album_id: rec.album_id } : { track_id: rec.track_id! }
        await api.like(ref)
        await Promise.all([loadLiked(), loadFacets()])
      } catch (err) {
        cancelRetire(rec)
        setError(err instanceof Error ? err.message : 'Could not save that like.')
      } finally {
        inFlight.current.delete(key)
        markBusy(key, null)
      }
    },
    [markBusy, retire, cancelRetire, loadLiked, loadFacets],
  )

  const block = useCallback(
    async (rec: Recommendation) => {
      const key = keyOf(rec)
      if (rec.band_id === null || inFlight.current.has(key)) return
      inFlight.current.add(key)
      markBusy(key, 'block')
      retire(rec, 'block')
      try {
        await api.block(rec.band_id)
        await Promise.all([loadBlocked(), loadFacets()])
      } catch (err) {
        cancelRetire(rec)
        setError(err instanceof Error ? err.message : 'Could not block that artist.')
      } finally {
        inFlight.current.delete(key)
        markBusy(key, null)
      }
    },
    [markBusy, retire, cancelRetire, loadBlocked, loadFacets],
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

  // Clamped at render time (not in an effect) so a like/block that removes the
  // currently-active row — one card fewer, no `loadFirstPage` involved — never
  // leaves `activeIndex` pointing past the end of `rows`.
  const activeCardIndex = rows.length === 0 ? 0 : Math.min(activeIndex, rows.length - 1)

  /** Roving tabindex, the standard WAI-ARIA pattern: ArrowDown/ArrowUp move to
   *  the next/previous card, Home/End jump to the ends. Scoped to firing only
   *  when the event actually originates from a card's own `tabIndex` (checked
   *  via the `card` class), so it never hijacks arrow keys typed into a filter
   *  field elsewhere in the page — the same scoping `Dropdown.tsx` uses for
   *  its `.ddrow` rows. */
  const onCardListKeyDown = useCallback(
    (e: KeyboardEvent<HTMLDivElement>) => {
      if (!(e.target instanceof HTMLElement) || !e.target.classList.contains('card')) return
      if (rows.length === 0) return
      let next: number
      if (e.key === 'ArrowDown') next = Math.min(activeCardIndex + 1, rows.length - 1)
      else if (e.key === 'ArrowUp') next = Math.max(activeCardIndex - 1, 0)
      else if (e.key === 'Home') next = 0
      else if (e.key === 'End') next = rows.length - 1
      else return
      e.preventDefault()
      setActiveIndex(next)
      document.getElementById(cardIdOf(rows[next]))?.focus()
    },
    [rows, activeCardIndex],
  )

  /** Reverses the currently-offered undo: unlikes/unblocks server-side, then
   *  restores the card straight into local `rows` at the spot it was removed
   *  from. Deliberately does NOT call `loadFirstPage()` — refetching page 1 to
   *  bring back one card would reset pagination/scroll for every other row
   *  already on screen. */
  async function undoRetire() {
    if (!undo) return
    const { rec, kind, index } = undo
    clearUndoTimer()
    setUndo(null)
    try {
      if (kind === 'like') {
        const ref = rec.album_id !== null ? { album_id: rec.album_id } : { track_id: rec.track_id! }
        await api.unlike(ref)
        await loadLiked()
      } else if (rec.band_id !== null) {
        await api.unblock(rec.band_id)
        await loadBlocked()
      }
      setRows((prev) => {
        if (prev.some((r) => keyOf(r) === keyOf(rec))) return prev
        const next = [...prev]
        next.splice(index === -1 ? next.length : Math.min(index, next.length), 0, rec)
        return next
      })
      setTotal((t) => (t === null ? t : t + 1))
      await loadFacets()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not undo that.')
    }
  }

  async function unlike(item: Liked) {
    const key = likedKeyOf(item)
    if (inFlight.current.has(key)) return
    inFlight.current.add(key)
    markPanelBusy(key, true)
    try {
      const ref = item.album_id !== null ? { album_id: item.album_id } : { track_id: item.track_id! }
      await api.unlike(ref)
      await Promise.all([loadLiked(), loadFirstPage()])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not undo that like.')
    } finally {
      inFlight.current.delete(key)
      markPanelBusy(key, false)
    }
  }

  async function unblock(bandId: number) {
    const key = blockedKeyOf(bandId)
    if (inFlight.current.has(key)) return
    inFlight.current.add(key)
    markPanelBusy(key, true)
    try {
      await api.unblock(bandId)
      await Promise.all([loadBlocked(), loadFirstPage()])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not undo that block.')
    } finally {
      inFlight.current.delete(key)
      markPanelBusy(key, false)
    }
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
      <ShortcutsHelp />
      <ScrollTopButton onClick={scrollToTop} />
      <nav className="feednav">
        <Link to="/scans" className="back">
          ← Scans
        </Link>
        <h1 className="scantitle" ref={headingRef} tabIndex={-1}>
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
            rows={rows}
            likedCount={liked.length}
            blockedCount={blocked.length}
            panel={panel}
            onTogglePanel={(p) => setPanel((cur) => (cur === p ? null : p))}
          />

          {panel === 'liked' && (
            <LikedPanel
              items={liked}
              onUnlike={(i) => void unlike(i)}
              busy={(i) => likedKeyOf(i) in panelBusy}
            />
          )}
          {panel === 'blocked' && (
            <BlockedPanel
              items={blocked}
              onUnblock={(id) => void unblock(id)}
              busy={(id) => blockedKeyOf(id) in panelBusy}
            />
          )}

          {/* Not a `<main>` — `App.tsx` already wraps every routed page in one
           *  shared `<main id="main-content">`, the skip link's target; a second
           *  nested landmark here would be invalid and confuse assistive tech. */}
          <div>
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

            {undo && (
              <p className="banner undo" role="status">
                <span aria-hidden="true">{undo.kind === 'like' ? '♥' : '⊘'}</span>
                <span>
                  {undo.kind === 'like'
                    ? 'Added to your likes.'
                    : `Blocked ${undo.rec.band_name ?? 'that artist'}.`}
                </span>
                <button type="button" className="btn ghost" onClick={() => void undoRetire()}>
                  Undo
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
                re-renders when its own row or flags change. `active` is a single
                index comparison, not a scan, so it's just as cheap. */}
            {rows.length > 0 && (
              <div className="cardlist" onKeyDown={onCardListKeyDown}>
                {rows.map((r, i) => {
                  const key = keyOf(r)
                  return (
                    <FeedCard
                      key={key}
                      rec={r}
                      cardId={cardIdOf(r)}
                      active={i === activeCardIndex}
                      exiting={exiting[key] ?? null}
                      busyAction={busy[key] ?? null}
                      onLike={like}
                      onBlock={block}
                      onTagClick={includeTag}
                      onBandClick={onBandClick}
                    />
                  )
                })}
              </div>
            )}

            {rows.length === 0 && !loading && !error && (
              <>
                <p className="empty">
                  {filters.anyActive
                    ? 'Nothing matches these filters — try clearing one.'
                    : 'No recommendations in this scan yet.'}
                </p>
                {filters.anyActive && (
                  <button type="button" className="btn ghost" onClick={filters.reset}>
                    Clear filters
                  </button>
                )}
                {!filters.anyActive && <ColdStartPanel coldStart={stats?.cold_start} />}
              </>
            )}

            {!done && rows.length > 0 && (
              <button type="button" className="btn ghost more" onClick={loadMore} disabled={loading}>
                {loading ? 'Loading…' : `Load ${plural(LIMIT, 'more')}`}
              </button>
            )}
          </div>
        </>
      )}
    </div>
  )
}
