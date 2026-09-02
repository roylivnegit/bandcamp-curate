import type { Recommendation } from '../api/types'

function escapeMarkdownLabel(text: string): string {
  return text.replace(/[[\]]/g, (c) => `\\${c}`)
}

function labelFor(rec: Recommendation): string {
  if (rec.band_name && rec.title) return `${rec.band_name} – ${rec.title}`
  return rec.title ?? rec.band_name ?? 'Untitled'
}

/** Renders recommendations as a Markdown bullet list, one row per line, for
 *  pasting into Discord/notes/etc. — `- [Band – Title](url)`. A row with no
 *  `url` (the discover-by-id convention, see `Recommendation.url`) renders as
 *  plain text instead of fabricating a link. */
export function recsToMarkdown(recs: Recommendation[]): string {
  return recs
    .map((r) => {
      const label = escapeMarkdownLabel(labelFor(r))
      return r.url ? `- [${label}](${r.url})` : `- ${label}`
    })
    .join('\n')
}
