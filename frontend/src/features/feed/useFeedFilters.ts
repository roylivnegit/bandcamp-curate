import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'

import type { FeedFilterParams } from '../../api/client'
import type { SortKey } from '../../api/types'

/** include ('by') or exclude ('out') — the two states a committed filter can hold. */
export type FilterMode = 'by' | 'out'

export interface LabelFilter {
  id: number
  name: string
}

/* Query param names, deliberately the same ones `filterQuery` (api/client.ts) sends
 * to the API — the URL is close to a literal record of the request, not a
 * separately-invented encoding. `label_name` is UI-only (the API only needs the id;
 * the pill needs the name too, and re-deriving it would mean an extra fetch on
 * every page load that starts from a shared/bookmarked link). */
const TYPE = 'item_type'
const SORT = 'sort'
const TAG = 'tag'
const EXCLUDE_TAG = 'exclude_tag'
const CONTAINS = 'tag_contains'
const EXCLUDE_CONTAINS = 'exclude_tag_contains'
const LABEL_ID = 'label_id'
const LABEL_NAME = 'label_name'

function isItemType(v: string | null): v is '' | 'album' | 'track' {
  return v === 'album' || v === 'track'
}

function isSortKey(v: string | null): v is SortKey {
  return v === 'score' || v === 'neighbours' || v === 'affinity'
}

/** Reads a by/out pair of repeated params into the `{ [value]: mode }` shape the
 *  rest of the feed already works with. */
function readModes(params: URLSearchParams, byKey: string, outKey: string): Record<string, FilterMode> {
  const out: Record<string, FilterMode> = {}
  for (const v of params.getAll(byKey)) out[v] = 'by'
  for (const v of params.getAll(outKey)) out[v] = 'out'
  return out
}

/** Inverse of `readModes` — rewrites a by/out pair of repeated params in place
 *  from a `{ [value]: mode }` map. */
function writeModes(
  params: URLSearchParams,
  byKey: string,
  outKey: string,
  map: Record<string, FilterMode>,
): void {
  params.delete(byKey)
  params.delete(outKey)
  for (const [value, mode] of Object.entries(map)) {
    params.append(mode === 'out' ? outKey : byKey, value)
  }
}

/** All feed filter state in one place, mirroring the old UI's loose globals
 *  (type / sort / tagState / tagLikeState / labelFilter) — except it lives in the
 *  URL (`useSearchParams`) rather than component state, so a filtered view can be
 *  bookmarked or shared, and survives a reload or a browser-back into this page.
 *
 *  Every setter goes through `setSearchParams`'s functional-updater form and reads
 *  only the `prev` it's handed — never the memoized `tags`/`label`/etc. below — so
 *  none of them need those as a dependency (the same "derive during render, update
 *  functionally" shape `frontend/CLAUDE.md` asks for, just against the URL instead
 *  of a `useState`). `{ replace: true }` throughout: toggling several tags should
 *  end with one history entry to come back to, not one per click. */
