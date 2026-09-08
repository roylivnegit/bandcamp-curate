import { useEffect, useRef } from 'react'

import { showToast } from '../lib/toast'
import { useOnlineStatus } from '../lib/useOnlineStatus'

/** Mounted once in the app shell (`App.tsx`). Own visibility state driven by
 *  `navigator.onLine` — deliberately NOT routed through the toast queue
 *  (`lib/toast.ts`): a toast always arms a real auto-dismiss timer, which
 *  can't express "stay up for as long as connectivity is actually down." */
export function OfflineBanner() {
  const online = useOnlineStatus()
  // A one-shot "back online" toast IS the right fit here, unlike the banner
  // itself — it's inherently transient, not something that needs to persist.
  // `wasOffline` guards against firing on initial mount (the common case:
  // the page loads already online, which is not a reconnect) — only a real
  // false→true transition counts.
  const wasOffline = useRef(false)
  useEffect(() => {
    if (!online) {
      wasOffline.current = true
    } else if (wasOffline.current) {
      wasOffline.current = false
      showToast('Back online.', 'status')
    }
  }, [online])

  if (online) return null

  return (
    <div className="banner error offlinebanner" role="status">
      <span>
        You&rsquo;re offline. Likes, blocks, and new scans won&rsquo;t save until your
        connection comes back.
      </span>
    </div>
  )
}
