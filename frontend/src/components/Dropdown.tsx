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

  useEffect(() => {
    if (!open) return
    function onDocClick(e: MouseEvent) {
      if (!root.current?.contains(e.target as Node)) setOpen(false)
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDocClick)
      document.removeEventListener('keydown', onKey)
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
