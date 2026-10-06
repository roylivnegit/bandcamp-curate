import { useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useNavigationType, useSearchParams } from 'react-router-dom'

import { api } from '../../api/client'
import type { CollectionResponse, CollectionSection } from '../../api/types'
import { useAuth } from '../../auth/context'
import { count, plural } from '../../lib/format'
import { showToast } from '../../lib/toast'
import { useDocumentTitle } from '../../lib/useDocumentTitle'
import {
  SECTIONS,
  SECTION_LABELS,
  matchesTerms,
  mergeCollection,
  searchTerms,
  type CollectionEntry,
} from '../../lib/collection'
import { CollectionRow, CollectionRowSkeleton } from './CollectionRow'
import './collection.css'

/** The tab names, as they appear in `?tab=`. 'all' is the default and the one
 *  that makes a single search box worthwhile. */
type Tab = 'all' | CollectionSection
const TABS: readonly Tab[] = ['all', ...SECTIONS]

const SKELETON_KEYS = ['sk-0', 'sk-1', 'sk-2', 'sk-3', 'sk-4']

const TAB = 'tab'
const QUERY = 'q'

/** How long to wait after the last keystroke before writing the search to the
 *  URL. Filtering does not wait for this — it runs off local state — so this
 *  only controls how quickly the address bar becomes shareable. */
const QUERY_URL_DEBOUNCE_MS = 200

/** How many rows to mount at once. The search still runs over everything. */
const ROWS_PER_PAGE = 100

function isTab(v: string | null): v is Tab {
  return v !== null && (TABS as readonly string[]).includes(v)
}

