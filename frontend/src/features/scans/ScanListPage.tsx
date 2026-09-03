import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import { api } from '../../api/client'
import type { Scan } from '../../api/types'
import { useAuth } from '../../auth/context'
import { RelativeTime } from '../../components/RelativeTime'
import { count, plural } from '../../lib/format'
import { useDocumentTitle } from '../../lib/useDocumentTitle'
import { NewScanForm } from './NewScanForm'
import './scans.css'

import { SCAN_POLL_MS } from '../../config'

const SKELETON_KEYS = ['sk-0', 'sk-1', 'sk-2']

export function ScanListPage() {
  useDocumentTitle('Scans')
  const { me, refresh } = useAuth()
  const [scans, setScans] = useState<Scan[] | null>(null)
  const [error, setError] = useState('')
  const [creating, setCreating] = useState(false)
  const headingRef = useRef<HTMLHeadingElement>(null)

  // A keyboard/screen-reader user landing here from another route should land
  // on the page's own heading, not wherever focus happened to be (often an
  // element no longer in the DOM).
  useEffect(() => {
    headingRef.current?.focus()
  }, [])

  const load = useCallback(async () => {
    try {
      setScans(await api.listScans())
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load scans.')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  // Keep polling while any scan is mid-flight, so a crawl finishing on the Mac
  // shows up here without a manual refresh. Also refreshes `me`, since the
  // collection scan's status drives the onboarding banner.
  const active = scans?.some((s) => s.status === 'queued' || s.status === 'running') ?? false
  useEffect(() => {
    if (!active) return
    // Timer id in the closure, not a ref: StrictMode invokes this twice, and a
    // shared ref would hold only the second id — leaving the first timer running
    // past cleanup. `scans` in the deps is the re-arm signal (load() sets a fresh
    // array), not an unused dependency.
    const id = window.setTimeout(async () => {
      // Parallel: the scan list and `me` are independent reads, and `me` only
      // feeds the onboarding banner.
      await Promise.all([load(), refresh()])
    }, SCAN_POLL_MS)
    return () => window.clearTimeout(id)
  }, [active, scans, load, refresh])

  const onboarding = me && !me.has_crawled

  return (
    <div className="wrap">
      {onboarding && (
        <div className="banner queued onboarding">
          <span aria-hidden="true">◴</span>
          <span>
            We&rsquo;re still crawling <b>{me.bandcamp_fan_url}</b>. Your feed fills in once that
            finishes — it runs on the operator&rsquo;s machine, so it may take a while.
          </span>
        </div>
      )}

      <div className="scanhead">
        {/* h1, not h2: this is the page's own top-level heading and the header's
            wordmark isn't one, so an h2 here skipped a level. `.eyebrow` carries
            all the styling, so the look is unchanged. */}
        <h1 className="eyebrow" ref={headingRef} tabIndex={-1}>
          Your scans
        </h1>
        {!creating && (
          <button type="button" className="btn" onClick={() => setCreating(true)}>
            ＋ New scan
          </button>
        )}
      </div>

      {creating && (
        <NewScanForm
          onCancel={() => setCreating(false)}
          onCreated={() => {
            setCreating(false)
            void load()
          }}
        />
      )}

      {error && (
        <p className="err" role="alert">
          {error}{' '}
          <button type="button" className="btn ghost" onClick={() => void load()}>
            Retry
          </button>
        </p>
      )}

      {scans === null && !error && (
        <div className="cards" role="status" aria-label="Loading scans…">
          {SKELETON_KEYS.map((k) => (
            <ScanCardSkeleton key={k} />
          ))}
        </div>
      )}

      {scans && (
        <div className="cards">
          {scans.map((s) => (
            <ScanCard key={s.id} scan={s} />
          ))}
          {!creating && (
            <button type="button" className="newcard" onClick={() => setCreating(true)}>
              ＋ New scan from album/track URLs
            </button>
          )}
        </div>
      )}

      {scans?.length === 0 && !creating && (
        <p className="empty">No scans yet — create one from a few album or track URLs.</p>
      )}
    </div>
  )
}

function ScanCard({ scan }: { scan: Scan }) {
  const collection = scan.kind === 'collection'
  return (
    <Link to={`/scans/${scan.id}`} className={`scan ${scan.status}`}>
      <span className="ico" aria-hidden="true">
        {collection ? '◎' : '⌖'}
      </span>
      <span className="scan-body">
        <span className="scan-r1">
          <span className="scan-nm">{scan.name}</span>
          {collection && (
            <span className="scan-star" title="Seeded by your own collection">
              ★
            </span>
          )}
          <span className={`pill ${scan.status}`}>
            <span className="dot" />
            {scan.status}
          </span>
        </span>
        <span className="scan-meta">
          <ScanMeta scan={scan} />
        </span>
      </span>
    </Link>
  )
}

/** Shaped like a real `ScanCard`, so the list doesn't shift once scans load.
 *  Decorative only — the `role="status"` wrapper above carries the
 *  announcement. */
function ScanCardSkeleton() {
  return (
    <div className="scan skeleton" aria-hidden="true">
      <span className="ico sk sk-ico" />
      <span className="scan-body">
        <span className="scan-r1">
          <span className="sk sk-title" />
        </span>
        <span className="scan-meta">
          <span className="sk sk-band" />
        </span>
      </span>
    </div>
  )
}

function ScanMeta({ scan }: { scan: Scan }) {
  if (scan.status === 'error') {
    return <span className="errtext">{scan.error || 'failed'}</span>
  }
  if (scan.status === 'queued') {
    return (
      <>
        waiting for the crawl worker <span className="sep">·</span>{' '}
        <b className="num">{scan.seed_count}</b> {plural(scan.seed_count, 'seed')}
      </>
    )
  }
  if (scan.status === 'running') {
    return (
      <>
        crawling now <span className="sep">·</span> <b className="num">{scan.seed_count}</b>{' '}
        {plural(scan.seed_count, 'seed')}
      </>
    )
  }
  // done / draft
  return (
    <>
      <b className="num">{count(scan.rec_count)}</b> recs
      {scan.kind === 'collection' ? (
        <>
          {' '}
          <span className="sep">·</span> seeded by your collection
        </>
      ) : (
        <>
          {' '}
          <span className="sep">·</span> <b className="num">{scan.seed_count}</b>{' '}
          {plural(scan.seed_count, 'seed')}
        </>
      )}
      {scan.last_run_at ? (
        <>
          {' '}
          <span className="sep">·</span> <RelativeTime iso={scan.last_run_at} />
        </>
      ) : null}
    </>
  )
}
