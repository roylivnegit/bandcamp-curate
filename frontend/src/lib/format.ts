/** Relative time, matching the old UI's `ago()`. */
export function ago(iso: string | null): string {
  if (!iso) return ''
  const s = (Date.now() - new Date(iso).getTime()) / 1000
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

/** The `<handle>` from `https://<handle>.bandcamp.com/...`, if it looks like one. */
export function bandcampHandle(url: string | null): string {
  if (!url) return ''
  try {
    const m = new URL(url).hostname.match(/^([^.]+)\.bandcamp\.com$/i)
    return m && m[1] !== 'www' ? m[1] : ''
  } catch {
    return ''
  }
}

/** Whether a pasted seed URL is a track or an album (the API decides for real). */
export function seedKind(url: string): 'album' | 'track' {
  return url.toLowerCase().includes('/track/') ? 'track' : 'album'
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return n === 1 ? one : many
}

export const count = (n: number) => n.toLocaleString()
