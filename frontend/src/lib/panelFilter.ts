/** Case-insensitive substring match against any of the given fields — the
 *  shared logic behind the search box in `LikedPanel`/`BlockedPanel`
 *  (`SidePanels.tsx`). A blank (or all-whitespace) query matches everything,
 *  same "empty query passes through" convention as `lib/quickFilter.ts`'s
 *  `matchesQuery`. */
export function matchesPanelQuery(fields: Array<string | null | undefined>, query: string): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return true
  return fields.some((f) => f != null && f.toLowerCase().includes(q))
}
