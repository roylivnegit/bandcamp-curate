import { useEffect, useRef, useState } from 'react'

import type { Recommendation } from '../api/types'
import { COPY_LINK_FEEDBACK_MS } from '../config'
import { recsToMarkdown } from '../lib/markdown'
import { showToast } from '../lib/toast'

/** Copies the currently loaded/filtered feed rows as a Markdown bullet list
 *  (`- [Band – Title](url)`), for pasting into Discord/notes/etc. Mirrors
 *  `CopyLinkButton`'s clipboard-write + toast-on-failure pattern. */
export function CopyMarkdownButton({ rows }: { rows: Recommendation[] }) {
  const [copied, setCopied] = useState(false)
  const timerRef = useRef<number | null>(null)

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current)
    }
  }, [])

  async function handleClick() {
    const text = recsToMarkdown(rows)
    try {
      await navigator.clipboard.writeText(text)
    } catch {
      // Same rationale as CopyLinkButton: no silent no-op and no "Copied"
      // claim for a write that didn't happen — a toast says what happened.
      showToast('Could not copy the feed — clipboard access was denied.', 'alert')
      return
    }
    setCopied(true)
    // Same rationale as CopyLinkButton: the "Copied" text swap alone reaches
    // no screen reader, while the failure path already gets a proper toast.
    showToast('Feed copied as Markdown.', 'status')
    if (timerRef.current !== null) window.clearTimeout(timerRef.current)
    timerRef.current = window.setTimeout(() => setCopied(false), COPY_LINK_FEEDBACK_MS)
  }

  return (
    <button type="button" className="btn ghost" onClick={handleClick} disabled={rows.length === 0}>
      {copied ? 'Copied' : 'Copy as Markdown'}
    </button>
  )
}
