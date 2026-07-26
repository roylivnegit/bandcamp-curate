/* The single place that talks to the API.
 *
 * A 401 anywhere means the token is gone or stale, so it's handled centrally:
 * clear it and notify listeners, rather than making every caller check.
 *
 * ── On keeping the token in localStorage ──────────────────────────────────
 * This is a known trade, not an oversight. localStorage is readable by any
 * script on this origin, so an XSS or a compromised dependency could exfiltrate
 * the token and use it until it expires (auth_token_ttl_days, 30 by default).
 *
 * The stronger alternative is an httpOnly cookie, which script can't read — but
 * that needs the API on the same site as this app, or SameSite=None + Secure +
 * credentialed CORS, plus CSRF protection that bearer tokens don't need. The
 * frontend and API are deliberately separate services here, which is what made
 * a bearer token the right fit in the first place.
 *
 * What actually bounds the risk today: no third-party scripts are loaded, the
 * dependency surface is small, sign-up is invite-gated, and the data is a music
 * recommendation feed rather than anything sensitive. If any of that changes —
 * especially loading third-party script — revisit this, because the mitigation
 * (same-site cookies) is an architecture change, not a patch.
 */

import type {
  Blocked,
  Facets,
  ItemRef,
  Liked,
  Me,
  Recommendation,
  Scan,
  ScanDetail,
  Stats,
  TokenResponse,
} from './types'

const BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')
const TOKEN_KEY = 'crate-digger.token'

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

// ── token storage ───────────────────────────────────────────────────────────

let onUnauthorized: (() => void) | null = null

/** Registered by AuthProvider so a 401 from any call can drop the session. */
export function setUnauthorizedHandler(fn: (() => void) | null): void {
  onUnauthorized = fn
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null // private-mode / storage-disabled: behave as logged out
  }
}

export function setToken(token: string | null): void {
  try {
    if (token === null) localStorage.removeItem(TOKEN_KEY)
    else localStorage.setItem(TOKEN_KEY, token)
  } catch {
    /* non-fatal: the session just won't survive a reload */
  }
}

// ── core request ────────────────────────────────────────────────────────────

/* On these, a 401/403 is a verdict on the credentials just submitted — not an
 * expired session. Treating them like one would sign the user out mid-login and
 * replace "wrong password" with a nonsensical "your session expired". */
const CREDENTIAL_PATHS = ['/api/auth/login', '/api/auth/signup']

