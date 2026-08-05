import { useState } from 'react'

import { api } from '../../api/client'
import { seedKind } from '../../lib/format'

export function NewScanForm({
  onCreated,
  onCancel,
}: {
  onCreated: () => void
  onCancel: () => void
}) {
  const [name, setName] = useState('')
  const [seedUrl, setSeedUrl] = useState('')
  const [seeds, setSeeds] = useState<string[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  function addSeed() {
    const u = seedUrl.trim()
    if (!u) return
    setSeeds((prev) => (prev.includes(u) ? prev : [...prev, u]))
    setSeedUrl('')
  }

  async function create() {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      await api.createScan({ name, seeds })
      onCreated()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create the scan.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="panel newscan">
      <p className="hint newscan-hint">
        Name it, then paste Bandcamp <b>album or track</b> URLs to seed discovery — any mix. Your
        Mac runs the crawl; recommendations come from those releases&rsquo; supporters.
      </p>

      <div className="field">
        <label className="label" htmlFor="scan-name">
          Scan name
        </label>
        <input
          id="scan-name"
          className="input"
          autoFocus
          placeholder="e.g. Deep forest psy dig"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>

      <div className="field">
        <label className="label" htmlFor="seed-url">
          Seed releases
        </label>
        <div className="seedadd">
          <input
            id="seed-url"
            className="input"
            // Matches the signup form's fan-url field: gets the URL keyboard on
            // mobile without `type="url"`, whose native validation would fight
            // the Enter-to-add handler below.
            inputMode="url"
            placeholder="Paste a Bandcamp album or track URL"
            value={seedUrl}
            onChange={(e) => setSeedUrl(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                addSeed()
              }
            }}
          />
          <button type="button" className="btn ghost" onClick={addSeed} disabled={!seedUrl.trim()}>
            Add
          </button>
        </div>
      </div>

      {seeds.length > 0 && (
        <ul className="seedlist">
          {seeds.map((u, i) => (
            <li className="seed" key={u}>
              <span className="stag">{seedKind(u)}</span>
              <span className="u">{u}</span>
              <button
                type="button"
                className="rm"
                aria-label={`Remove ${u}`}
                onClick={() => setSeeds((prev) => prev.filter((_, j) => j !== i))}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}

      {error && (
        <p className="err" role="alert">
          {error}
        </p>
      )}

      <div className="newscan-foot">
        <button type="button" className="btn ghost" onClick={onCancel}>
          Cancel
        </button>
        <button
          type="button"
          className="btn"
          onClick={create}
          disabled={busy || !name.trim() || seeds.length === 0}
        >
          {busy ? 'Creating…' : 'Create & queue'}
        </button>
      </div>
    </div>
  )
}
