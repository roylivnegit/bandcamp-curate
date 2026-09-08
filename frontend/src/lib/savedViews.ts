import { SAVED_VIEWS_CAP } from '../config'

export interface SavedView {
  id: string
  name: string
  /** `location.search` (including the leading `?`, or `''` for no filters) —
   *  everything `useFeedFilters` needs to reconstruct the view is already
   *  encoded here, so "apply" is just a navigation, not a second decoder. */
  search: string
}

const KEY_PREFIX = 'crate-digger.savedViews:'

function storageKey(scanId: number): string {
  return `${KEY_PREFIX}${scanId}`
}

function isSavedView(v: unknown): v is SavedView {
  return (
    typeof v === 'object' &&
    v !== null &&
    typeof (v as SavedView).id === 'string' &&
    typeof (v as SavedView).name === 'string' &&
    typeof (v as SavedView).search === 'string'
  )
}

function read(scanId: number): SavedView[] {
  try {
    const raw = window.localStorage.getItem(storageKey(scanId))
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.filter(isSavedView) : []
  } catch {
    // Private mode / storage disabled / corrupted value: behave as "no saved views".
    return []
  }
}

function write(scanId: number, views: SavedView[]): void {
  try {
    window.localStorage.setItem(storageKey(scanId), JSON.stringify(views))
  } catch {
    // Non-fatal: the save just won't survive a reload.
  }
}

let seq = 0
function makeId(): string {
  seq += 1
  return `${Date.now()}-${seq}`
}

/** The current scan's saved views, oldest first. */
export function listViews(scanId: number): SavedView[] {
  return read(scanId)
}

/** Appends a view under `name`, evicting the oldest once the count would
 *  exceed `SAVED_VIEWS_CAP`. Returns the resulting list. */
export function saveView(scanId: number, name: string, search: string): SavedView[] {
  const next = [...read(scanId), { id: makeId(), name, search }]
  const capped = next.length > SAVED_VIEWS_CAP ? next.slice(next.length - SAVED_VIEWS_CAP) : next
  write(scanId, capped)
  return capped
}

/** Removes one view by id. Returns the resulting list; a no-op (same list
 *  back) if the id isn't present. */
export function deleteView(scanId: number, id: string): SavedView[] {
  const next = read(scanId).filter((v) => v.id !== id)
  write(scanId, next)
  return next
}