async function request<T>(
  path: string,
  { method = 'GET', body }: { method?: string; body?: unknown } = {},
): Promise<T> {
  const token = getToken()
  const headers: Record<string, string> = {}
  if (token) headers.Authorization = `Bearer ${token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    // Network-level failure: the API is asleep (Render free tier cold-starts) or
    // unreachable. Say something a person can act on.
    throw new ApiError(0, "Can't reach the server. It may be waking up — try again in a moment.")
  }

  if (res.status === 401 && !CREDENTIAL_PATHS.includes(path)) {
    setToken(null)
    onUnauthorized?.()
    throw new ApiError(401, 'Your session expired. Please sign in again.')
  }

  if (!res.ok) {
    throw new ApiError(res.status, await errorDetail(res))
  }

  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

/** FastAPI puts the message in `detail` — a string, or a list for validation errors. */
async function errorDetail(res: Response): Promise<string> {
  try {
    const data = await res.json()
    const d = data?.detail
    if (typeof d === 'string') return d
    if (Array.isArray(d) && d.length) {
      const first = d[0]
      if (typeof first?.msg === 'string') return first.msg
    }
  } catch {
    /* fall through to the generic message */
  }
  return `Request failed (${res.status})`
}

// ── query building ──────────────────────────────────────────────────────────

export interface FeedFilterParams {
  scanId?: number | null
  itemType?: '' | 'album' | 'track'
  /** genre tag -> include ('by') or exclude ('out') */
  tags?: Record<string, 'by' | 'out'>
  /** substring match on tag names -> include or exclude */
  tagContains?: Record<string, 'by' | 'out'>
  labelId?: number | null
}

/** Filters as the API expects them: repeated keys, not comma-joined lists. */
export function filterQuery(f: FeedFilterParams): URLSearchParams {
  const q = new URLSearchParams()
  if (f.scanId != null) q.set('scan_id', String(f.scanId))
  if (f.itemType) q.set('item_type', f.itemType)
  for (const [tag, mode] of Object.entries(f.tags ?? {})) {
    q.append(mode === 'out' ? 'exclude_tag' : 'tag', tag)
  }
  for (const [text, mode] of Object.entries(f.tagContains ?? {})) {
    q.append(mode === 'out' ? 'exclude_tag_contains' : 'tag_contains', text)
  }
  if (f.labelId != null) q.set('label_id', String(f.labelId))
  return q
}

// ── endpoints ───────────────────────────────────────────────────────────────

export const api = {
  // auth
  signup: (body: {
    username: string
    password: string
    bandcamp_fan_url: string
    invite_code: string
  }) => request<TokenResponse>('/api/auth/signup', { method: 'POST', body }),

  login: (body: { username: string; password: string }) =>
    request<TokenResponse>('/api/auth/login', { method: 'POST', body }),

  me: () => request<Me>('/api/auth/me'),

  // scans
  listScans: () => request<Scan[]>('/api/scans'),
  getScan: (id: number) => request<ScanDetail>(`/api/scans/${id}`),
  createScan: (body: { name: string; seeds: string[] }) =>
    request<ScanDetail>('/api/scans', { method: 'POST', body }),
  runScan: (id: number) => request<ScanDetail>(`/api/scans/${id}/run`, { method: 'POST' }),
  deleteScan: (id: number) => request<{ deleted: number }>(`/api/scans/${id}`, { method: 'DELETE' }),

  // feed
  stats: (scanId?: number | null) =>
    request<Stats>(`/api/stats${scanId != null ? `?scan_id=${scanId}` : ''}`),

  recommendations: (f: FeedFilterParams, opts: { sort: string; limit: number; offset: number }) => {
    const q = filterQuery(f)
    q.set('sort', opts.sort)
    q.set('limit', String(opts.limit))
    q.set('offset', String(opts.offset))
    return request<Recommendation[]>(`/api/recommendations?${q}`)
  },

  recommendationsCount: (f: FeedFilterParams) =>
    request<{ count: number }>(`/api/recommendations/count?${filterQuery(f)}`),

  facets: (scanId?: number | null) =>
    request<Facets>(`/api/facets${scanId != null ? `?scan_id=${scanId}` : ''}`),

  recompute: (scanId?: number | null, excludeSeedTags: string[] = []) => {
    const q = new URLSearchParams()
    if (scanId != null) q.set('scan_id', String(scanId))
    for (const t of excludeSeedTags) q.append('exclude_seed_tag', t)
    return request<{ computed: number; excluded_seed_tags: string[] }>(
      `/api/recommendations/recompute?${q}`,
      { method: 'POST' },
    )
  },

  // likes / blocks (both global across a user's scans)
  listLikes: () => request<Liked[]>('/api/likes'),
  like: (ref: ItemRef) => request<Liked>('/api/likes', { method: 'POST', body: ref }),
  unlike: (ref: ItemRef) => request<{ unliked: boolean }>('/api/likes/unlike', {
    method: 'POST',
    body: ref,
  }),

  listBlocked: () => request<Blocked[]>('/api/blacklist'),
  block: (bandId: number) =>
    request<Blocked>('/api/blacklist', { method: 'POST', body: { band_id: bandId } }),
  unblock: (bandId: number) =>
    request<{ unblocked: number }>(`/api/blacklist/${bandId}/unblock`, { method: 'POST' }),
}
