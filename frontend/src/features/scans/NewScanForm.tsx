import { useState, type ClipboardEvent as ReactClipboardEvent } from 'react'

import { api } from '../../api/client'
import { RemoveButton } from '../../components/RemoveButton'
import { seedKind } from '../../lib/format'

// Mirrors the backend's own acceptance shape (`app.crawl.scan_service._SEED_RE`):
// any host, path starting /album/<slug> or /track/<slug>. Deliberately no
// bandcamp.com host check here — the API doesn't require one either, so this
// must not reject anything the API would accept.
const SEED_URL_RE = /^https?:\/\/[^/]+\/(album|track)\/[^/?#]+/i

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
    if (!SEED_URL_RE.test(u)) {
      setError('That doesn’t look like a Bandcamp album or track URL (e.g. https://artist.bandcamp.com/album/name).')
      return
    }
    setError('')
    setSeeds((prev) => (prev.includes(u) ? prev : [...prev, u]))
    setSeedUrl('')
  }

  // A single pasted line falls through to the default paste behavior (lands
  // in the input, same as typing) — only a multi-line paste (a batch of
  // copied tabs) is handled here, since that's the case Enter-to-add can't
  // cover at all. Invalid/duplicate lines are silently dropped, same as
  // `addSeed`'s own dedupe; only a paste with *no* valid lines surfaces an
  // error, mirroring the single-URL rejection message.
  function onSeedPaste(e: ReactClipboardEvent<HTMLInputElement>) {
    const text = e.clipboardData.getData('text')
    if (!/\r|\n/.test(text)) return
    e.preventDefault()
    const lines = text
      .split(/\r\n|\r|\n/)
      .map((l) => l.trim())
      .filter(Boolean)
    const valid = lines.filter((l) => SEED_URL_RE.test(l))
    if (valid.length === 0) {
      setError('None of the pasted lines looked like a Bandcamp album or track URL.')
      return
    }
    setError('')
    setSeeds((prev) => {
      const next = [...prev]
      for (const u of valid) if (!next.includes(u)) next.push(u)
      return next
    })
    setSeedUrl('')
  }

  async function create() {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      await api.createScan({ name: name.trim(), seeds })
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
            onPaste={onSeedPaste}
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
              <RemoveButton
                label={`Remove ${u}`}
                onClick={() => setSeeds((prev) => prev.filter((_, j) => j !== i))}
              />
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
