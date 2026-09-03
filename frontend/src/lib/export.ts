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
