import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api } from '../api/client'
import type { ScanKind } from '../api/types'
import { showToast } from '../lib/toast'

const CONFIRM_WINDOW_MS = 4000

/** `DELETE /api/scans/{id}` already refuses the `collection` scan (it's the
 *  one everything else is excluded against), so this renders nothing for one
 *  rather than duplicating that rule client-side and risking drift.
 *
 *  Two clicks, not a native `confirm()` — this app doesn't use those anywhere
 *  else. The first click arms a "Confirm delete?" state that reverts on its
 *  own after `CONFIRM_WINDOW_MS`, so a stray click can't delete a scan by
 *  itself; the second click is the real request. */
export function DeleteScanButton({
  scanId,
  scanName,
  kind,
}: {
  scanId: number
  scanName: string
  kind: ScanKind
}) {
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const navigate = useNavigate()
  const revertTimer = useRef<number | null>(null)

  useEffect(() => {
    return () => {
      if (revertTimer.current !== null) window.clearTimeout(revertTimer.current)
    }
  }, [])

  if (kind === 'collection') return null

  const arm = () => {
    setConfirming(true)
    revertTimer.current = window.setTimeout(() => setConfirming(false), CONFIRM_WINDOW_MS)
  }

  const cancel = () => {
    if (revertTimer.current !== null) window.clearTimeout(revertTimer.current)
    setConfirming(false)
  }

  const confirm = async () => {
    if (revertTimer.current !== null) window.clearTimeout(revertTimer.current)
    setBusy(true)
    try {
      await api.deleteScan(scanId)
      showToast(`Deleted "${scanName}".`, 'status')
      navigate('/scans')
    } catch (err) {
      setBusy(false)
      setConfirming(false)
      showToast(err instanceof Error ? err.message : 'Could not delete the scan.', 'alert')
    }
  }

  if (confirming) {
    return (
      <span className="delscan">
        <button type="button" className="btn ghost danger" onClick={() => void confirm()} disabled={busy}>
          {busy ? 'Deleting…' : 'Confirm delete?'}
        </button>
        <button type="button" className="btn ghost" onClick={cancel} disabled={busy}>
          Cancel
        </button>
      </span>
    )
  }

  return (
    <span className="delscan">
      <button
        type="button"
        className="btn ghost danger"
        aria-label={`Delete scan "${scanName}"`}
        onClick={arm}
      >
        Delete scan
      </button>
    </span>
  )
}
