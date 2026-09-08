import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import { isDuplicateScanName } from '../lib/format'
import { deleteView, listViews, saveView, type SavedView } from '../lib/savedViews'
import { Dropdown } from './Dropdown'
import { RemoveButton } from './RemoveButton'

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

  return (
    <Dropdown
      label={views.length ? `Views (${views.length}) ▾` : '☆ Views'}
      onOpen={() => {
        setViews(listViews(scanId))
        setName('')
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
                  <RemoveButton
                    label={`Delete saved view "${v.name}"`}
                    onClick={() => setViews(deleteView(scanId, v.id))}
                  />
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </Dropdown>
  )
}
