import { useCallback, useMemo, useState } from 'react'

import type { FeedFilterParams } from '../../api/client'
import type { SortKey } from '../../api/types'

/** include ('by') or exclude ('out') — the two states a committed filter can hold. */
export type FilterMode = 'by' | 'out'

export interface LabelFilter {
  id: number
  name: string
}

/** All feed filter state in one place, mirroring the old UI's loose globals
 *  (type / sort / tagState / tagLikeState / labelFilter). */
export function useFeedFilters(scanId: number | null) {
  const [itemType, setItemType] = useState<'' | 'album' | 'track'>('')
  const [sort, setSort] = useState<SortKey>('score')
  const [tags, setTags] = useState<Record<string, FilterMode>>({})
  const [tagContains, setTagContains] = useState<Record<string, FilterMode>>({})
  const [label, setLabel] = useState<LabelFilter | null>(null)

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

  const toggleTagMode = useCallback((tag: string) => {
    setTags((prev) => ({ ...prev, [tag]: prev[tag] === 'out' ? 'by' : 'out' }))
  }, [])

  const removeTag = useCallback((tag: string) => {
    setTags((prev) => {
      const next = { ...prev }
      delete next[tag]
      return next
    })
  }, [])

  const includeTag = useCallback((tag: string) => {
    setTags((prev) => ({ ...prev, [tag]: 'by' }))
  }, [])

  /** Commit the genre dropdown's pending selection: adds new tags as 'by',
   *  drops deselected ones, and preserves the mode of tags that stay. */
  const commitTags = useCallback((selected: Set<string>) => {
    setTags((prev) => {
      const next: Record<string, FilterMode> = {}
      for (const t of selected) next[t] = prev[t] ?? 'by'
      return next
    })
  }, [])

  const addContains = useCallback((raw: string) => {
    const text = raw.trim().toLowerCase()
    if (!text) return
    setTagContains((prev) => (text in prev ? prev : { ...prev, [text]: 'by' }))
  }, [])

  const toggleContainsMode = useCallback((text: string) => {
    setTagContains((prev) => ({ ...prev, [text]: prev[text] === 'out' ? 'by' : 'out' }))
  }, [])

  const removeContains = useCallback((text: string) => {
    setTagContains((prev) => {
      const next = { ...prev }
      delete next[text]
      return next
    })
  }, [])

  const reset = useCallback(() => {
    setItemType('')
    setSort('score')
    setTags({})
    setTagContains({})
    setLabel(null)
  }, [])

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
    commitTags,
    addContains,
    toggleContainsMode,
    removeContains,
    reset,
  }
}

export type FeedFilters = ReturnType<typeof useFeedFilters>
