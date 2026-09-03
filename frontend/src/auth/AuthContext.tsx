/* Session state: the bearer token plus the `me` payload it resolves to.
 *
 * `me` matters beyond the username — it carries the collection scan's status, so
 * the app can tell a brand-new user their collection is still being crawled
 * instead of showing them an empty feed with no explanation.
 */

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

import { ApiError, api, getToken, setToken, setUnauthorizedHandler } from '../api/client'
import type { Me } from '../api/types'
import { showToast } from '../lib/toast'
import { useSessionExpiryWarning } from '../lib/useSessionExpiryWarning'
import { AuthContext } from './context'

const SESSION_EXPIRED_MESSAGE = 'Your session expired — please log in again.'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)
  const [authError, setAuthError] = useState('')

  const logout = useCallback(() => {
    setToken(null)
    setMe(null)
  }, [])

  // Read synchronously from the handler below without re-registering it on
  // every `me` change (rule 3, frontend/CLAUDE.md: a ref for a value only
  // read imperatively, not one that drives a render).
  const meRef = useRef<Me | null>(null)
  useEffect(() => {
    meRef.current = me
  }, [me])

  // A 401 from any request drops the session, wherever it happened. Only
  // toast about it when it actually ended a real session — the initial
  // stale-token-on-load 401 (below) and an explicit logout() both leave
  // `meRef.current` null/unset already, so neither should say "expired".
  useEffect(() => {
    setUnauthorizedHandler(() => {
      if (meRef.current !== null) showToast(SESSION_EXPIRED_MESSAGE, 'alert')
      setMe(null)
    })
    return () => setUnauthorizedHandler(null)
  }, [])

  // Resolve a token left over from a previous visit.
  useEffect(() => {
    let cancelled = false
    if (!getToken()) {
      setLoading(false)
      return
    }
    api
      .me()
      .then((m) => {
        if (!cancelled) setMe(m)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        // ONLY a 401 means the token is actually bad — and the client has
        // already discarded it by then. A network failure or a 5xx says nothing
        // about the session, and throwing it away would sign people out every
        // time the API is briefly unreachable (the free tier cold-starts for
        // ~30-60s, so that is the common case, not the rare one).
        if (err instanceof ApiError && err.status !== 401) {
          setAuthError(err.message)
        } else if (!(err instanceof ApiError)) {
          setAuthError('Could not reach the server.')
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const login = useCallback(async (username: string, password: string) => {
    const { access_token } = await api.login({ username, password })
    setToken(access_token)
    setMe(await api.me())
    setAuthError('')
  }, [])

  const signup = useCallback(
    async (body: {
      username: string
      password: string
      bandcamp_fan_url: string
      invite_code: string
    }) => {
      const { access_token } = await api.signup(body)
      setToken(access_token)
      setMe(await api.me())
    },
    [],
  )

  const refresh = useCallback(async () => {
    if (!getToken()) return
    try {
      setMe(await api.me())
    } catch {
      /* a 401 already cleared the session via the handler above */
    }
  }, [])

  useSessionExpiryWarning(me !== null ? getToken() : null)

  const value = useMemo(
    () => ({ me, loading, authError, login, signup, logout, refresh }),
    [me, loading, authError, login, signup, logout, refresh],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
