/* The context object + hook live apart from the provider component so the
 * provider module only exports components (keeps Vite fast-refresh working). */

import { createContext, useContext } from 'react'

import type { Me } from '../api/types'

export interface AuthValue {
  me: Me | null
  /** True until any stored token has been checked against /api/auth/me. */
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  signup: (body: {
    username: string
    password: string
    bandcamp_fan_url: string
    invite_code: string
  }) => Promise<void>
  logout: () => void
  /** Re-fetch `me` — used to pick up collection_scan status changes. */
  refresh: () => Promise<void>
}

export const AuthContext = createContext<AuthValue | null>(null)

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
