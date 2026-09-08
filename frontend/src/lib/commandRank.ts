/** Which quality of match `q` (already trimmed/lowercased) is against `label`
 *  (already lowercased), or `null` for no match at all. Lower is better:
 *  a prefix match ("sca" → "Scavenger Hunt") ranks above a word-boundary
 *  match ("sca" → "My Ambient Scan"), which ranks above a match buried
 *  mid-word. */
function matchTier(label: string, q: string): 0 | 1 | 2 | null {
  const idx = label.indexOf(q)
  if (idx === -1) return null
  if (idx === 0) return 0
  if (label[idx - 1] === ' ') return 1
  return 2
}

/** Ranks `items` by how well `item.label` matches `query` — prefix match,
 *  then word-boundary match, then plain substring — instead of leaving
 *  matches in whatever order the caller passed them in. Ties within a tier
 *  keep the original relative order (a plain filter-then-stable-sort would
 *  do the same, but doing it in one pass avoids computing the tier twice).
 *  A blank query returns `items` unchanged, same "empty query passes
 *  through" convention as `lib/quickFilter.ts`/`lib/panelFilter.ts`. */
export function rankCommands<T extends { label: string }>(items: T[], query: string): T[] {
  const q = query.trim().toLowerCase()
  if (!q) return items
  return items
    .map((item, index) => ({ item, index, tier: matchTier(item.label.toLowerCase(), q) }))
    .filter((x): x is { item: T; index: number; tier: 0 | 1 | 2 } => x.tier !== null)
    .sort((a, b) => a.tier - b.tier || a.index - b.index)
    .map((x) => x.item)
}
