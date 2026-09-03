/** Decodes a JWT's `exp` claim (seconds since epoch) into ms since epoch.
 *  This app never needs to *verify* the token client-side — the server is
 *  the real authority, and a bad token just gets a 401 — only read expiry
 *  for a client-side warning. Returns null for anything that doesn't parse
 *  cleanly: a malformed token, a payload that isn't valid base64url/JSON, or
 *  a missing/non-numeric `exp` claim. */
export function decodeJwtExpMs(token: string): number | null {
  const parts = token.split('.')
  if (parts.length !== 3) return null
  try {
    const base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    const padded = base64 + '='.repeat((4 - (base64.length % 4)) % 4)
    const payload = JSON.parse(atob(padded)) as { exp?: unknown }
    return typeof payload.exp === 'number' ? payload.exp * 1000 : null
  } catch {
    return null
  }
}
