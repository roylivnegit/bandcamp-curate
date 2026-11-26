import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from 'react'

import { rankCommands } from '../lib/commandRank'
import { subscribeToCommandPalette } from '../lib/commandPalette'
import './CommandPalette.css'

export interface CommandAction {
  id: string
  label: string
  hint?: string
  /** Text only a screen reader gets, appended to the accessible name — for
   *  what the visible row conveys with a glyph. `hint` can't carry this: it's
   *  `aria-hidden` (see the note at its render site), and a row that leaves
   *  the tab it opens unannounced is the one case where that matters. */
  srHint?: string
  run: () => void
}

/** Module scope, not a per-keystroke literal — see `frontend/CLAUDE.md` rule 9. */
const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), ' +
  'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

/** Must match the server's own `MIN_QUERY_LEN` (`backend/app/api/search.py`):
 *  below it the API answers with an empty result, so asking is pure latency. */
const MIN_SEARCH_CHARS = 2

/** How long after the last keystroke before the search request goes out. The
 *  local navigation commands filter with no delay — they're already in memory
 *  — so this only paces the network half of the list. */
const SEARCH_DEBOUNCE_MS = 180

/** A Ctrl/Cmd+K palette: jump to a destination, and search everything the
 *  app knows about, from one box.
 *
 *  Reuses `ShortcutsHelp`'s focus-trap / restore-focus shape — the difference
 *  here is a filterable result list instead of a static one.
 *
 *  Two kinds of row, in one keyboard-navigable list:
 *
 *  - **`actions`** — the caller's navigation commands, filtered locally. Owned
 *    by the caller (a fresh array each render is fine, nothing here depends on
 *    its identity across renders).
 *  - **`onSearch`** — content matched by the server: scans, collection, feed.
 *    Called with the trimmed query, debounced, and only once it's at least
 *    `MIN_SEARCH_CHARS` long. Each call takes a ticket, so a slow response for
 *    "apx" can't land on top of the results for "aphex" (`frontend/CLAUDE.md`
 *    rule 4). Pass a `useCallback`'d function: it's a real effect dependency.
 *
 *  `onOpen` is the caller's hook to refresh whatever backs the local actions —
 *  e.g. re-fetch the scan list — each time the palette opens. Also a real
 *  dependency (it fires again if it changes while open), so `useCallback` that
 *  one too, or an unrelated re-render of whatever mounts this will reset the
 *  search.
 */
