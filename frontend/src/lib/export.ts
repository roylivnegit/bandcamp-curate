import type { Recommendation } from '../api/types'

/** RFC-4180 field escaping: wrap in quotes and double any embedded quote
 *  whenever the value contains a comma, quote, or line break — the
 *  characters that would otherwise break a naive comma-split read. */
function csvField(value: string): string {
  if (/[",\r\n]/.test(value)) return `"${value.replace(/"/g, '""')}"`
  return value
}

const HEADERS = ['Rank', 'Type', 'Title', 'Artist', 'Score', 'Co-owners', 'Genre match', 'URL']

/** Renders recommendations as an RFC-4180 CSV string (CRLF rows, header
 *  included). Pure — no DOM, no fetch — so it's fully unit-testable;
 *  `downloadCsv` below is the thin DOM wrapper that actually saves it. */
export function formatRecommendationsAsCsv(recs: Recommendation[]): string {
  const rows = recs.map((r) =>
    [
      String(r.rank),
      r.item_type,
      r.title ?? '',
      r.band_name ?? '',
      String(r.score),
      String(r.reasons.co_owners),
      String(r.reasons.tag_affinity),
      r.url ?? '',
    ]
      .map(csvField)
      .join(','),
  )
  return [HEADERS.join(','), ...rows].join('\r\n')
}

const GENERIC_EXPORT_NAME = 'bandcamp-feed'
/* Hoisted per rule 9 (js-hoist-regexp, frontend/CLAUDE.md) — exportFilename
 * runs once per export click, not a hot path, but there's no reason not to. */
const SLUG_UNSAFE = /[^a-z0-9]+/g
/** Anything outside the ASCII range `slugify` can represent at all — a name
 *  written entirely in a non-Latin script (Cyrillic, CJK, Hebrew, …) needs
 *  the `fallbackTag` path below instead of collapsing to the plain generic
 *  form, unlike a name that's merely all-ASCII-punctuation (e.g. "???"). */
const NON_ASCII = /[^\p{ASCII}]/u

/** Slugifies a scan name for use in a downloaded filename: lowercase,
 *  non-alphanumeric runs collapsed to a single `-`, leading/trailing `-`
 *  trimmed, capped at 50 characters so a very long scan name can't produce
 *  an unwieldy filename. */
function slugify(name: string): string {
  return name.toLowerCase().replace(SLUG_UNSAFE, '-').replace(/^-+|-+$/g, '').slice(0, 50)
}

/** Deterministic short tag derived from a name that `slugify` can't
 *  represent in ASCII at all (djb2-style hash, base36) — distinct non-Latin
 *  names still produce distinct filenames instead of all collapsing onto
 *  the one generic form. Not for uniqueness guarantees beyond "good enough
 *  to avoid the common case," same spirit as the 50-character slug cap. */
function fallbackTag(name: string): string {
  let hash = 5381
  for (let i = 0; i < name.length; i++) hash = (hash * 33 + name.charCodeAt(i)) | 0
  return Math.abs(hash).toString(36)
}

/** CSV export filename, scoped to the scan it came from so exporting two
 *  different scans on the same day doesn't produce two files with the
 *  identical name (silently overwriting one in the browser's Downloads
 *  folder). `scanName` is `null` for the pre-#150 generic form. A name
 *  that's empty/whitespace-only or made entirely of ASCII characters
 *  `slugify` strips (e.g. "???") falls back to the same generic form, since
 *  there's nothing distinguishing left to encode. A name `slugify` empties
 *  out for a different reason — it's written entirely in a non-Latin
 *  script, which the ASCII-only slug can't represent at all — instead gets
 *  a deterministic `fallbackTag`, so two differently-named non-Latin scans
 *  still get distinct filenames rather than reproducing the exact
 *  same-day collision this function exists to prevent. */
export function exportFilename(scanName: string | null, date: Date): string {
  const dateStr = date.toISOString().slice(0, 10)
  if (scanName === null) return `${GENERIC_EXPORT_NAME}-${dateStr}.csv`
  const slug = slugify(scanName)
  if (slug) return `${GENERIC_EXPORT_NAME}-${slug}-${dateStr}.csv`
  if (NON_ASCII.test(scanName)) return `${GENERIC_EXPORT_NAME}-${fallbackTag(scanName)}-${dateStr}.csv`
  return `${GENERIC_EXPORT_NAME}-${dateStr}.csv`
}

/** Triggers a browser download of `csv` as `filename` via a temporary
 *  object-URL anchor, revoked right after the click. DOM plumbing only —
 *  the string it saves is what `formatRecommendationsAsCsv` is tested
 *  against, so this itself carries no separate logic to unit test. */
export function downloadCsv(filename: string, csv: string): void {
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
