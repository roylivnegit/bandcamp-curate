import { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'

import { COPY_LINK_FEEDBACK_MS } from '../config'

/** Copies the current view's URL (including feed filters, which live in the
 *  query string via `useFeedFilters`/`useSearchParams`) to the clipboard, so
 *  a filtered view that's already shareable/bookmarkable is also visibly
 *  shareable rather than something a reader has to notice in the address bar. */
export function CopyLinkButton() {
  const location = useLocation()
  const [copied, setCopied] = useState(false)
  const timerRef = useRef<number | null>(null)

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current)
    }
  }, [])

  async function handleClick() {
    const url = `${window.location.origin}${location.pathname}${location.search}`
    try {
      await navigator.clipboard.writeText(url)
    } catch {
      // Clipboard access can be denied (permissions, insecure context) — no
      // confirmation to show rather than claiming a copy that didn't happen.
      return
    }
    setCopied(true)
    if (timerRef.current !== null) window.clearTimeout(timerRef.current)
    timerRef.current = window.setTimeout(() => setCopied(false), COPY_LINK_FEEDBACK_MS)
  }

  return (
    <button type="button" className="btn ghost" onClick={handleClick}>
      {copied ? 'Copied' : 'Copy link'}
    </button>
  )
}
