import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from 'react'

import './Dropdown.css'

/** A button that toggles a popover, closing on outside-click or Escape.
 *  The old UI wired this by hand three times over; here it's one primitive. */
export function Dropdown({
  label,
  active = false,
  width,
  children,
  onOpen,
}: {
  label: ReactNode
  /** Renders the trigger in its "has a selection" state. */
  active?: boolean
  width?: number
  /** Called each time the panel opens — used to seed pending state. */
  onOpen?: () => void
  children: (close: () => void) => ReactNode
}) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    const trigger = triggerRef.current

    // Move focus into the panel so the arrow-key nav below works immediately,
    // unless something inside already grabbed it — the Genre/Contains panels'
    // own `autoFocus` search input, which React focuses during commit, before
    // this (passive) effect runs.
    if (!panelRef.current?.contains(document.activeElement)) {
      panelRef.current?.querySelector<HTMLButtonElement>('.ddrow')?.focus()
    }

    // Escape (no natural focus target) and selecting a row (the render prop's
    // `close()`) both restore focus to the trigger. An outside click is left
    // alone — the click itself already moved focus (or didn't) to whatever
    // was clicked, and forcing it back to the trigger would fight that.
    let restoreFocus = true
    function onDocClick(e: MouseEvent) {
      if (!root.current?.contains(e.target as Node)) {
        restoreFocus = false
        setOpen(false)
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDocClick)
      document.removeEventListener('keydown', onKey)
      if (restoreFocus) trigger?.focus()
    }
  }, [open])

  /* Arrow-key nav among the panel's `.ddrow` buttons (the WAI-ARIA menu-button
   * pattern's core behavior). Scoped to when a row itself already has focus —
   * the Genre/Contains panels also hold a text input, and hijacking Home/End
   * there would break normal cursor movement inside it. */
  function onPanelKeyDown(e: ReactKeyboardEvent<HTMLDivElement>) {
    const target = e.target as HTMLElement
    if (!target.classList.contains('ddrow')) return
    const rows = Array.from(e.currentTarget.querySelectorAll<HTMLButtonElement>('.ddrow'))
    const idx = rows.indexOf(target as HTMLButtonElement)
    if (idx === -1) return
    let next: number
    if (e.key === 'ArrowDown') next = (idx + 1) % rows.length
    else if (e.key === 'ArrowUp') next = (idx - 1 + rows.length) % rows.length
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = rows.length - 1
    else return
    e.preventDefault()
    rows[next].focus()
  }

  return (
    <div className="dd" ref={root}>
      <button
        ref={triggerRef}
        type="button"
        className={`btn ghost${active ? ' on' : ''}`}
        aria-expanded={open}
        onClick={() => {
          const next = !open
          setOpen(next)
          if (next) onOpen?.()
        }}
      >
        {label}
      </button>
      {open && (
        <div
          ref={panelRef}
          className="ddpanel"
          style={width ? { width } : undefined}
          onKeyDown={onPanelKeyDown}
        >
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  )
}
