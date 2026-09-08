import { useEffect, useState } from 'react'

/** Tracks `navigator.onLine`, updated by the browser's `online`/`offline`
 *  events. Standalone (not routed through the toast queue, per the QA
 *  correction on this backlog item) — `showToast` always arms a real
 *  auto-dismiss timer, which can't express "stay up until connectivity
 *  actually returns." */
export function useOnlineStatus(): boolean {
  const [online, setOnline] = useState(() => navigator.onLine)

  useEffect(() => {
    const goOnline = () => setOnline(true)
    const goOffline = () => setOnline(false)
    window.addEventListener('online', goOnline)
    window.addEventListener('offline', goOffline)
    return () => {
      window.removeEventListener('online', goOnline)
      window.removeEventListener('offline', goOffline)
    }
  }, [])

  return online
}