export function CommandPalette({
  actions,
  onOpen,
  onSearch,
}: {
  actions: CommandAction[]
  onOpen?: () => void
  onSearch?: (query: string) => Promise<CommandAction[]>
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [activeIndex, setActiveIndex] = useState(0)
  const [results, setResults] = useState<CommandAction[]>([])
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState('')
  const previouslyFocused = useRef<HTMLElement | null>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  /* Which search request's answer is still wanted. Bumped per request and read
   * back before each setState — a ref, not state, because nothing renders from
   * it (`frontend/CLAUDE.md` rule 3). */
  const searchSeq = useRef(0)

  // Always listening (not just while open), same as ShortcutsHelp's "?" —
  // Ctrl/Cmd+K isn't something anyone types into a text field, so unlike "?"
  // this needs no isTextEntryTarget guard.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key.toLowerCase() !== 'k' || !(e.ctrlKey || e.metaKey) || e.shiftKey || e.altKey) return
      e.preventDefault()
      setOpen((o) => !o)
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [])

  // The header's search button (and anything else that calls
  // `openCommandPalette`) — opens, never toggles: a button you can see is a
  // request to open the thing, not to close what your click can't see.
  useEffect(() => subscribeToCommandPalette(() => setOpen(true)), [])

  const filtered = useMemo(() => rankCommands(actions, query), [actions, query])

  /* One flat list so Arrow keys run straight through both kinds of row — the
   * grouping below is only how they're drawn. */
  const rows = useMemo(() => [...filtered, ...results], [filtered, results])

  // Typing narrows `rows` on every keystroke, so the highlighted row has to
  // stay in range rather than pointing past the end of a shorter list.
  const activeRow = activeIndex >= 0 && activeIndex < rows.length ? rows[activeIndex] : null

  // Arrow-key nav moves `activeIndex` (and the `.active` class/aria-activedescendant
  // that follow it) but does nothing to the scroll position on its own — on a
  // filtered list longer than the visible `.cmdk-list`, arrowing past the
  // visible rows would otherwise highlight an option the user can't see.
  useEffect(() => {
    if (!open || !activeRow) return
    document.getElementById(`cmdk-opt-${activeRow.id}`)?.scrollIntoView?.({ block: 'nearest' })
  }, [open, activeRow])

  useEffect(() => {
    if (!open || !onSearch) return
    const q = query.trim()
    if (q.length < MIN_SEARCH_CHARS) {
      // Bump the ticket as well as clearing: a response for the longer query
      // the user just backspaced out of is no longer wanted either.
      searchSeq.current += 1
      setResults([])
      setSearching(false)
      setSearchError('')
      return
    }
    const req = (searchSeq.current += 1)
    setSearching(true)
    // Timer in the effect closure, not a ref — StrictMode double-invokes
    // effects and a shared ref would leak the first timer (rule 7).
    const timer = window.setTimeout(() => {
      onSearch(q)
        .then((hits) => {
          if (searchSeq.current !== req) return
          setResults(hits)
          setSearchError('')
        })
        .catch(() => {
          if (searchSeq.current !== req) return
          setResults([])
          setSearchError("Couldn't search right now.")
        })
        .finally(() => {
          if (searchSeq.current === req) setSearching(false)
        })
    }, SEARCH_DEBOUNCE_MS)
    return () => window.clearTimeout(timer)
  }, [open, query, onSearch])

  useEffect(() => {
    if (!open) return
    previouslyFocused.current = document.activeElement as HTMLElement | null
    setQuery('')
    setActiveIndex(0)
    setResults([])
    setSearchError('')
    onOpen?.()
    inputRef.current?.focus()

    function onDocMouseDown(e: MouseEvent) {
      if (!panelRef.current?.contains(e.target as Node)) setOpen(false)
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        setOpen(false)
        return
      }
      // Focus trap, identical to ShortcutsHelp's: Tab/Shift+Tab cycle within
      // the panel instead of leaking out into the page behind it.
      if (e.key !== 'Tab') return
      const focusable = panelRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)
      if (!focusable || focusable.length === 0) return
      const list = Array.from(focusable)
      const first = list[0]
      const last = list[list.length - 1]
      const active = document.activeElement
      const atEdge = !(active instanceof HTMLElement) || !list.includes(active)
      if (e.shiftKey) {
        if (atEdge || active === first) {
          e.preventDefault()
          last.focus()
        }
      } else if (atEdge || active === last) {
        e.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('mousedown', onDocMouseDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onDocMouseDown)
      document.removeEventListener('keydown', onKeyDown)
      previouslyFocused.current?.focus()
      previouslyFocused.current = null
    }
  }, [open, onOpen])

  if (!open) return null

  function runAction(action: CommandAction) {
    action.run()
    setOpen(false)
  }

  function onInputKeyDown(e: ReactKeyboardEvent<HTMLInputElement>) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIndex((i) => Math.min(i + 1, rows.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIndex((i) => Math.max(i - 1, 0))
    } else if (e.key === 'Home') {
      // Clamp to the first row, same as ArrowUp's own bound — not Dropdown's
      // wrap-around menu convention, since this is a filtered result list
      // with a definite start/end, the same shape as the feed card list's nav.
      e.preventDefault()
      setActiveIndex(0)
    } else if (e.key === 'End') {
      e.preventDefault()
      setActiveIndex(rows.length - 1)
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (activeRow) runAction(activeRow)
    }
  }

  /* Group headings only earn their space when the list can hold two kinds of
   * row. Without `onSearch` this is the pure navigation palette it started as,
   * and labelling its one group tells the reader nothing. */
  const grouped = onSearch !== undefined

  /* `index` is passed in rather than looked up: `rows.indexOf` per row is
   * quadratic over a list that re-renders on every keystroke (rule 9), and the
   * caller already knows the offset. */
  function renderRow(action: CommandAction, index: number) {
    return (
      <button
        key={action.id}
        id={`cmdk-opt-${action.id}`}
        type="button"
        role="option"
        aria-selected={action === activeRow}
        className={`cmdk-row${action === activeRow ? ' active' : ''}`}
        onMouseEnter={() => setActiveIndex(index)}
        onClick={() => runAction(action)}
      >
        <span className="cmdk-label">{action.label}</span>
        {action.srHint ? <span className="sr-only">{action.srHint}</span> : null}
        {/* aria-hidden: the label alone is the option's accessible name.
            Without this, the hint's text runs straight into the label with no
            separating space — "Psy digscan" — since accessible-name
            computation concatenates text content and ignores flex layout
            spacing. */}
        {action.hint && (
          <span className="cmdk-hint" aria-hidden="true">
            {action.hint}
          </span>
        )}
      </button>
    )
  }

  return (
    <div className="cmdk-backdrop">
      <div
        ref={panelRef}
        className="cmdk-panel"
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
      >
        <input
          ref={inputRef}
          className="input cmdk-input"
          type="text"
          aria-label="Search"
          aria-controls="cmdk-list"
          aria-activedescendant={activeRow ? `cmdk-opt-${activeRow.id}` : undefined}
          placeholder={grouped ? 'Search scans, records, artists…' : 'Jump to…'}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value)
            setActiveIndex(0)
          }}
          onKeyDown={onInputKeyDown}
        />
        <div id="cmdk-list" role="listbox" aria-label="Results" className="cmdk-list">
          {filtered.length > 0 &&
            (grouped ? (
              <div role="group" aria-label="Pages">
                <p className="cmdk-group">Pages</p>
                {filtered.map(renderRow)}
              </div>
            ) : (
              filtered.map(renderRow)
            ))}
          {results.length > 0 && (
            <div role="group" aria-label="Your library">
              <p className="cmdk-group">Your library</p>
              {results.map((action, i) => renderRow(action, filtered.length + i))}
            </div>
          )}
          {/* A quiet note rather than an empty panel: the difference between
              "nothing matches" and "the answer hasn't arrived yet" is the
              difference between retyping and waiting. */}
          {searching && rows.length === 0 && <p className="cmdk-empty">Searching…</p>}
          {searchError && (
            <p className="cmdk-empty err" role="alert">
              {searchError}
            </p>
          )}
          {!searching && !searchError && rows.length === 0 && (
            <p className="cmdk-empty">No matches.</p>
          )}
        </div>
      </div>
    </div>
  )
}
