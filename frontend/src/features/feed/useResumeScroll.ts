import { useEffect, useRef } from 'react'

/** sessionStorage-backed "resume where you left off" for the feed's scroll
 *  position. `storageKey` is built by the caller from the scan id plus the
 *  current filter query string, so a different filter set is simply a
 *  different key — restoring never has to special-case "filters changed",
 *  it just finds nothing under the new key. `ready` gates the restore on
 *  content having actually rendered (rows loaded), so it never scrolls to a
 *  position the still-loading page can't yet reach. */
export function useResumeScroll(storageKey: string | null, ready: boolean) {
  // Which key has already been restored for, so a page-1 fetch racing with
  // "load more" (both toggle `ready`) doesn't re-apply the same offset twice.
  const restoredFor = useRef<string | null>(null)

  useEffect(() => {
    if (!ready || storageKey === null || restoredFor.current === storageKey) return
    restoredFor.current = storageKey
    const stored = sessionStorage.getItem(storageKey)
    if (stored === null) return
    const y = Number(stored)
    if (Number.isFinite(y)) window.scrollTo(0, y)
  }, [storageKey, ready])

  useEffect(() => {
    if (storageKey === null) return
    const key = storageKey
    const onScroll = () => sessionStorage.setItem(key, String(window.scrollY))
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [storageKey])
}
