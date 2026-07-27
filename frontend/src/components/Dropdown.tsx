import { useEffect, useRef, useState, type ReactNode } from 'react'

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
        <div className="ddpanel" style={width ? { width } : undefined}>
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  )
}
