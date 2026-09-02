import { useEffect, useRef, useState } from 'react'

import './ShortcutsHelp.css'

const SHORTCUTS: Array<{ keys: string; description: string }> = [
  { keys: 'l', description: 'Like the focused recommendation' },
  { keys: 'b', description: "Block the focused recommendation's artist" },
  { keys: '↑ / ↓', description: 'Move through an open menu' },
  { keys: 'Home / End', description: 'Jump to the first / last row in an open menu' },
  { keys: '?', description: 'Toggle this panel' },
]

function isTextEntryTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable
}

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
      if (e.key === 'Escape') setOpen(false)
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