export function useFeedFilters(scanId: number | null) {
  const [searchParams, setSearchParams] = useSearchParams()

  const itemType = useMemo<'' | 'album' | 'track'>(() => {
    const v = searchParams.get(TYPE)
    return isItemType(v) ? v : ''
  }, [searchParams])

  const sort = useMemo<SortKey>(() => {
    const v = searchParams.get(SORT)
    return isSortKey(v) ? v : 'score'
  }, [searchParams])

  const tags = useMemo(() => readModes(searchParams, TAG, EXCLUDE_TAG), [searchParams])
  const tagContains = useMemo(() => readModes(searchParams, CONTAINS, EXCLUDE_CONTAINS), [searchParams])

  const label = useMemo<LabelFilter | null>(() => {
    const id = searchParams.get(LABEL_ID)
    // `Number('')` is `0`, and `Number.isInteger(0)` is true, so an empty
    // `label_id=` (a hand-edited or partially-stripped bookmarked URL) would
    // otherwise parse as a real filter on band id 0 instead of "no filter".
    if (id === null || id === '') return null
    const parsed = Number(id)
    if (!Number.isInteger(parsed)) return null
    return { id: parsed, name: searchParams.get(LABEL_NAME) ?? 'unknown' }
  }, [searchParams])

  const params: FeedFilterParams = useMemo(
    () => ({ scanId, itemType, tags, tagContains, labelId: label?.id ?? null }),
    [scanId, itemType, tags, tagContains, label],
  )

  /** Any filter beyond the scan itself — drives "N results match your filters". */
  const anyActive =
    itemType !== '' ||
    label !== null ||
    Object.keys(tags).length > 0 ||
    Object.keys(tagContains).length > 0

  const setItemType = useCallback(
    (v: '' | 'album' | 'track') => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          if (v) next.set(TYPE, v)
          else next.delete(TYPE)
          return next
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

  const setSort = useCallback(
    (v: SortKey) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          if (v !== 'score') next.set(SORT, v)
          else next.delete(SORT)
          return next
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

  const setLabel = useCallback(
    (l: LabelFilter | null) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          if (l) {
            next.set(LABEL_ID, String(l.id))
            next.set(LABEL_NAME, l.name)
          } else {
            next.delete(LABEL_ID)
            next.delete(LABEL_NAME)
          }
          return next
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

  const toggleTagMode = useCallback(
    (tag: string) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          const map = readModes(next, TAG, EXCLUDE_TAG)
          map[tag] = map[tag] === 'out' ? 'by' : 'out'
          writeModes(next, TAG, EXCLUDE_TAG, map)
          return next
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

  const removeTag = useCallback(
    (tag: string) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          const map = readModes(next, TAG, EXCLUDE_TAG)
          delete map[tag]
          writeModes(next, TAG, EXCLUDE_TAG, map)
          return next
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

  const includeTag = useCallback(
    (tag: string) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          const map = readModes(next, TAG, EXCLUDE_TAG)
          map[tag] = 'by'
          writeModes(next, TAG, EXCLUDE_TAG, map)
          return next
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

  /** Commit the genre dropdown's pending selection: adds new tags as 'by',
   *  drops deselected ones, and preserves the mode of tags that stay. */
  const commitTags = useCallback(
    (selected: Set<string>) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          const map = readModes(next, TAG, EXCLUDE_TAG)
          const out: Record<string, FilterMode> = {}
          for (const t of selected) out[t] = map[t] ?? 'by'
          writeModes(next, TAG, EXCLUDE_TAG, out)
          return next
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

  const addContains = useCallback(
    (raw: string) => {
      const text = raw.trim().toLowerCase()
      if (!text) return
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          const map = readModes(next, CONTAINS, EXCLUDE_CONTAINS)
          if (!(text in map)) map[text] = 'by'
          writeModes(next, CONTAINS, EXCLUDE_CONTAINS, map)
          return next
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

  const toggleContainsMode = useCallback(
    (text: string) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          const map = readModes(next, CONTAINS, EXCLUDE_CONTAINS)
          map[text] = map[text] === 'out' ? 'by' : 'out'
          writeModes(next, CONTAINS, EXCLUDE_CONTAINS, map)
          return next
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

  const removeContains = useCallback(
    (text: string) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          const map = readModes(next, CONTAINS, EXCLUDE_CONTAINS)
          delete map[text]
          writeModes(next, CONTAINS, EXCLUDE_CONTAINS, map)
          return next
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

  /** Drops one or more `tag=` (include-mode) entries in a single update — used
   *  to auto-clear a stale filter (a tag that no longer appears in the scan's
   *  current recommendations, e.g. after a recompute) rather than leaving it
   *  silently matching nothing. Deliberately only ever called with `by`-mode
   *  keys: an `exclude_tag` for a value that's currently absent is a harmless
   *  no-op, not a "silently empty feed" bug, so it's left alone. */
  const pruneTags = useCallback(
    (stale: string[]) => {
      if (stale.length === 0) return
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          const map = readModes(next, TAG, EXCLUDE_TAG)
          for (const t of stale) delete map[t]
          writeModes(next, TAG, EXCLUDE_TAG, map)
          return next
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

  const reset = useCallback(() => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        for (const key of [TYPE, SORT, TAG, EXCLUDE_TAG, CONTAINS, EXCLUDE_CONTAINS, LABEL_ID, LABEL_NAME]) {
          next.delete(key)
        }
        return next
      },
      { replace: true },
    )
  }, [setSearchParams])

  return {
    itemType,
    setItemType,
    sort,
    setSort,
    tags,
    tagContains,
    label,
    setLabel,
    params,
    anyActive,
    includeTag,
    toggleTagMode,
    removeTag,
    pruneTags,
    commitTags,
    addContains,
    toggleContainsMode,
    removeContains,
    reset,
  }
}

export type FeedFilters = ReturnType<typeof useFeedFilters>