export function CollectionPage() {
  useDocumentTitle('Collection')
  const { me } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const location = useLocation()
  const navigationType = useNavigationType()
  const [data, setData] = useState<CollectionResponse | null>(null)
  const [error, setError] = useState('')
  const headingRef = useRef<HTMLHeadingElement>(null)

  // Tab and query live in the URL, not useState, so a filtered view can be
  // shared or bookmarked and browser-back restores it — the same shape
  // `useFeedFilters` uses for the feed's filters.
  const tabParam = searchParams.get(TAB)
  const tab: Tab = isTab(tabParam) ? tabParam : 'all'
  const urlQuery = searchParams.get(QUERY) ?? ''

  /* Local state owns the text, and the URL is caught up just behind it.
   * Binding `value` straight to `searchParams.get('q')` drops characters:
   * `setSearchParams` is an ordinary async update, so React resets the field to
   * a trailing value mid-word. Typing "bjork vespertine 10" left "0". */
  const [query, setQuery] = useState(urlQuery)

  /* Adopt the URL's query only on a POP — an actual back/forward. That is the
   * only case where the URL knows something the box does not: our own writes
   * are REPLACE, and a tab link is a PUSH that already carries the current
   * query.
   *
   * The earlier version used a boolean ref set around our own write, which had
   * to guess which navigation it was looking at and could consume the wrong one
   * when two debounced writes landed close together. Asking the router what
   * kind of navigation this was removes the guess, and the race with it. */
  useEffect(() => {
    if (navigationType !== 'POP') return
    setQuery(new URLSearchParams(location.search).get(QUERY) ?? '')
  }, [navigationType, location.key, location.search])

  // Catch the URL up, debounced. `replace`, so Back steps between tabs rather
  // than walking the search backwards one letter at a time.
  useEffect(() => {
    if (query === (new URLSearchParams(location.search).get(QUERY) ?? '')) return
    // Timer id in the effect closure, not a ref: StrictMode double-invokes
    // this, and a shared ref would hold only the second id.
    const id = window.setTimeout(() => {
      setSearchParams(
        (prev) => {
          const p = new URLSearchParams(prev)
          if (query) p.set(QUERY, query)
          else p.delete(QUERY)
          return p
        },
        { replace: true },
      )
    }, QUERY_URL_DEBOUNCE_MS)
    return () => window.clearTimeout(id)
  }, [query, location.search, setSearchParams])

  // A keyboard/screen-reader user arriving from another route should land on
  // this page's heading, same as ScanListPage/ScanFeedPage.
  useEffect(() => {
    headingRef.current?.focus()
  }, [])

  const load = useCallback(async () => {
    try {
      setData(await api.collection())
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load your collection.')
    }
  }, [])

  // One fetch, on mount. No stale-response ticket: unlike the feed there is
  // nothing to re-request — the tab and the search are pure views over the
  // single response, so no second request can ever race this one.
  useEffect(() => {
    void load()
  }, [load])

  /** Merged once per response: the three lists folded into one deduplicated,
   *  sorted array with a precomputed search haystack per row. Everything below
   *  is a view over this. */
  const entries = useMemo(() => (data ? mergeCollection(data) : null), [data])

  // Deferred so typing stays responsive on a few thousand rows: React keeps
  // painting the old list while the new filter is computed.
  const deferredQuery = useDeferredValue(query)
  const terms = useMemo(() => searchTerms(deferredQuery), [deferredQuery])

  const matching = useMemo(
    () => entries?.filter((e) => matchesTerms(e, terms)) ?? null,
    [entries, terms],
  )

  /** Badge numbers. With an empty query these are the section totals; with a
   *  query they are per-section match counts, which is the point of lifting
   *  the search above the tabs — you can see your record is in Wishlist
   *  without opening Wishlist. */
  const counts = useMemo(() => {
    const c: Record<Tab, number> = { all: 0, owned: 0, wishlist: 0, liked: 0 }
    for (const e of matching ?? []) {
      c.all += 1
      for (const s of e.sections) c[s] += 1
    }
    return c
  }, [matching])

  const rows = useMemo(
    () => matching?.filter((e) => tab === 'all' || e.sections.includes(tab)) ?? null,
    [matching, tab],
  )

  /* Filtering runs over the whole collection, but rendering does not. A large
   * collection is tens of thousands of items, and mounting a row component per
   * item locks the main thread for seconds on first paint — `content-visibility`
   * saves the paint, not the DOM construction or the reconciliation.
   *
   * So the list grows in pages, like the feed's "Load more". The counts above
   * still describe every match, not just what is rendered. */
  const [shownCount, setShownCount] = useState(ROWS_PER_PAGE)

  // Reset the window when the filter changes, adjusted during render rather
  // than in an effect (the pattern React documents for "state derived from a
  // prop change") — an effect would paint one frame of the old window first.
  const listKey = `${tab}|${deferredQuery}`
  const [prevListKey, setPrevListKey] = useState(listKey)
  if (prevListKey !== listKey) {
    setPrevListKey(listKey)
    setShownCount(ROWS_PER_PAGE)
  }

  const visibleRows = useMemo(() => rows?.slice(0, shownCount) ?? null, [rows, shownCount])
  const hiddenCount = (rows?.length ?? 0) - (visibleRows?.length ?? 0)

  // In-flight unlikes: the ref is the re-entry guard, the state is what
  // disables the button. Keeping both in state would put `busyKeys` in every
  // handler's dep list and un-memoize every row on each click.
  const inFlight = useRef<Set<string>>(new Set())
  const [busyKeys, setBusyKeys] = useState<Set<string>>(new Set())

  const markBusy = useCallback((key: string, on: boolean) => {
    setBusyKeys((prev) => {
      const next = new Set(prev)
      if (on) next.add(key)
      else next.delete(key)
      return next
    })
  }, [])

  const onArtistClick = useCallback(
    (entry: CollectionEntry) => setQuery(entry.band_name ?? ''),
    [setQuery],
  )

  /** Unliking drops the `liked` label. If that was the item's only label it
   *  leaves the collection entirely; if you also own it, the row stays and
   *  just loses the chip. Held locally until the next collection crawl
   *  confirms the real state on Bandcamp. */
  const onUnlike = useCallback(
    async (entry: CollectionEntry) => {
      if (inFlight.current.has(entry.key)) return
      const ref = entry.item_type === 'track'
        ? { track_id: entry.track_id as number }
        : { album_id: entry.album_id as number }
      inFlight.current.add(entry.key)
      markBusy(entry.key, true)
      try {
        await api.unlike(ref)
        setData((prev) =>
          prev === null
            ? prev
            : {
                ...prev,
                liked: prev.liked.filter(
                  (i) => !(i.item_type === entry.item_type
                    && i.album_id === entry.album_id
                    && i.track_id === entry.track_id),
                ),
              },
        )
        showToast(`Unliked ${entry.title || 'that item'}.`, 'status')
      } catch (err) {
        showToast(err instanceof Error ? err.message : 'Could not unlike that.', 'alert')
      } finally {
        inFlight.current.delete(entry.key)
        markBusy(entry.key, false)
      }
    },
    [markBusy],
  )

  const loading = entries === null && !error
  const searching = terms.length > 0
  const kindWord = tab === 'all' ? 'item' : SECTION_LABELS[tab].toLowerCase() + ' item'

  return (
    <div className="wrap collection">
      <h1 className="ctitle" tabIndex={-1} ref={headingRef}>
        Collection
      </h1>
      <p className="hint">
        Everything you already have — bought, wishlisted, or liked in a feed. One search covers all
        three.
      </p>

      <label className="label csearch-label" htmlFor="collection-search">
        Search your collection
      </label>
      <input
        id="collection-search"
        className="input csearch"
        type="search"
        placeholder="Artist or title…"
        autoComplete="off"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />

      <nav className="ctabs" aria-label="Collection sections">
        {TABS.map((t) => (
          <Link
            key={t}
            className={`ctab${t === tab ? ' active' : ''}`}
            aria-current={t === tab ? 'page' : undefined}
            // Plain links with aria-current rather than role="tab": a real ARIA
            // tablist owes the user arrow-key navigation and a single tab stop,
            // and a half-built one is worse than none. Links also give
            // browser-back between tabs for free.
            to={{
              search: new URLSearchParams(
                query ? { [TAB]: t, [QUERY]: query } : { [TAB]: t },
              ).toString(),
            }}
          >
            {t === 'all' ? 'All' : SECTION_LABELS[t]}{' '}
            <span className="num ctab-count">{count(counts[t])}</span>
          </Link>
        ))}
      </nav>

      {error && (
        <p className="err" role="alert">
          {error}
        </p>
      )}

      {data?.truncated === true && (
        <p className="banner warn">
          <span aria-hidden="true">⚠</span> Your collection is larger than this page can load, so
          the counts below are not totals and a search may miss something.
        </p>
      )}

      {/* Live region so a screen-reader user hears the list shrink as they
          type, rather than only discovering it by moving focus into the rows. */}
      {!error && (
        <p className="countline" role="status">
          {rows === null ? (
            'Loading your collection…'
          ) : (
            <>
              <b className="num">{count(rows.length)}</b> {plural(rows.length, kindWord)}
              {/* The verb has to agree with the count too, not just the noun:
                  "1 liked item match your search" reads as broken English. */}
              {searching ? (rows.length === 1 ? ' matches your search' : ' match your search') : ''}
            </>
          )}
        </p>
      )}

      {loading && SKELETON_KEYS.map((k) => <CollectionRowSkeleton key={k} />)}

      {rows !== null && rows.length === 0 && !error && (
        <p className="empty">
          {searching ? (
            'Nothing matches that search — the tab counts above show whether another section has it.'
          ) : /* Liked is checked BEFORE the crawl state: likes hang off the app user, not
                the Bandcamp fan, so an uncrawled user's Liked tab is already complete and
                the scan message would send them somewhere that cannot help. */
          tab === 'liked' ? (
            "You haven't liked anything in a feed yet."
          ) : me?.has_crawled === false ? (
            <>
              Your collection scan hasn&apos;t finished yet, so there&apos;s nothing to show.{' '}
              <Link to="/scans">Check its progress</Link>.
            </>
          ) : (
            'Nothing here yet.'
          )}
        </p>
      )}

      {visibleRows?.map((e) => (
        <CollectionRow
          key={e.key}
          entry={e}
          busy={busyKeys.has(e.key)}
          onArtistClick={onArtistClick}
          onUnlike={onUnlike}
        />
      ))}

      {hiddenCount > 0 && (
        <button
          type="button"
          className="btn ghost more"
          onClick={() => setShownCount((n) => n + ROWS_PER_PAGE)}
        >
          Show {count(Math.min(hiddenCount, ROWS_PER_PAGE))} more
          <span className="hint"> of {count(hiddenCount)} remaining</span>
        </button>
      )}
    </div>
  )
}
