import { useState } from 'react'

import { api } from '../api/client'
import type { ScanDetail } from '../api/types'
import { showToast } from '../lib/toast'

/** Re-queues a scan that ended in `status === 'error'` (e.g. the crawl
 *  budget ran out mid-collection, per `CLAUDE.md`) via the existing
 *  `POST /api/scans/{id}/run` endpoint. Previously the only recovery was
 *  deleting the scan and re-submitting its seeds by hand — and a
 *  `kind === 'collection'` scan's `DeleteScanButton` doesn't even render,
 *  so an errored collection scan had no recovery path in the UI at all. */
export function RetryScanButton({
  scanId,
  onRetried,
}: {
  scanId: number
  onRetried: (scan: ScanDetail) => void
}) {
  const [busy, setBusy] = useState(false)

  const retry = async () => {
    setBusy(true)
    try {
      onRetried(await api.runScan(scanId))
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Could not retry the scan.', 'alert')
    } finally {
      setBusy(false)
    }
  }

  return (
    <button type="button" className="btn ghost" onClick={() => void retry()} disabled={busy}>
      {busy ? 'Retrying…' : 'Retry scan'}
    </button>
  )
}
