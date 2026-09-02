import { useEffect, useRef, useState } from 'react'

import './ShortcutsHelp.css'

const SHORTCUTS: Array<{ keys: string; description: string }> = [
  { keys: 'l', description: 'Like the focused recommendation' },
  { keys: 'b', description: "Block the focused recommendation's artist" },
  { keys: '↑ / ↓', description: 'Move to the next/previous card, or through an open menu' },
  { keys: 'Home / End', description: 'Jump to the first / last card, or menu row' },
  { keys: '?', description: 'Toggle this panel' },
]

function isTextEntryTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable
}

/** Module scope, not a per-keystroke literal — see `frontend/CLAUDE.md` rule 9. */
const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), ' +
  'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

/** A "?"-triggered overlay documenting the feed's keyboard shortcuts (l/b,
 *  Dropdown arrow-key nav), which otherwise ship invisible — nothing else
 *  in the UI tells a reader they exist. */
export function ShortcutsHelp() {
  const [open, setOpen] = useState(false)
  const previouslyFocused = useRef<HTMLElement | null>(null)
  const panelRef = useRef<HTMLDivElement>(null)

  // Always listening (not just while open) so "?" can open the panel from
  // anywhere on the page — except while the reader is actually typing a
  // question mark into a genre-search or tag-contains field.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key !== '?' || e.ctrlKey || e.metaKey || e.altKey) return
      if (isTextEntryTarget(e.target)) return
      e.preventDefault()
      setOpen((o) => !o)
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [])

  useEffect(() => {
    if (!open) return
    previouslyFocused.current = document.activeElement as HTMLElement | null
    panelRef.current?.focus()

    function onDocMouseDown(e: MouseEvent) {
      if (!panelRef.current?.contains(e.target as Node)) setOpen(false)
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        setOpen(false)
        return
      }
      // Focus trap: Tab/Shift+Tab cycle within the panel instead of leaking
      // out into the page behind it. Queries fresh each press rather than
      // caching the list once, so it keeps working if the panel's content
      // ever grows beyond today's single Close button.
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
  }, [open])

  if (!open) return null

  return (
    <div className="shortcuts-backdrop">
      <div
        ref={panelRef}
        className="shortcuts-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="shortcuts-title"
        tabIndex={-1}
      >
        <div className="shortcuts-head">
          <h2 id="shortcuts-title">Keyboard shortcuts</h2>
          <button type="button" className="rm" aria-label="Close" onClick={() => setOpen(false)}>
            ✕
          </button>
        </div>
        <dl>
          {SHORTCUTS.map((s) => (
            <div className="shortcut-row" key={s.keys}>
              <dt>
                <kbd>{s.keys}</kbd>
              </dt>
              <dd>{s.description}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  )
}
