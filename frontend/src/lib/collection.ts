import type { CollectionItem, CollectionResponse, CollectionSection } from '../api/types'

/** Chip/tab order, and the order sections are merged in — so a row that is both
 *  owned and liked always reads "owned · liked", never the reverse. */
export const SECTIONS: readonly CollectionSection[] = ['owned', 'wishlist', 'liked']

export const SECTION_LABELS: Record<CollectionSection, string> = {
  owned: 'Owned',
  wishlist: 'Wishlist',
  liked: 'Liked',
}

/** One item, however many of the three lists it appeared in.
 *
 *  `haystack` is precomputed rather than derived per keystroke: the search runs
 *  over every entry four times on each keypress (the visible list plus a match
 *  count for each of the three tab badges), so normalizing titles inside the
 *  filter would redo the same `normalize()` work thousands of times per
 *  character typed. */
export interface CollectionEntry extends CollectionItem {
  key: string
  sections: CollectionSection[]
  haystack: string
}

/** Identity of the underlying Bandcamp item, independent of which list it came
 *  from. The API returns no row id precisely so this can be the key. */
export function entryKey(item: Pick<CollectionItem, 'item_type' | 'album_id' | 'track_id'>): string {
  return item.item_type === 'track' ? `track:${item.track_id}` : `album:${item.album_id}`
}

/* Combining marks, stripped after NFD splits "ó" into "o" + an accent. A
 * Bandcamp collection is full of Sigur Rós, Björk and Múm, and nobody types the
 * accents into a search box.
 *
 * Module scope per the hoisting rule in frontend/CLAUDE.md. The `g` flag is safe
 * here — that rule's warning is about `lastIndex` on a shared regex, which only
 * `.exec`/`.test` advance; `String.replace` resets it. */
const COMBINING_MARKS = /[\u0300-\u036f]/g

/** Lowercase and accent-free, so "bjork" finds "Björk". */
export function normalize(text: string): string {
  return text.normalize('NFD').replace(COMBINING_MARKS, '').toLowerCase()
}

/** A query becomes independent terms, ALL of which must match — so
 *  "aphex drukqs" finds the one record, in either word order. An empty query
 *  yields no terms, which `matchesTerms` treats as "everything matches". */
export function searchTerms(query: string): string[] {
  return normalize(query).trim().split(/\s+/).filter(Boolean)
}

export function matchesTerms(entry: CollectionEntry, terms: string[]): boolean {
  return terms.every((t) => entry.haystack.includes(t))
}

/** Case-insensitive artist-then-title, mirroring the API's
 *  `lower(coalesce(band_name, ''))` ordering so a merged list keeps the order
 *  each individual list arrived in. A missing artist becomes '' and sorts first,
 *  the same as the server's coalesce. */
function compareEntries(a: CollectionEntry, b: CollectionEntry): number {
  const byBand = (a.band_name ?? '').localeCompare(b.band_name ?? '', undefined, {
    sensitivity: 'base',
  })
  if (byBand !== 0) return byBand
  return (a.title ?? '').localeCompare(b.title ?? '', undefined, { sensitivity: 'base' })
}

/** Fold the three lists into one deduplicated, sorted list.
 *
 *  The API deliberately does not deduplicate: an item you liked in the feed and
 *  later bought is a real row in both `likes` and `fan_items`, and showing it
 *  twice would read as a bug. Merging here instead means the combined
 *  "owned · liked" label comes for free, and every view (All or a single
 *  section) filters the same array. */
export function mergeCollection(data: CollectionResponse): CollectionEntry[] {
  const byKey = new Map<string, CollectionEntry>()
  for (const section of SECTIONS) {
    for (const item of data[section]) {
      const key = entryKey(item)
      const existing = byKey.get(key)
      if (existing) {
        // Same item id → the API joined the same album/track row, so the
        // display fields are identical; only the section is new.
        if (!existing.sections.includes(section)) existing.sections.push(section)
        continue
      }
      byKey.set(key, {
        ...item,
        key,
        sections: [section],
        haystack: normalize(`${item.title ?? ''} ${item.band_name ?? ''}`),
      })
    }
  }
  return [...byKey.values()].sort(compareEntries)
}
