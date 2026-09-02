import { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'

import { COPY_LINK_FEEDBACK_MS } from '../config'
import { showToast } from '../lib/toast'

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
      // "Copied" confirmation, since that would claim a copy that didn't
      // happen, but a silent no-op looked identical to a working click doing
      // nothing. A toast says what actually happened instead.
      showToast('Could not copy the link — clipboard access was denied.', 'alert')
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
