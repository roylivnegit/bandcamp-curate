import { describe, expect, it } from 'vitest'

import { SESSION_EXPIRY_WARNING_MS } from '../config'
import { msUntilWarning } from './sessionExpiry'

function fakeJwt(expSeconds: number | undefined): string {
  const base64url = (obj: unknown) =>
    btoa(JSON.stringify(obj)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
  const payload = expSeconds === undefined ? {} : { exp: expSeconds }
  return `${base64url({ alg: 'HS256' })}.${base64url(payload)}.sig`
}

describe('msUntilWarning', () => {
  const now = 1_700_000_000_000

  it('returns the delay until the warning window before expiry, for a token with plenty of time left', () => {
    const expMs = now + 60 * 60 * 1000 // 1h from now
    const token = fakeJwt(expMs / 1000)
    expect(msUntilWarning(token, now)).toBe(60 * 60 * 1000 - SESSION_EXPIRY_WARNING_MS)
  })

  it('warns immediately (0) when less than the warning window remains but the token is still valid', () => {
    const expMs = now + 60 * 1000 // 1 minute from now, less than the warning window
    const token = fakeJwt(expMs / 1000)
    expect(msUntilWarning(token, now)).toBe(0)
  })

  it('returns null for a token that has already expired', () => {
    const expMs = now - 1000
    const token = fakeJwt(expMs / 1000)
    expect(msUntilWarning(token, now)).toBeNull()
  })

  it('returns null for a token with no exp claim', () => {
    expect(msUntilWarning(fakeJwt(undefined), now)).toBeNull()
  })

  it('returns null for a malformed token', () => {
    expect(msUntilWarning('not-a-jwt', now)).toBeNull()
  })
})
