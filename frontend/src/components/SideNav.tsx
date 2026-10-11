import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { NavLink, useLocation } from 'react-router-dom'

import { useAuth } from '../auth/context'
import './SideNav.css'

const NAV = [
  { to: '/scans', label: 'Scans', icon: '◎' },
  { to: '/collection', label: 'Collection', icon: '◈' },
] as const

/** Grace period before an unpinned panel closes. The trigger sits inside the
 *  58px header and the panel starts below it, so the pointer crosses a gap of
 *  a few pixels on its way down; closing on the first `mouseleave` made the
 *  panel impossible to reach without clicking. */
const CLOSE_GRACE_MS = 220

/** Navigation: a hamburger that opens a panel from the left edge. Hover to
 *  glance, click to pin. Hover is an enhancement only — the trigger is a real
 *  toggle, so keyboard and screen-reader users are not locked out. */
export function SideNav() {
  const { me, logout } = useAuth()
  const [pinned, setPinned] = useState(false)
  const [transient, setTransient] = useState(false)
  /* Set when a click closes the panel while the pointer is still on the
     trigger. Without it, hover would immediately reopen what the click just
     dismissed — clicking requires hovering, so the two fight. Cleared when
     the pointer leaves. */
  const [suppressed, setSuppressed] = useState(false)
  const open = !suppressed && (pinned || transient)
  const rootRef = useRef<HTMLDivElement>(null)
  const panelRef = useRef<HTMLElement>(null)
  const toggleRef = useRef<HTMLButtonElement>(null)
  const closeTimer = useRef<number | null>(null)
  const { pathname } = useLocation()

  /** The panel is portalled, so a DOM `contains` on the root alone misses it. */
  const isInside = (node: Node | null) =>
    Boolean(node && (rootRef.current?.contains(node) || panelRef.current?.contains(node)))

  const cancelClose = () => {
    if (closeTimer.current !== null) {
      window.clearTimeout(closeTimer.current)
      closeTimer.current = null
    }
  }

  const close = useCallback((restoreFocus = false) => {
    cancelClose()
    setPinned(false)
    setTransient(false)
    setSuppressed(false)
    // Escape and outside-click can remove the element that currently holds
    // focus, which would drop a keyboard user back to <body>.
    if (restoreFocus) toggleRef.current?.focus()
  }, [])

  /* Both flags clear together, in the timer. Clearing `suppressed` eagerly on
     mouseleave while only *scheduling* the `transient` clear flipped `open`
     back to true for one render: the panel re-mounted, replayed its entry
     animation, then closed 220ms later. Closing the menu and moving away made
     it flicker back. */
  const closeSoon = () => {
    cancelClose()
    closeTimer.current = window.setTimeout(() => {
      setTransient(false)
      setSuppressed(false)
    }, CLOSE_GRACE_MS)
  }

  useEffect(() => cancelClose, [])

  // A pinned panel must not survive a navigation it did not cause — the
  // command palette can change route with the panel still open over it.
  useEffect(() => {
    setPinned(false)
    setTransient(false)
  }, [pathname])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close(true)
    }
    const onDown = (e: MouseEvent) => {
      if (!isInside(e.target as Node)) close()
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onDown)
    }
  }, [open, close])

  /** Pin from the keyboard and focus follows into the panel, which is at the
   *  end of <body> and otherwise unreachable by Tab from the header. */
  const togglePinned = (e: React.MouseEvent<HTMLButtonElement>) => {
    // Keyed on `pinned`, not `open`: clicking requires hovering, and hovering
    // has already opened the panel transiently. Keying on `open` made the
    // FIRST click close what the hover had just shown.
    if (pinned) {
      setPinned(false)
      setSuppressed(true)
      return
    }
    setSuppressed(false)
    setPinned(true)
    if (e.detail === 0) {
      // detail === 0 means Enter/Space, not a real click.
      window.setTimeout(() => panelRef.current?.querySelector('a')?.focus(), 0)
    }
  }

  return (
    <div
      className="snav-root"
      ref={rootRef}
      onMouseEnter={() => {
        cancelClose()
        setTransient(true)
      }}
      onMouseLeave={closeSoon}
    >
      <button
        type="button"
        ref={toggleRef}
        className={`snav-toggle${open ? ' on' : ''}`}
        aria-expanded={open}
        aria-controls="snav-panel"
        onClick={togglePinned}
      >
        <span className="snav-bars" aria-hidden="true">
          <span />
          <span />
          <span />
        </span>
        <span className="sr-only">Menu</span>
      </button>

      {/* Portalled to <body>: `.apphead` sets `backdrop-filter`, which makes it
          the containing block for `position: fixed` descendants, so a panel
          rendered inside the header sized itself against the 58px bar. */}
      {open && createPortal(
        <nav
          className="snav-panel"
          id="snav-panel"
          aria-label="Main"
          ref={panelRef}
          onMouseEnter={cancelClose}
          onMouseLeave={closeSoon}
          onBlur={(e) => {
            if (!isInside(e.relatedTarget as Node)) setTransient(false)
          }}
        >
          <div className="snav-items">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                // `on`, not NavLink's default `active`: feed.css defines a
                // global `.active` for its filter-pill bar, which gave the
                // current row a stray top margin once that stylesheet loaded.
                className={({ isActive }) => `snav-row${isActive ? ' on' : ''}`}
                onClick={() => close()}
              >
                <span className="snav-ico" aria-hidden="true">
                  {item.icon}
                </span>
                <span className="snav-label">{item.label}</span>
              </NavLink>
            ))}
          </div>

          {me && (
            <div className="snav-foot">
              <div className="snav-who">
                <span className="snav-who-k">Signed in as</span>
                <b className="snav-who-v">{me.username}</b>
              </div>
              <button
                type="button"
                className="snav-row"
                onClick={() => {
                  close()
                  logout()
                }}
              >
                <span className="snav-ico" aria-hidden="true">
                  ⏻
                </span>
                <span className="snav-label">Sign out</span>
              </button>
            </div>
          )}
        </nav>,
        document.body,
      )}
    </div>
  )
}
