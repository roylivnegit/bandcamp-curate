/* Session state: the bearer token plus the `me` payload it resolves to.
 *
 * `me` matters beyond the username — it carries the collection scan's status, so
 * the app can tell a brand-new user their collection is still being crawled
 * instead of showing them an empty feed with no explanation.
 */

import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'

import { ApiError, api, getToken, setToken, setUnauthorizedHandler } from '../api/client'
import type { Me } from '../api/types'
import { AuthContext } from './context'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)
  const [authError, setAuthError] = useState('')

  const logout = useCallback(() => {
    setToken(null)
    setMe(null)
  }, [])

  // A 401 from any request drops the session, wherever it happened.
  useEffect(() => {
    setUnauthorizedHandler(() => setMe(null))
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

  const value = useMemo(
    () => ({ me, loading, authError, login, signup, logout, refresh }),
    [me, loading, authError, login, signup, logout, refresh],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
