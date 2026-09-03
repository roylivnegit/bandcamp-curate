import { useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react'

import './CommandPalette.css'

export interface CommandAction {
  id: string
  label: string
  hint?: string
  run: () => void
}

/** Module scope, not a per-keystroke literal — see `frontend/CLAUDE.md` rule 9. */
const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), ' +
  'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

/** A Ctrl/Cmd+K palette for jumping straight to a destination instead of
 *  clicking through nav. Reuses `ShortcutsHelp`'s focus-trap / restore-focus
 *  shape — the difference here is a filterable action list instead of a
 *  static one. `actions` is owned by the caller (a fresh array each render is
 *  fine, nothing here depends on its identity across renders); `onOpen` is
 *  the caller's hook to refresh whatever backs those actions — e.g. re-fetch
 *  the scan list — each time the palette opens. It's a real effect dependency
 *  (fires again if it changes while open), so pass a `useCallback`'d
 *  function, not an inline arrow, or it'll reset the search on every
 *  unrelated re-render of whatever mounts this. */
export function CommandPalette({
  actions,
  onOpen,
}: {
  actions: CommandAction[]
  onOpen?: () => void
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [activeIndex, setActiveIndex] = useState(0)
  const previouslyFocused = useRef<HTMLElement | null>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

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

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return actions
    return actions.filter((a) => a.label.toLowerCase().includes(q))
  }, [actions, query])

  // Typing narrows `filtered` on every keystroke, so the highlighted row has
  // to stay in range rather than pointing past the end of a shorter list.
  const activeRow = activeIndex >= 0 && activeIndex < filtered.length ? filtered[activeIndex] : null

  // Arrow-key nav moves `activeIndex` (and the `.active` class/aria-activedescendant
  // that follow it) but does nothing to the scroll position on its own — on a
  // filtered list longer than the visible `.cmdk-list`, arrowing past the
  // visible rows would otherwise highlight an option the user can't see.
  useEffect(() => {
    if (!open || !activeRow) return
    document.getElementById(`cmdk-opt-${activeRow.id}`)?.scrollIntoView?.({ block: 'nearest' })
  }, [open, activeRow])

  useEffect(() => {
    if (!open) return
    previouslyFocused.current = document.activeElement as HTMLElement | null
    setQuery('')
    setActiveIndex(0)
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
      setActiveIndex((i) => Math.min(i + 1, filtered.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIndex((i) => Math.max(i - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (activeRow) runAction(activeRow)
    }
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
          aria-label="Jump to…"
          aria-controls="cmdk-list"
          aria-activedescendant={activeRow ? `cmdk-opt-${activeRow.id}` : undefined}
          placeholder="Jump to…"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value)
            setActiveIndex(0)
          }}
          onKeyDown={onInputKeyDown}
        />
        <div id="cmdk-list" role="listbox" aria-label="Actions" className="cmdk-list">
          {filtered.length === 0 ? (
            <p className="cmdk-empty">No matches.</p>
          ) : (
            filtered.map((a, i) => (
              <button
                key={a.id}
                id={`cmdk-opt-${a.id}`}
                type="button"
                role="option"
                aria-selected={a === activeRow}
                className={`cmdk-row${a === activeRow ? ' active' : ''}`}
                onMouseEnter={() => setActiveIndex(i)}
                onClick={() => runAction(a)}
              >
                <span className="cmdk-label">{a.label}</span>
                {/* aria-hidden: the label alone is the option's accessible
                    name. Without this, the hint's text runs straight into
                    the label with no separating space — "Psy digscan" — since
                    accessible-name computation concatenates text content and
                    ignores flex layout spacing. */}
                {a.hint && (
                  <span className="cmdk-hint" aria-hidden="true">
                    {a.hint}
                  </span>
                )}
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
