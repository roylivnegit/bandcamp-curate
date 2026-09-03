import { describe, expect, it } from 'vitest'

import { decodeJwtExpMs } from './jwt'

function fakeJwt(payload: Record<string, unknown>): string {
  const base64url = (obj: unknown) =>
    btoa(JSON.stringify(obj)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
  return `${base64url({ alg: 'HS256', typ: 'JWT' })}.${base64url(payload)}.signature`
}

describe('decodeJwtExpMs', () => {
  it('reads the exp claim (seconds) as ms', () => {
    expect(decodeJwtExpMs(fakeJwt({ exp: 1_700_000_000 }))).toBe(1_700_000_000_000)
  })

  it('returns null for a token that is not three dot-separated parts', () => {
    expect(decodeJwtExpMs('not-a-jwt')).toBeNull()
    expect(decodeJwtExpMs('only.two')).toBeNull()
  })

  it('returns null for a payload that is not valid base64/JSON', () => {
    expect(decodeJwtExpMs('header.!!!not-base64!!!.sig')).toBeNull()
  })

  it('returns null when the exp claim is missing', () => {
    expect(decodeJwtExpMs(fakeJwt({ sub: 'roy' }))).toBeNull()
  })

  it('returns null when the exp claim is not a number', () => {
    expect(decodeJwtExpMs(fakeJwt({ exp: 'soon' }))).toBeNull()
  })
})
