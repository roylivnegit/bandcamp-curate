import { SESSION_EXPIRY_WARNING_MS } from '../config'
import { decodeJwtExpMs } from './jwt'

/** How long, in ms, until a "session expiring soon" warning should fire for
 *  `token` — or null if there's nothing to schedule: the token carries no
 *  readable `exp` claim, or it's already past expiry (the existing 401
 *  handler covers that case; warning about it after the fact would be
 *  pointless). If less than the warning window remains, warns immediately
 *  (0) rather than not at all. Pure so it's testable against fabricated
 *  tokens/clock values with no timers involved. */
export function msUntilWarning(token: string, nowMs: number): number | null {
  const expMs = decodeJwtExpMs(token)
  if (expMs === null) return null
  const msUntilExpiry = expMs - nowMs
  if (msUntilExpiry <= 0) return null
  return Math.max(msUntilExpiry - SESSION_EXPIRY_WARNING_MS, 0)
}
