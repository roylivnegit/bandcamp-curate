import type { SearchHit, SearchResponse } from '../api/types'

/** What a result row says and where it goes, independent of React and of the
 *  palette — so the mapping can be tested on its own and read in one place.
 *
 *  `to` is an in-app route for anything the app has a page for. `openUrl` is
 *  set instead when the only place the record actually exists is Bandcamp:
 *  there is no per-record route here, and sending someone to a 200-card feed
 *  to go and find one track by eye is worse than opening the record itself.
 */
export interface SearchRow {
  id: string
  label: string
  hint?: string
  srHint?: string
  to?: string
  openUrl?: string
}

/** "Drukqs — Aphex Twin", or just one side when the other is missing. A
 *  crawled record can legitimately have neither (`title` and the band are both
 *  nullable), which becomes "Untitled" rather than an empty row. */
function itemLabel(hit: SearchHit): string {
  const title = hit.title?.trim()
  const band = hit.band_name?.trim()
  if (title && band) return `${title} — ${band}`
  return title || band || 'Untitled'
}

/** "owned · liked", in the order the API returns them (which is the
 *  Collection page's own section order). The section keys are already the
 *  words to show, so this deliberately does not import `SECTION_LABELS` from
 *  `lib/collection`: that module is only reachable from the lazy Collection
 *  route today, and importing it here would pull it into the entry chunk to
 *  title-case three strings and lowercase them again. */
function sectionsHint(hit: SearchHit): string {
  return hit.sections.join(' · ')
}

function itemKey(hit: SearchHit): string {
  return hit.item_type === 'track' ? `track-${hit.track_id}` : `album-${hit.album_id}`
}

/** Flatten one API response into the rows the palette shows, in the order it
 *  shows them: what the user already has first, then what the feed suggests.
 *  Scans are not in here — the palette's own local actions cover those. */
export function searchRows(data: SearchResponse): SearchRow[] {
  const rows: SearchRow[] = []

  for (const hit of data.collection) {
    // The Collection page takes `?q=` and filters its own fully-loaded list,
    // so this lands on the record rather than merely on the page. Searching
    // the title (not the artist) keeps the result to the one record even for
    // an artist with 40 of them.
    const q = hit.title?.trim()
    rows.push({
      id: `search-collection-${itemKey(hit)}`,
      label: itemLabel(hit),
      hint: sectionsHint(hit),
      to: q ? `/collection?q=${encodeURIComponent(q)}` : '/collection',
    })
  }

  for (const hit of data.feed) {
    // A feed row has no route of its own: the quick filter on a scan's feed
    // only sees the page of recommendations already loaded, so pointing at the
    // scan is a promise the page can't keep for a record ranked #700. The
    // record on Bandcamp is the destination that always works. Falls back to
    // the scan when the crawl never recorded a URL.
    rows.push({
      id: `search-feed-${hit.scan_id}-${itemKey(hit)}`,
      label: itemLabel(hit),
      hint: hit.url ? `in ${hit.scan_name} ↗` : `in ${hit.scan_name}`,
      srHint: hit.url ? ` in ${hit.scan_name} — opens Bandcamp in a new tab` : ` in ${hit.scan_name}`,
      openUrl: hit.url ?? undefined,
      to: hit.url ? undefined : `/scans/${hit.scan_id}`,
    })
  }

  return rows
}
