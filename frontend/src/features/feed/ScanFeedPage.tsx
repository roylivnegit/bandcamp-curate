import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'

import { api } from '../../api/client'
import type { Blocked, Facet, Liked, Recommendation, ScanDetail, Stats } from '../../api/types'
import { BulkActionBar } from '../../components/BulkActionBar'
import { DeleteScanButton } from '../../components/DeleteScanButton'
import { ScrollTopButton } from '../../components/ScrollTopButton'
import { ShortcutsHelp } from '../../components/ShortcutsHelp'
import { CARD_EXIT_MS, FEED_PAGE_SIZE, SCAN_POLL_MS, TOAST_DURATION_MS, UNDO_WINDOW_MS } from '../../config'
import { count } from '../../lib/format'
import { matchesQuery } from '../../lib/quickFilter'
import { showToast } from '../../lib/toast'
import { useDocumentTitle } from '../../lib/useDocumentTitle'
import { useScanFinishedMarker } from '../../lib/useScanFinishedMarker'
import { EmptyState } from './EmptyState'
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

/** Same guard `ShortcutsHelp`/`CommandPalette` use for their own global
 *  shortcuts — "/" must not hijack focus while the reader is already typing
 *  a literal "/" into some other field. */
function isTextEntryTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable
}

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
  const { includeTag, setLabel, tags: activeTags, pruneTags } = filters
  /* Read imperatively inside `loadFacets` rather than as a dependency — a tag
   * toggle would otherwise re-create `loadFacets` and re-fire the effect that
   * calls it (below) on every filter click, not just on a scan/recompute
   * change. Same "ref for an imperative read, not a re-render trigger" shape
   * as `AuthContext`'s `meRef`. */
  const activeTagsRef = useRef(activeTags)
  useEffect(() => {
    activeTagsRef.current = activeTags
  }, [activeTags])

  const [scan, setScan] = useState<ScanDetail | null>(null)
  const justFinished = useScanFinishedMarker(scan?.status)
  useDocumentTitle(scan?.name ? (justFinished ? `✓ ${scan.name}` : scan.name) : scan?.name)
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
  /** A pure client-side view filter over the already-loaded `rows` — no API
   *  call, just narrows what's rendered so a specific title/artist can be
   *  found without scrolling a long page. `/` (see the effect below) focuses
   *  the input; the query itself never leaves this page. */
  const [quickQuery, setQuickQuery] = useState('')
  const quickFilterRef = useRef<HTMLInputElement>(null)
  /** Bulk-select mode: a set of card keys (see `keyOf`) chosen for a bulk
   *  action. Off by default; toggling it off also clears the selection so a
   *  stale set can't linger for the next time it's turned on. */
  const [selectMode, setSelectMode] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [bulkBusy, setBulkBusy] = useState(false)
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

  // "/" focuses the quick-filter input from anywhere on the page — the same
  // always-listening + text-entry-guard shape as ShortcutsHelp's "?".
  useEffect(() => {
    function onKeyDown(e: globalThis.KeyboardEvent) {
      if (e.key !== '/' || e.ctrlKey || e.metaKey || e.altKey) return
      if (isTextEntryTarget(e.target)) return
      e.preventDefault()
      quickFilterRef.current?.focus()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
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
    const data = await api.facets(scanId)
    setFacetTags(data.tags)
    // A tag the URL is filtering "by" (include mode) that no longer appears
    // anywhere in the scan's current recommendations (e.g. a recompute moved
    // it out) would otherwise silently keep matching nothing forever, with no
    // clue why — auto-drop it and say what was removed. An `exclude`-mode tag
    // absent from this same list is left alone: excluding something that
    // isn't there is a harmless no-op, not a stuck filter.
    const validTags = new Set(data.tags.map((t) => t.value))
    const stale = Object.entries(activeTagsRef.current)
      .filter(([tag, mode]) => mode === 'by' && !validTags.has(tag))
      .map(([tag]) => tag)
    if (stale.length > 0) {
      pruneTags(stale)
      const what = stale.length === 1 ? `the "${stale[0]}" filter` : `${stale.length} genre filters`
      showToast(`Removed ${what} — no longer in your recommendations.`, 'status')
    }
  }, [scanId, pruneTags])
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

  /* `loadMore` is a plain function (recreated every render, closing over the
   * current `rows`/`filters`), so the observer effect below reads it through
   * a ref rather than depending on it directly — otherwise every row append
   * would tear down and recreate the IntersectionObserver. */
  const loadMoreRef = useRef(loadMore)
  loadMoreRef.current = loadMore

  const loadMoreSentinelRef = useRef<HTMLDivElement | null>(null)

  // Auto-load-more: the sentinel sits after the last card, and a 600px
  // rootMargin fires the fetch well before the reader actually reaches the
  // bottom, so the next page is usually already there by the time they get
  // there. Stops observing once `done` — nothing left to fetch.
  //
  // Depends on `rows.length`, not just `done`: the sentinel only renders once
  // `rows.length > 0` (see the JSX below), so on the very first render — rows
  // still empty, `done` still false — the ref is null and there's nothing to
  // observe yet. Without this dependency the effect runs exactly once at that
  // moment and never again, so it never actually attaches to the sentinel
  // once real rows (and the sentinel) exist.
  useEffect(() => {
    if (done) return
    const el = loadMoreSentinelRef.current
    if (!el) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) void loadMoreRef.current()
      },
      { rootMargin: '600px 0px' },
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [done, rows.length])

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

  // A quick-filter query left over from a different scan's feed would be
  // confusing (and likely match nothing) once the reader lands on another
  // scan via the same route element.
  useEffect(() => {
    setQuickQuery('')
  }, [scanId])

  // Same reasoning as the quick-filter reset above: a bulk selection made on
  // one scan's feed would be meaningless (and reference rows that don't
  // exist) after navigating to another scan via the same route element.
  useEffect(() => {
    setSelectMode(false)
    setSelected(new Set())
  }, [scanId])

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
        showToast(err instanceof Error ? err.message : 'Could not save that like.', 'alert', TOAST_DURATION_MS, {
          label: 'Retry',
          onClick: () => void like(rec),
        })
      } finally {
        inFlight.current.delete(key)
        markBusy(key, null)
      }
    },
    [markBusy, retire, cancelRetire, loadLiked, loadFacets],
  )

  const block = useCallback(
    async (rec: Recommendation, expiresAt?: string | null) => {
      const key = keyOf(rec)
      if (rec.band_id === null || inFlight.current.has(key)) return
      inFlight.current.add(key)
      markBusy(key, 'block')
      retire(rec, 'block')
      try {
        await api.block(rec.band_id, expiresAt)
        await Promise.all([loadBlocked(), loadFacets()])
      } catch (err) {
        cancelRetire(rec)
        showToast(
          err instanceof Error ? err.message : 'Could not block that artist.',
          'alert',
          TOAST_DURATION_MS,
          { label: 'Retry', onClick: () => void block(rec, expiresAt) },
        )
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

  const toggleSelectMode = useCallback(() => {
    setSelectMode((prev) => {
      if (prev) setSelected(new Set())
      return !prev
    })
  }, [])

  const toggleSelect = useCallback((rec: Recommendation) => {
    const key = keyOf(rec)
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }, [])

  const cancelSelect = useCallback(() => {
    setSelected(new Set())
  }, [])

  /** Calls the existing per-card `block` handler once per selected row —
   *  same optimistic retire/undo/error handling as a single click, just
   *  fired in a batch. Clears the selection once every call has settled,
   *  regardless of outcome; `block` itself already reports any individual
   *  failure via `setError`. */
  const bulkBlock = useCallback(async () => {
    const targets = rows.filter((r) => selected.has(keyOf(r)))
    if (targets.length === 0) return
    setBulkBusy(true)
    try {
      await Promise.all(targets.map((r) => block(r)))
    } finally {
      setBulkBusy(false)
      setSelected(new Set())
      setSelectMode(false)
    }
  }, [rows, selected, block])

  // Purely a view filter over what's already loaded — no re-fetch, and the
  // query never reaches the API. An empty query is the identity filter, so
  // this is cheap to always run through rather than branching around it.
  const visibleRows = useMemo(
    () => (quickQuery.trim() ? rows.filter((r) => matchesQuery(r, quickQuery)) : rows),
    [rows, quickQuery],
  )

  // Only rows with a band can be selected at all — mirrors FeedCard's own
  // checkbox gate (`rec.band_id !== null`), so "select all" never tries to
  // select something that never had a checkbox to begin with.
  const selectableKeys = useMemo(
    () => visibleRows.filter((r) => r.band_id !== null).map(keyOf),
    [visibleRows],
  )

  /** Selects every currently-*visible* row (respecting the active quick
   *  filter/genre filters — never the full server-side result set). A
   *  second click, once everything selectable is already selected, clears
   *  the selection back to none — the common toggle shape, not a one-way
   *  action. */
  const selectAllLoaded = useCallback(() => {
    setSelected((prev) => {
      const allSelected = selectableKeys.length > 0 && selectableKeys.every((k) => prev.has(k))
      return allSelected ? new Set() : new Set(selectableKeys)
    })
  }, [selectableKeys])

  // Clamped at render time (not in an effect) so a like/block that removes the
  // currently-active row — one card fewer, no `loadFirstPage` involved — never
  // leaves `activeIndex` pointing past the end of the rendered set.
  const activeCardIndex = visibleRows.length === 0 ? 0 : Math.min(activeIndex, visibleRows.length - 1)

  /** Roving tabindex, the standard WAI-ARIA pattern: ArrowDown/ArrowUp move to
   *  the next/previous card, Home/End jump to the ends. Scoped to firing only
   *  when the event actually originates from a card's own `tabIndex` (checked
   *  via the `card` class), so it never hijacks arrow keys typed into a filter
   *  field elsewhere in the page — the same scoping `Dropdown.tsx` uses for
   *  its `.ddrow` rows. Moves over `visibleRows`, not `rows` — the quick
   *  filter can hide the currently-active card. */
  const onCardListKeyDown = useCallback(
    (e: KeyboardEvent<HTMLDivElement>) => {
      if (!(e.target instanceof HTMLElement) || !e.target.classList.contains('card')) return
      if (visibleRows.length === 0) return
      let next: number
      if (e.key === 'ArrowDown') next = Math.min(activeCardIndex + 1, visibleRows.length - 1)
      else if (e.key === 'ArrowUp') next = Math.max(activeCardIndex - 1, 0)
      else if (e.key === 'Home') next = 0
      else if (e.key === 'End') next = visibleRows.length - 1
      else return
      e.preventDefault()
      setActiveIndex(next)
      document.getElementById(cardIdOf(visibleRows[next]))?.focus()
    },
    [visibleRows, activeCardIndex],
  )

  /** Reverses the currently-offered undo: unlikes/unblocks server-side, then
   *  restores the card straight into local `rows` at the spot it was removed
   *  from. Deliberately does NOT call `loadFirstPage()` — refetching page 1 to
   *  bring back one card would reset pagination/scroll for every other row
   *  already on screen.
   *
   *  Takes an explicit `entry` (defaulting to the current `undo` state) so a
   *  failure's "Retry" action can pass the same `{rec, kind, index}` back in
   *  directly — by the time Retry is clicked, `undo` state has already been
   *  cleared below, so reading it again would just see `null`. */
  async function undoRetire(entry: typeof undo = undo) {
    if (!entry) return
    const { rec, kind, index } = entry
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
      showToast(err instanceof Error ? err.message : 'Could not undo that.', 'alert', TOAST_DURATION_MS, {
        label: 'Retry',
        onClick: () => void undoRetire(entry),
      })
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

  // The band is already excluded from the feed, so only the Blocked list
  // itself needs to reflect the fresh expiry — no `loadFirstPage`/`loadFacets`
  // round trip, unlike a fresh block/unblock.
  async function renew(bandId: number, expiresAt: string) {
    const key = blockedKeyOf(bandId)
    if (inFlight.current.has(key)) return
    inFlight.current.add(key)
    markPanelBusy(key, true)
    try {
      await api.block(bandId, expiresAt)
      await loadBlocked()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not renew that block.')
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
        {scan && <DeleteScanButton scanId={scan.id} scanName={scan.name} kind={scan.kind} />}
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
            quickQuery={quickQuery}
            onQuickQueryChange={setQuickQuery}
            quickFilterRef={quickFilterRef}
            selectMode={selectMode}
            onToggleSelectMode={toggleSelectMode}
            selectedCount={selected.size}
            selectableCount={selectableKeys.length}
            onSelectAll={selectAllLoaded}
          />

          <BulkActionBar
            count={selected.size}
            busy={bulkBusy}
            onBlock={() => void bulkBlock()}
            onCancel={cancelSelect}
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
              onRenew={(id, expiresAt) => void renew(id, expiresAt)}
              busy={(id) => blockedKeyOf(id) in panelBusy}
            />
          )}

          {/* Not a `<main>` — `App.tsx` already wraps every routed page in one
           *  shared `<main id="main-content">`, the skip link's target; a second
           *  nested landmark here would be invalid and confuse assistive tech. */}
          <div>
            {total !== null && (
              <p className="countline" role="status" aria-live="polite">
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
                index comparison, not a scan, so it's just as cheap. Maps
                `visibleRows`, not `rows` — the quick filter narrows what's
                rendered without re-fetching. */}
            {visibleRows.length > 0 && (
              <div className="cardlist" onKeyDown={onCardListKeyDown}>
                {visibleRows.map((r, i) => {
                  const key = keyOf(r)
                  return (
                    <FeedCard
                      key={key}
                      rec={r}
                      cardId={cardIdOf(r)}
                      active={i === activeCardIndex}
                      exiting={exiting[key] ?? null}
                      busyAction={busy[key] ?? null}
                      selectMode={selectMode}
                      selected={selected.has(key)}
                      onLike={like}
                      onBlock={block}
                      onTagClick={includeTag}
                      onBandClick={onBandClick}
                      onToggleSelect={toggleSelect}
                    />
                  )
                })}
                {/* Auto-load-more: no button. Skeletons are real grid items so
                    they slot in wherever the next row would go, rather than a
                    separate full-width block under a multi-column grid. */}
                {loading && SKELETON_KEYS.slice(0, 2).map((k) => <FeedCardSkeleton key={k} />)}
              </div>
            )}
            {/* The IntersectionObserver's target — full-width, zero-height,
                below the grid so it never affects card layout. */}
            {!done && rows.length > 0 && (
              <div
                ref={loadMoreSentinelRef}
                role="status"
                aria-label={loading ? 'Loading more…' : undefined}
              />
            )}

            {rows.length === 0 && !loading && !error && (
              <EmptyState
                anyActive={filters.anyActive}
                coldStart={stats?.cold_start}
                onClearFilters={filters.reset}
              />
            )}

            {/* Distinct from the true-empty message above: the server-side
                result set isn't empty, the quick filter just hides all of
                it — clearing it (not filters.reset(), which is unrelated) is
                the way out. */}
            {rows.length > 0 && visibleRows.length === 0 && !loading && !error && (
              <p className="empty">No loaded cards match “{quickQuery.trim()}”.</p>
            )}

          </div>
        </>
      )}
    </div>
  )
}
