import { useEffect, useRef, useState } from 'react'

/** Tracks whether a scan just finished (a `running` → `done` transition)
 *  while the tab was hidden/unfocused — there's otherwise no signal in the
 *  tab bar that a long crawl finished, so tabbing away means manually
 *  re-checking. Stays `false` for a scan that was already `done` on mount
 *  (nothing to announce, it didn't just finish) and for a transition that
 *  happens while the tab is visible (the reader is already watching it).
 *  Clears itself the moment the tab becomes visible again — the reader
 *  noticing on their own. Deliberately its own hook, not folded into
 *  `useDocumentTitle`, so it's testable without mounting the page that
 *  formats the title string. */
export function useScanFinishedMarker(status: string | null | undefined): boolean {
  const [marked, setMarked] = useState(false)
  const prevStatus = useRef(status)

  useEffect(() => {
    if (prevStatus.current === 'running' && status === 'done' && document.hidden) {
      setMarked(true)
    }
    prevStatus.current = status
  }, [status])

  useEffect(() => {
    if (!marked) return
    function onVisibilityChange() {
      if (!document.hidden) setMarked(false)
    }
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => document.removeEventListener('visibilitychange', onVisibilityChange)
  }, [marked])

  return marked
}
