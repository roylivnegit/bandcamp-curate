/** Tracks, per scan, the `recompute_generation` a reader last had loaded —
 *  so a fresh visit (a new tab, a return the next day) can say "this scan's
 *  feed changed since you were last here." This is a *different* signal
 *  from `ScanFeedPage`'s in-session reflow banner: that one only fires for a
 *  generation bump observed while the page is already open (a `useRef`, gone
 *  the moment the tab closes); this one survives across visits by persisting
 *  to `localStorage`. `try`-wrapped the same way `visited.ts`/`density.ts`
 *  are, so private mode / storage-disabled browsers just see "nothing
 *  changed" rather than throwing. */
const PREFIX = 'crate-digger.lastSeenGeneration:'

export function getLastSeenGeneration(scanId: number): number | null {
  try {
    const raw = localStorage.getItem(PREFIX + scanId)
    if (raw === null) return null
    const n = Number(raw)
    return Number.isFinite(n) ? n : null
  } catch {
    return null
  }
}

export function setLastSeenGeneration(scanId: number, generation: number): void {
  try {
    localStorage.setItem(PREFIX + scanId, String(generation))
  } catch {
    // Nothing to recover — the next visit just won't know what was "last seen".
  }
}

/** Pure comparator: true only when there's a real prior visit on record
 *  (`lastSeen !== null`) and the feed has genuinely moved on since — never
 *  true on a scan's first-ever visit, same "nothing to have changed from
 *  yet" rule `ScanFeedPage`'s in-session `generationChanged` already uses. */
export function isUpdatedSinceLastVisit(current: number | null, lastSeen: number | null): boolean {
  return current !== null && lastSeen !== null && current > lastSeen
}
