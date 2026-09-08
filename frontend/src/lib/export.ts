import type { Recommendation } from '../api/types'

/* Hoisted per rule 9 (js-hoist-regexp, frontend/CLAUDE.md). Matches the
 * leading character a spreadsheet app (Excel/Sheets) treats as a formula
 * trigger: a Bandcamp band/track title starting with one of these would
 * otherwise execute as a formula instead of displaying as text. */
const FORMULA_TRIGGER = /^[=+\-@\t\r]/

/** RFC-4180 field escaping, plus a CSV-injection guard: a value starting
 *  with `=`, `+`, `-`, `@`, tab, or CR gets a leading `'` so a spreadsheet
 *  app renders it as text rather than executing it as a formula. Then wraps
 *  in quotes and doubles any embedded quote whenever the (possibly
 *  guarded) value contains a comma, quote, or line break — the characters
 *  that would otherwise break a naive comma-split read. */
function csvField(value: string): string {
  const guarded = FORMULA_TRIGGER.test(value) ? `'${value}` : value
  if (/[",\r\n]/.test(guarded)) return `"${guarded.replace(/"/g, '""')}"`
  return guarded
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

/** Slugifies a scan name for use in a downloaded filename: lowercase,
 *  non-alphanumeric runs collapsed to a single `-`, leading/trailing `-`
 *  trimmed, capped at 50 characters so a very long scan name can't produce
 *  an unwieldy filename. */
function slugify(name: string): string {
  return name.toLowerCase().replace(SLUG_UNSAFE, '-').replace(/^-+|-+$/g, '').slice(0, 50)
}

/** CSV export filename, scoped to the scan it came from so exporting two
 *  different scans on the same day doesn't produce two files with the
 *  identical name (silently overwriting one in the browser's Downloads
 *  folder). `scanName` is `null` for the pre-#150 generic form, and a name
 *  that's empty/whitespace-only or made entirely of characters `slugify`
 *  strips (e.g. "???") falls back to the same generic form rather than
 *  producing a filename with an empty segment. */
export function exportFilename(scanName: string | null, date: Date): string {
  const dateStr = date.toISOString().slice(0, 10)
  const slug = scanName === null ? '' : slugify(scanName)
  return slug ? `${GENERIC_EXPORT_NAME}-${slug}-${dateStr}.csv` : `${GENERIC_EXPORT_NAME}-${dateStr}.csv`
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
