import { useEffect, useState } from 'react'

import { RELATIVE_TIME_REFRESH_MS } from '../config'
import { ago } from '../lib/format'

/** Self-refreshing `ago(iso)` text. A page that stops polling once nothing is
 *  in flight (e.g. `ScanListPage` once every scan is `done`) would otherwise
 *  leave "3m ago" stuck at whatever it read on the last render — this owns its
 *  own interval so the text keeps advancing on a tab left open, independent of
 *  any parent poll. */
export function RelativeTime({ iso }: { iso: string | null }) {
  const [, setTick] = useState(0)

  useEffect(() => {
    if (!iso) return
    const id = window.setInterval(() => setTick((n) => n + 1), RELATIVE_TIME_REFRESH_MS)
    return () => window.clearInterval(id)
  }, [iso])

  return <>{ago(iso)}</>
}
