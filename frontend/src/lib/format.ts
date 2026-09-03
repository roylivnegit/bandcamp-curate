/** Relative time, matching the old UI's `ago()`. */
export function ago(iso: string | null): string {
  if (!iso) return ''
  const s = (Date.now() - new Date(iso).getTime()) / 1000
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

/* Hoisted: a literal in the function body is a fresh RegExp object on every
 * call, and this one runs once per rendered feed card. No `/g`, so there's no
 * shared `lastIndex` to leak between calls. */
const BANDCAMP_HOST = /^([^.]+)\.bandcamp\.com$/i

/** The `<handle>` from `https://<handle>.bandcamp.com/...`, if it looks like one. */
export function bandcampHandle(url: string | null): string {
  if (!url) return ''
  try {
    const m = BANDCAMP_HOST.exec(new URL(url).hostname)
    return m && m[1] !== 'www' ? m[1] : ''
  } catch {
    return ''
  }
}

/** Whether a pasted seed URL is a track or an album (the API decides for real). */
export function seedKind(url: string): 'album' | 'track' {
  return url.toLowerCase().includes('/track/') ? 'track' : 'album'
}

// A fan's collection page always lives at bandcamp.com/<handle> — unlike album/track
// URLs (SEED_URL_RE in NewScanForm.tsx), which are hosted per-artist and deliberately
// accept any host. The backend itself only checks non-empty (`api/auth.py`), so this
// is strictly a UI-side early-feedback check, not a stricter gate than the API's.
const FAN_URL_RE = /^https?:\/\/bandcamp\.com\/[^/?#]+\/?(?:[?#].*)?$/i

/** Whether a string looks like a Bandcamp fan-collection URL (https://bandcamp.com/<handle>). */
export function isValidFanUrl(url: string): boolean {
  return FAN_URL_RE.test(url.trim())
}

/** "expires in Xm/Xh/Xd" for a temporary block's `expires_at`, or '' for a
 *  permanent one (`null`) or one that's already lapsed — the backend's own
 *  `expires_at > now()` filter keeps a lapsed row out of `GET /api/blacklist`
 *  in the first place, so this is a display nicety, not the enforcement. */
export function expiresLabel(iso: string | null): string {
  if (!iso) return ''
  const ms = new Date(iso).getTime() - Date.now()
  if (ms <= 0) return ''
  const s = ms / 1000
  if (s < 3600) return `expires in ${Math.max(1, Math.round(s / 60))}m`
  if (s < 86400) return `expires in ${Math.round(s / 3600)}h`
  return `expires in ${Math.round(s / 86400)}d`
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return n === 1 ? one : many
}

export const count = (n: number) => n.toLocaleString()
