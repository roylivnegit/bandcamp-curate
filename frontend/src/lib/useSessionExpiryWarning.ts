import { useEffect } from 'react'

import { msUntilWarning } from './sessionExpiry'
import { showToast } from './toast'

export const SESSION_EXPIRING_MESSAGE = 'Your session is expiring soon — log in again to keep working.'

/** Schedules a one-time warning toast before `token`'s JWT `exp` claim
 *  lapses, so a session doesn't just silently die mid-task. Re-evaluated
 *  whenever `token` changes (a fresh login gets a fresh timer) and cleared
 *  on unmount/change so a stale timer from a previous token never fires.
 *  `null` (signed out, or a token with no readable expiry) schedules
 *  nothing — this is warn-only, no refresh flow exists to build on top of
 *  it.
 *
 *  `logout` gives the warning an action button ("Log out now") so the user
 *  can end the session cleanly instead of just being told it's about to be
 *  yanked out from under them. `AuthContext`'s `logout` is a stable
 *  `useCallback`, so listing it as a dependency here doesn't reschedule the
 *  timer on every render — it only re-runs the effect on a genuine `token`
 *  or `logout`-identity change, same as `token` alone did before. */
export function useSessionExpiryWarning(token: string | null, logout: () => void) {
  useEffect(() => {
    if (token === null) return
    const delay = msUntilWarning(token, Date.now())
    if (delay === null) return
    const id = window.setTimeout(() => {
      showToast(SESSION_EXPIRING_MESSAGE, 'alert', undefined, { label: 'Log out now', onClick: logout })
    }, delay)
    return () => window.clearTimeout(id)
  }, [token, logout])
}
