import { act, fireEvent, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { SCAN_POLL_MS } from '../../config'
import { currentLocation, fakeMe, fakeRec, fakeScan, mockFetch, renderApp } from '../../test/renderApp'

const signedIn = () => localStorage.setItem('crate-digger.token', 'tok')

describe('scan list', () => {
  beforeEach(() => {
    localStorage.clear()
    signedIn()
  })
  afterEach(() => vi.unstubAllGlobals())

  it('lists scans with their status', async () => {
    mockFetch([
      ['/api/auth/me', fakeMe],
      [
        '/api/scans',
        [fakeScan, { ...fakeScan, id: 2, name: 'Psy dig', kind: 'custom', status: 'queued' }],
      ],
    ])
    renderApp('/scans')

    expect(await screen.findByText('My collection')).toBeInTheDocument()
    expect(screen.getByText('Psy dig')).toBeInTheDocument()
    expect(screen.getByText('queued')).toBeInTheDocument()
  })

  it('shows skeleton scan cards while the list loads, then the real ones', async () => {
    // Layout-shift regression: nothing rendered in the gap before scans landed,
    // so the real cards used to pop in. A shaped placeholder should occupy
    // that space instead, and disappear once the real list arrives.
    let releaseScans = () => {}
    const scansHeld = new Promise<void>((resolve) => {
      releaseScans = resolve
    })
    const json = (body: unknown) =>
      new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: string | URL | Request) => {
        const url = String(input)
        if (url.includes('/api/auth/me')) return json(fakeMe)
        if (url.includes('/api/scans')) {
          await scansHeld
          return json([fakeScan])
        }
        throw new Error(`no mock route for ${url}`)
      }),
    )

    renderApp('/scans')

    expect(await screen.findByLabelText('Loading scans…')).toBeInTheDocument()
    expect(screen.queryByText('My collection')).not.toBeInTheDocument()

    await act(async () => {
      releaseScans()
      await new Promise((r) => setTimeout(r, 0))
    })

    expect(await screen.findByText('My collection')).toBeInTheDocument()
    expect(screen.queryByLabelText('Loading scans…')).not.toBeInTheDocument()
  })

  it('tells a brand-new user their collection is still being crawled', async () => {
    // The whole point of `has_crawled`: an empty feed with no explanation is
    // indistinguishable from a broken one.
    mockFetch([
      ['/api/auth/me', { ...fakeMe, has_crawled: false, collection_scan: { id: 1, status: 'queued' } }],
      ['/api/scans', [{ ...fakeScan, status: 'queued', rec_count: 0 }]],
    ])
    renderApp('/scans')

    expect(await screen.findByText(/still crawling/i)).toBeInTheDocument()
  })
})

