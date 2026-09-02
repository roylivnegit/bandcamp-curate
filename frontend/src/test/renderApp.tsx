import { render } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { vi } from 'vitest'

import App from '../App'
import { AuthProvider } from '../auth/AuthContext'
import type { Me, Recommendation, Scan } from '../api/types'

/** Written by `LocationWatcher` on every render, so a test can assert on the
 *  URL a filter/navigation change actually produced — MemoryRouter's history
 *  isn't otherwise reachable from outside the tree. Read via `currentLocation()`
 *  rather than destructured at import time, since `renderApp` re-mounts the
 *  tree (and this object) on every call. */
let current = { pathname: '', search: '' }

export function currentLocation() {
  return current
}

function LocationWatcher() {
  const location = useLocation()
  current = { pathname: location.pathname, search: location.search }
  return null
}

/** Mounts the real App (router + auth provider) so tests exercise the actual
 *  routing/session wiring rather than a stand-in. */
export function renderApp(initialPath = '/') {
  current = { pathname: '', search: '' }
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <AuthProvider>
        <LocationWatcher />
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}

export const fakeMe: Me = {
  id: 1,
  username: 'digger',
  bandcamp_fan_url: 'https://bandcamp.com/digger',
  has_crawled: true,
  collection_scan: { id: 1, status: 'done' },
}

export const fakeScan: Scan = {
  id: 1,
  name: 'My collection',
  kind: 'collection',
  status: 'done',
  error: null,
  seed_count: 0,
  rec_count: 2,
  last_run_at: null,
  stats: {},
  recompute_generation: 1,
}

export function fakeRec(over: Partial<Recommendation> = {}): Recommendation {
  return {
    rank: 1,
    item_type: 'album',
    score: 3.25,
    album_id: 10,
    track_id: null,
    title: 'Eyes of Infinity',
    band_id: 20,
    band_name: 'Minds of Infinity',
    url: 'https://mindsofinfinity.bandcamp.com/album/eyes-of-infinity',
    reasons: { co_owners: 2, tag_affinity: 9, matched_tags: ['psybient'], seed_tags: ['ambient'] },
    recompute_generation: 1,
    ...over,
  }
}

/** Routes fetch by URL substring. Unmatched paths fail loudly rather than
 *  silently returning undefined and producing a confusing render. */
export function mockFetch(routes: Array<[string, unknown, number?]>) {
  const fn = vi.fn(async (input: string | URL | Request) => {
    const url = typeof input === 'string' ? input : input.toString()
    for (const [needle, body, status] of routes) {
      if (url.includes(needle)) {
        return new Response(JSON.stringify(body), {
          status: status ?? 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
    }
    throw new Error(`no mock route for ${url}`)
  })
  vi.stubGlobal('fetch', fn)
  return fn
}
