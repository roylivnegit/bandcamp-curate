import { useEffect, useRef, useState } from 'react'

import {
  getLastSeenGeneration,
  isUpdatedSinceLastVisit,
  setLastSeenGeneration,
} from '../../lib/lastSeenGeneration'

/** Surfaces "this scan's feed changed since you were last here" on a fresh
 *  page load — distinct from `ScanFeedPage`'s in-session reflow banner,
 *  which only catches a change observed while the page is already open. Runs
 *  once per `scanId` (a `checkedFor` ref, same "don't re-fire on every poll
 *  tick" shape `useResumeScroll`'s `restoredFor` uses): the moment a real
 *  `generation` is first seen for this scan, it's compared against — then
 *  immediately overwrites — the stored value, so a refresh a second later
 *  doesn't re-show the same notice. */
export function useUpdatedSinceLastVisit(scanId: number | null, generation: number | null) {
  const [updated, setUpdated] = useState(false)
  const checkedFor = useRef<number | null>(null)

  useEffect(() => {
    if (scanId === null || generation === null || checkedFor.current === scanId) return
    checkedFor.current = scanId
    if (isUpdatedSinceLastVisit(generation, getLastSeenGeneration(scanId))) setUpdated(true)
    setLastSeenGeneration(scanId, generation)
  }, [scanId, generation])

  return { updated, dismiss: () => setUpdated(false) }
}
