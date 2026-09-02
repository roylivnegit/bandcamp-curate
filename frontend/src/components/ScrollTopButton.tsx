import { useEffect, useState } from 'react'

import { SCROLL_TOP_THRESHOLD_PX } from '../config'
import './ScrollTopButton.css'

/** Floating "back to top" control for a feed grown long via "load more" —
 *  appears only once the reader has scrolled past `SCROLL_TOP_THRESHOLD_PX`,
 *  and on click both scrolls to the top and hands focus to `onClick`'s
 *  caller-supplied target (typically the page heading), matching the
 *  focus-on-route-change pattern already used elsewhere in this app. */
export function ScrollTopButton({ onClick }: { onClick: () => void }) {
  const [visible, setVisible] = useState(() => window.scrollY > SCROLL_TOP_THRESHOLD_PX)

  useEffect(() => {
    const onScroll = () => setVisible(window.scrollY > SCROLL_TOP_THRESHOLD_PX)
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  if (!visible) return null

  return (
    <button type="button" className="scrolltop" onClick={onClick} aria-label="Back to top">
      <span aria-hidden="true">↑</span>
    </button>
  )
}