describe('scan feed', () => {
  beforeEach(() => {
    localStorage.clear()
    signedIn()
  })
  afterEach(() => vi.unstubAllGlobals())

  const feedRoutes = (recs = [fakeRec()]) =>
    [
      ['/api/auth/me', fakeMe],
      ['/api/scans/1', { ...fakeScan, seeds: [] }],
      ['/api/recommendations/count', { count: recs.length }],
      ['/api/recommendations', recs],
      ['/api/facets', { tags: [{ value: 'psybient', label: 'psybient', count: 12 }], labels: [], seed_tags: [] }],
      ['/api/likes', []],
      ['/api/blacklist', []],
    ] as Array<[string, unknown, number?]>

  it('renders a recommendation with its score, artist and reasons', async () => {
    mockFetch(feedRoutes())
    renderApp('/scans/1')

    expect(await screen.findByText('Eyes of Infinity')).toBeInTheDocument()
    expect(screen.getByText('Minds of Infinity')).toBeInTheDocument()
    expect(screen.getByText('3.3')).toBeInTheDocument() // score, 1dp
    expect(screen.getByText(/2 neighbours own this/)).toBeInTheDocument()
  })

  it('shows skeleton recommendation cards while the first page loads', async () => {
    let releaseRecs = () => {}
    const recsHeld = new Promise<void>((resolve) => {
      releaseRecs = resolve
    })
    const json = (body: unknown) =>
      new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: string | URL | Request) => {
        const url = String(input)
        if (url.includes('/api/auth/me')) return json(fakeMe)
        if (url.includes('/api/scans/1')) return json({ ...fakeScan, seeds: [] })
        if (url.includes('/api/likes') || url.includes('/api/blacklist')) return json([])
        if (url.includes('/api/facets')) return json({ tags: [], labels: [], seed_tags: [] })
        if (url.includes('/api/recommendations/count')) return json({ count: 1 })
        if (url.includes('/api/recommendations')) {
          await recsHeld
          return json([fakeRec()])
        }
        throw new Error(`no mock route for ${url}`)
      }),
    )

    renderApp('/scans/1')

    expect(await screen.findByLabelText('Loading recommendations…')).toBeInTheDocument()
    expect(screen.queryByText('Eyes of Infinity')).not.toBeInTheDocument()

    await act(async () => {
      releaseRecs()
      await new Promise((r) => setTimeout(r, 0))
    })

    expect(await screen.findByText('Eyes of Infinity')).toBeInTheDocument()
    expect(screen.queryByLabelText('Loading recommendations…')).not.toBeInTheDocument()
  })

  it('shows the banner instead of the feed while a scan is still running', async () => {
    mockFetch([
      ['/api/auth/me', fakeMe],
      ['/api/scans/1', { ...fakeScan, status: 'running', seeds: [] }],
      ['/api/likes', []],
      ['/api/blacklist', []],
    ])
    renderApp('/scans/1')

    expect(await screen.findByText(/crawling seeds now/i)).toBeInTheDocument()
    expect(screen.queryByText('Eyes of Infinity')).not.toBeInTheDocument()
  })

  it('surfaces a failed scan with its error', async () => {
    mockFetch([
      ['/api/auth/me', fakeMe],
      ['/api/scans/1', { ...fakeScan, status: 'error', error: 'no bandcamp_fan_url set', seeds: [] }],
      ['/api/likes', []],
      ['/api/blacklist', []],
    ])
    renderApp('/scans/1')

    expect(await screen.findByText(/no bandcamp_fan_url set/)).toBeInTheDocument()
  })

  it('adds an include pill when a genre chip on a card is clicked', async () => {
    mockFetch(feedRoutes())
    renderApp('/scans/1')
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'psybient' }))

    // The pill offers the include/exclude toggle the old UI had.
    expect(await screen.findByText(/✓ include/)).toBeInTheDocument()
    // Filters live in the URL now, so this view can be bookmarked or shared —
    // not just held in component state that a reload would lose.
    expect(currentLocation().search).toContain('tag=psybient')
  })

  it('seeds filters from a bookmarked/shared URL instead of always starting blank', async () => {
    // The reverse of the test above: opening a URL that already carries a
    // filter (e.g. a link someone shared, or a reload) must restore it, not
    // require re-clicking it.
    mockFetch(feedRoutes())
    renderApp('/scans/1?item_type=album&tag=psybient')

    expect(await screen.findByText('Eyes of Infinity')).toBeInTheDocument()
    const albumsBtn = screen.getByRole('button', { name: 'Albums' })
    expect(albumsBtn).toHaveAttribute('aria-pressed', 'true')
    expect(await screen.findByRole('button', { name: /✓ include.*psybient/ })).toBeInTheDocument()
  })

  it('keeps a filter in the URL across an unrelated filter change, so back restores it', async () => {
    // A real page navigation (leaving, then hitting browser-back) lands back on
    // whatever URL this page last held — so the fix only holds if a *second*
    // filter change doesn't clobber the first one's query param.
    mockFetch(feedRoutes())
    renderApp('/scans/1')
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'psybient' }))
    expect(currentLocation().search).toContain('tag=psybient')

    await user.click(screen.getByRole('button', { name: 'Albums' }))
    expect(currentLocation().search).toContain('tag=psybient')
    expect(currentLocation().search).toContain('item_type=album')
  })

  it('rejects a non-numeric scan id instead of requesting /api/scans/NaN', async () => {
    const fetchMock = mockFetch([
      ['/api/auth/me', fakeMe],
      ['/api/likes', []],
      ['/api/blacklist', []],
    ])
    renderApp('/scans/not-a-number')

    expect(await screen.findByText(/isn’t a valid scan address/i)).toBeInTheDocument()
    const urls = fetchMock.mock.calls.map(([u]) => String(u))
    expect(urls.some((u) => u.includes('NaN'))).toBe(false)
  })

  it('ignores a page that lands after the filters moved on', async () => {
    // Two filter changes in quick succession, with the first request answering
    // last. Its rows belong to a query the user has already left, so they must
    // not replace the newer ones — the reason loadFirstPage takes a ticket.
    let releaseAlbums = () => {}
    const albumsHeld = new Promise<void>((resolve) => {
      releaseAlbums = resolve
    })
    const json = (body: unknown) =>
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })

    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: string | URL | Request) => {
        const url = String(input)
        if (url.includes('/api/auth/me')) return json(fakeMe)
        if (url.includes('/api/scans/1')) return json({ ...fakeScan, seeds: [] })
        if (url.includes('/api/likes') || url.includes('/api/blacklist')) return json([])
        if (url.includes('/api/facets')) return json({ tags: [], labels: [], seed_tags: [] })
        if (url.includes('/api/recommendations/count')) return json({ count: 1 })
        if (url.includes('/api/recommendations')) {
          if (url.includes('item_type=album')) {
            await albumsHeld
            return json([fakeRec({ title: 'Stale album page', album_id: 11 })])
          }
          if (url.includes('item_type=track')) {
            return json([fakeRec({ title: 'Fresh track page', album_id: 12 })])
          }
          return json([fakeRec({ title: 'Unfiltered page' })])
        }
        throw new Error(`no mock route for ${url}`)
      }),
    )

    renderApp('/scans/1')
    const user = userEvent.setup()
    expect(await screen.findByText('Unfiltered page')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Albums' })) // held in flight
    await user.click(screen.getByRole('button', { name: 'Tracks' })) // answers immediately
    expect(await screen.findByText('Fresh track page')).toBeInTheDocument()

    await act(async () => {
      releaseAlbums()
      await new Promise((r) => setTimeout(r, 0))
    })

    expect(screen.queryByText('Stale album page')).not.toBeInTheDocument()
    expect(screen.getByText('Fresh track page')).toBeInTheDocument()
  })

  it('filters to one artist when the band name is clicked', async () => {
    mockFetch(feedRoutes())
    renderApp('/scans/1')
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: /Minds of Infinity/ }))

    expect(await screen.findByText(/artist:/)).toBeInTheDocument()
    expect(currentLocation().search).toContain('label_id=20')
    expect(currentLocation().search).toContain('label_name=Minds')
  })

  it('clears every stacked filter with one "Clear all filters" click', async () => {
    mockFetch(feedRoutes())
    renderApp('/scans/1')
    const user = userEvent.setup()

    // Stack two filter facets (a genre tag, an artist) plus the item-type
    // segment, which isn't a pill but is part of reset()'s job too.
    await user.click(await screen.findByRole('button', { name: 'psybient' }))
    await user.click(await screen.findByRole('button', { name: /Minds of Infinity/ }))
    await user.click(screen.getByRole('button', { name: 'Albums' }))

    expect(await screen.findByRole('button', { name: /✓ include.*psybient/ })).toBeInTheDocument()
    expect(screen.getByText(/artist:/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Clear all filters' }))

    expect(screen.queryByRole('button', { name: /✓ include.*psybient/ })).not.toBeInTheDocument()
    expect(screen.queryByText(/artist:/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'All' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('does not show "Clear all filters" for a single active facet', async () => {
    mockFetch(feedRoutes())
    renderApp('/scans/1')
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'psybient' }))
    expect(await screen.findByRole('button', { name: /✓ include.*psybient/ })).toBeInTheDocument()

    expect(screen.queryByRole('button', { name: 'Clear all filters' })).not.toBeInTheDocument()
  })
})

describe('feed while the scan is still running', () => {
  beforeEach(() => {
    localStorage.clear()
    signedIn()
  })
  afterEach(() => vi.unstubAllGlobals())

  it('shows recommendations before the scan finishes', async () => {
    // The backend re-curates after every slice, so results accrue during the
    // crawl. Waiting for `done` meant a long scan showed nothing for hours.
    mockFetch([
      ['/api/auth/me', fakeMe],
      ['/api/scans/1', { ...fakeScan, status: 'running', stats: { recommendations: 7 }, seeds: [] }],
      ['/api/recommendations/count', { count: 1 }],
      ['/api/recommendations', [fakeRec()]],
      ['/api/facets', { tags: [], labels: [], seed_tags: [] }],
      ['/api/likes', []],
      ['/api/blacklist', []],
    ])
    renderApp('/scans/1')

    // The card is rendered even though the scan is mid-crawl…
    expect(await screen.findByText(fakeRec().title!)).toBeInTheDocument()
    // …and the banner says so rather than pretending the feed is complete.
    expect(screen.getByText(/7 found so far/i)).toBeInTheDocument()
  })

  it('shows nothing for a queued scan, which has curated nothing yet', async () => {
    mockFetch([
      ['/api/auth/me', fakeMe],
      ['/api/scans/1', { ...fakeScan, status: 'queued', stats: {}, seeds: [] }],
      ['/api/recommendations/count', { count: 0 }],
      ['/api/recommendations', []],
      ['/api/facets', { tags: [], labels: [], seed_tags: [] }],
      ['/api/likes', []],
      ['/api/blacklist', []],
    ])
    renderApp('/scans/1')

    expect(await screen.findByText(/queued/i)).toBeInTheDocument()
  })
})

describe('feed reflow notice', () => {
  beforeEach(() => {
    localStorage.clear()
    signedIn()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  const json = (body: unknown) =>
    new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })

  /** A running scan whose `/api/scans/1` generation is controlled by `gen()`,
   *  so a test can change what the *next* poll returns before advancing the
   *  clock. Everything else behaves like a normal one-item feed. */
  function mockPollingScan(gen: () => number) {
    return vi.fn(async (input: string | URL | Request) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes('/api/auth/me')) return json(fakeMe)
      if (url.includes('/api/scans/1')) {
        return json({
          ...fakeScan,
          status: 'running',
          stats: { recommendations: 1 },
          recompute_generation: gen(),
          seeds: [],
        })
      }
      if (url.includes('/api/likes') || url.includes('/api/blacklist')) return json([])
      if (url.includes('/api/facets')) return json({ tags: [], labels: [], seed_tags: [] })
      if (url.includes('/api/recommendations/count')) return json({ count: 1 })
      if (url.includes('/api/recommendations')) return json([fakeRec()])
      throw new Error(`no mock route for ${url}`)
    })
  }

  it('resets to page 0 and shows a notice when a poll lands a new generation', async () => {
    let generation = 1
    const fetchMock = mockPollingScan(() => generation)
    vi.stubGlobal('fetch', fetchMock)
    vi.useFakeTimers({ shouldAdvanceTime: true })

    renderApp('/scans/1')
    expect(await screen.findByText(fakeRec().title!)).toBeInTheDocument()
    expect(screen.queryByText(/list updated/i)).not.toBeInTheDocument()
    const recFetchesBefore = fetchMock.mock.calls.filter((c) =>
      String(c[0]).includes('/api/recommendations') && !String(c[0]).includes('count'),
    ).length

    // The scan reflowed underneath the reader — same total, different ranking
    // — so the next poll comes back with a new generation.
    generation = 2
    await act(async () => {
      await vi.advanceTimersByTimeAsync(SCAN_POLL_MS)
    })

    expect(await screen.findByText(/list updated/i)).toBeInTheDocument()
    const recFetchesAfter = fetchMock.mock.calls.filter((c) =>
      String(c[0]).includes('/api/recommendations') && !String(c[0]).includes('count'),
    ).length
    expect(recFetchesAfter).toBeGreaterThan(recFetchesBefore) // page 0 was re-fetched

    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }))
    expect(screen.queryByText(/list updated/i)).not.toBeInTheDocument()
  })

  it('does not show the notice when a poll lands the same generation', async () => {
    const generation = 1
    const fetchMock = mockPollingScan(() => generation)
    vi.stubGlobal('fetch', fetchMock)
    vi.useFakeTimers({ shouldAdvanceTime: true })

    renderApp('/scans/1')
    expect(await screen.findByText(fakeRec().title!)).toBeInTheDocument()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(SCAN_POLL_MS)
    })

    expect(screen.queryByText(/list updated/i)).not.toBeInTheDocument()
  })
})
