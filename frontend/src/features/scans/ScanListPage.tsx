import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import { api } from '../../api/client'
import type { Scan } from '../../api/types'
import { useAuth } from '../../auth/context'
import { ago, count, plural } from '../../lib/format'
import { NewScanForm } from './NewScanForm'
import './scans.css'

const POLL_MS = 4000

export function ScanListPage() {
  const { me, refresh } = useAuth()
  const [scans, setScans] = useState<Scan[] | null>(null)
  const [error, setError] = useState('')
  const [creating, setCreating] = useState(false)
  const timer = useRef<number | undefined>(undefined)

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
    timer.current = window.setTimeout(async () => {
      await load()
      await refresh()
    }, POLL_MS)
    return () => window.clearTimeout(timer.current)
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
        <h2 className="eyebrow">Your scans</h2>
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

      {error && <p className="err">{error}</p>}

      {scans === null && !error && <p className="empty">Loading scans…</p>}

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
      {scan.stats?.credits ? (
        <>
          {' '}
          <span className="sep">·</span> <span className="num">{scan.stats.credits}</span> credits
        </>
      ) : null}
      {scan.last_run_at ? (
        <>
          {' '}
          <span className="sep">·</span> {ago(scan.last_run_at)}
        </>
      ) : null}
    </>
  )
}
