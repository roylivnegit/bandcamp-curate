import { VISITED_CAP } from '../config'

/** Tracks which feed cards a reader has already clicked "Bandcamp ↗" on, so
 *  scrolling back through a long feed shows which ones were already checked
 *  out. `localStorage` access is `try`-wrapped — same trade as the auth token
 *  in `api/client.ts` — so private mode / storage-disabled browsers just fall
 *  back to "nothing is seen" rather than throwing. Capped at `VISITED_CAP`
 *  entries (oldest evicted first) so a long-lived account's storage entry
 *  can't grow without bound. */
const KEY = 'crate-digger.visited'

function readAll(): string[] {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.filter((k): k is string => typeof k === 'string') : []
  } catch {
    return []
  }
}

export function isVisited(key: string): boolean {
  return readAll().includes(key)
}

export function markVisited(key: string): void {
  try {
    const next = readAll().filter((k) => k !== key)
    next.push(key)
    if (next.length > VISITED_CAP) next.splice(0, next.length - VISITED_CAP)
    localStorage.setItem(KEY, JSON.stringify(next))
  } catch {
    // Nothing to recover — the card just won't be marked seen on a reload.
  }
}
