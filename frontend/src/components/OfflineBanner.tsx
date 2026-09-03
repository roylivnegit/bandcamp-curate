import { useOnlineStatus } from '../lib/useOnlineStatus'

/** Mounted once in the app shell (`App.tsx`). Own visibility state driven by
 *  `navigator.onLine` — deliberately NOT routed through the toast queue
 *  (`lib/toast.ts`): a toast always arms a real auto-dismiss timer, which
 *  can't express "stay up for as long as connectivity is actually down." */
export function OfflineBanner() {
  const online = useOnlineStatus()
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
