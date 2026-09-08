import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import { isDuplicateScanName } from '../lib/format'
import { deleteView, listViews, saveView, type SavedView } from '../lib/savedViews'
import { Dropdown } from './Dropdown'
import { RemoveButton } from './RemoveButton'

/** Same window `DeleteScanButton`/`BulkActionBar` use for the identical
 *  arm-then-confirm shape, applied here per-row instead of to one button. */
const CONFIRM_WINDOW_MS = 4000

/** Saves the current filter/sort combination (already fully expressed in the
 *  URL by `useFeedFilters`) under a name, and offers a list of previously
 *  saved ones to jump back to. Storage is per-scan `localStorage`
 *  (`lib/savedViews.ts`), not server-side — there's nothing to sync, just a
 *  personal shortcut back to a combination someone checks repeatedly. */
export function SavedViewsDropdown({ scanId }: { scanId: number }) {
  const location = useLocation()
  const navigate = useNavigate()
  const [views, setViews] = useState<SavedView[]>([])
  const [name, setName] = useState('')
  const duplicateName = isDuplicateScanName(
    name,
    views.map((v) => v.name),
  )
  /** Which saved view's remove button is armed, awaiting a second click —
   *  same "first click arms, second confirms, or it reverts on its own"
   *  pattern as `DeleteScanButton`/`BulkActionBar`, keyed per-row here since
   *  this is a list rather than one button. Deleting a saved view is
   *  permanent (no undo, unlike like/block), so a stray click shouldn't be
   *  enough on its own. */
  const [confirmingId, setConfirmingId] = useState<string | null>(null)
  const revertTimer = useRef<number | null>(null)

  useEffect(() => {
    return () => {
      if (revertTimer.current !== null) window.clearTimeout(revertTimer.current)
    }
  }, [])

  const arm = (id: string) => {
    if (revertTimer.current !== null) window.clearTimeout(revertTimer.current)
    setConfirmingId(id)
    revertTimer.current = window.setTimeout(() => setConfirmingId(null), CONFIRM_WINDOW_MS)
  }

  const confirmDelete = (id: string) => {
    if (revertTimer.current !== null) window.clearTimeout(revertTimer.current)
    setConfirmingId(null)
    setViews(deleteView(scanId, id))
  }

  return (
    <Dropdown
      label={views.length ? `Views (${views.length}) ▾` : '☆ Views'}
      onOpen={() => {
        setViews(listViews(scanId))
        setName('')
        if (revertTimer.current !== null) window.clearTimeout(revertTimer.current)
        setConfirmingId(null)
      }}
    >
      {(close) => (
        <div>
          <input
            className="ddsearch input"
            placeholder="Name this view — press Enter to save"
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key !== 'Enter') return
              const trimmed = name.trim()
              if (!trimmed) return
              e.preventDefault()
              setViews(saveView(scanId, trimmed, location.search))
              setName('')
            }}
          />
          <p className="ddempty">Saves the current filters/sort under a name, just for you.</p>
          {duplicateName && (
            <p className="hint">A saved view named &ldquo;{name.trim()}&rdquo; already exists.</p>
          )}
          <div className="ddlist">
            {views.length === 0 ? (
              <p className="ddempty">No saved views yet.</p>
            ) : (
              views.map((v) => (
                <div className="ddviewrow" key={v.id}>
                  <button
                    type="button"
                    className="ddrow"
                    onClick={() => {
                      navigate(`${location.pathname}${v.search}`)
                      close()
                    }}
                  >
                    <span className="nm">{v.name}</span>
                  </button>
                  {confirmingId === v.id ? (
                    <button
                      type="button"
                      className="rm confirm"
                      aria-label={`Confirm delete saved view "${v.name}"`}
                      onClick={() => confirmDelete(v.id)}
                    >
                      Confirm?
                    </button>
                  ) : (
                    <RemoveButton
                      label={`Delete saved view "${v.name}"`}
                      onClick={() => arm(v.id)}
                    />
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </Dropdown>
  )
}
