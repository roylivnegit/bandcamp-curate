/** Feed row density, persisted across sessions so the choice sticks without a
 *  setting per scan. `localStorage` access is `try`-wrapped — same trade as
 *  the auth token in `api/client.ts` — so private mode / storage-disabled
 *  browsers just fall back to the default rather than throwing. */
export type Density = 'comfortable' | 'compact'

const KEY = 'crate-digger.density'
const DEFAULT_DENSITY: Density = 'comfortable'

export function getDensity(): Density {
  try {
    return localStorage.getItem(KEY) === 'compact' ? 'compact' : DEFAULT_DENSITY
  } catch {
    return DEFAULT_DENSITY
  }
}

export function setDensity(density: Density): void {
  try {
    localStorage.setItem(KEY, density)
  } catch {
    // Nothing to recover — the toggle still works for this render, it just
    // won't survive a reload.
  }
}
