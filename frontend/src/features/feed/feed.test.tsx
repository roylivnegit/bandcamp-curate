import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { CARD_EXIT_MS, SCAN_POLL_MS, UNDO_WINDOW_MS } from '../../config'
import { triggerIntersections } from '../../test/intersectionObserver'
import { resetToastsForTests } from '../../lib/toast'
import { currentLocation, fakeMe, fakeRec, fakeScan, mockFetch, renderApp } from '../../test/renderApp'

const signedIn = () => localStorage.setItem('crate-digger.token', 'tok')

// The toast queue (lib/toast.ts) is module-scope by design, so a toast raised
// by one test (like/block/undoRetire failures now show one) would otherwise
// leak into whichever test runs next in this file — same cross-test leakage
// ToastStack.test.tsx already guards against.
beforeEach(() => resetToastsForTests())

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

  it('renders a recommendation with its artist and reasons, but no visible score', async () => {
    mockFetch(feedRoutes())
    renderApp('/scans/1')

    expect(await screen.findByText('Eyes of Infinity')).toBeInTheDocument()
    expect(screen.getByText('Minds of Infinity')).toBeInTheDocument()
    expect(screen.getByText(/2 neighbours own this/)).toBeInTheDocument()
    // The score still drives ranking/sorting server-side — it's just not shown.
    expect(screen.queryByText('3.3')).not.toBeInTheDocument()
  })

  it('auto-loads the next page when the sentinel scrolls into view, with no button', async () => {
    // A full first page (LIMIT=50 items) with more available server-side
    // (count > page length) is what keeps `done` false and the sentinel
    // mounted at all (`done` is `page.length < LIMIT`).
    const firstPage = Array.from({ length: 50 }, (_, i) => fakeRec({ album_id: i + 1, title: `Album ${i + 1}` }))
    const secondPage = [fakeRec({ album_id: 51, title: 'Album 51' })]
    const fetchMock = mockFetch([
      ['/api/auth/me', fakeMe],
      ['/api/scans/1', { ...fakeScan, seeds: [] }],
      ['/api/recommendations/count', { count: 51 }],
      ['/api/recommendations', firstPage],
      ['/api/facets', { tags: [], labels: [], seed_tags: [] }],
      ['/api/likes', []],
      ['/api/blacklist', []],
    ])
    renderApp('/scans/1')
    await screen.findByText('Album 1')

    expect(screen.queryByRole('button', { name: /load more/i })).not.toBeInTheDocument()
    expect(screen.queryByText('Album 51')).not.toBeInTheDocument()

    // The next fetch (the second page) resolves with `secondPage` — swap the
    // mock's routing for /api/recommendations before triggering the sentinel.
    fetchMock.mockImplementation(async (input: string | URL | Request) => {
      const url = typeof input === 'string' ? input : input.toString()
      const json = (body: unknown) =>
        new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
      if (url.includes('/api/recommendations')) return json(secondPage)
      throw new Error(`no mock route for ${url}`)
    })
    triggerIntersections()

    expect(await screen.findByText('Album 51')).toBeInTheDocument()
  })

  it('announces the match count to screen readers, and it updates as the count changes', async () => {
    // The countline text visibly changes whenever `total` does (e.g. a
    // like/block decrementing it) but was a plain <p> with no aria-live, so a
    // screen-reader user got no confirmation anything happened.
    mockFetch(feedRoutes())
    vi.useFakeTimers({ shouldAdvanceTime: true })

    renderApp('/scans/1')
    expect(await screen.findByText('Eyes of Infinity')).toBeInTheDocument()

    const countline = screen.getByRole('status')
    expect(countline).toHaveTextContent('1 results')

    fireEvent.click(screen.getByRole('button', { name: '♥ like' }))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(CARD_EXIT_MS)
    })

    expect(countline).toHaveTextContent('0 results')
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

  it('collapses the secondary filter controls behind a toggle, off by default', async () => {
    // Actually hiding `#filterbar-more` is a mobile-only CSS media query
    // (jsdom doesn't evaluate those, so it isn't meaningfully testable here)
    // — what IS real component behavior, and what this covers, is the
    // collapse/expand state itself and which controls it gates.
    mockFetch(feedRoutes())
    renderApp('/scans/1')
    const user = userEvent.setup()
    await screen.findByText('Eyes of Infinity')

    const toggle = screen.getByRole('button', { name: '▾ More filters' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    // Always-visible controls are direct children of `.controls`, not gated.
    expect(screen.getByRole('button', { name: 'All' })).toBeInTheDocument()
    expect(screen.getByPlaceholderText('Search (/)')).toBeInTheDocument()
    // Gated behind the toggle: present in the DOM (desktop shows them via
    // `display: contents`, unaffected by this state) but the wrapper isn't
    // marked open yet.
    const more = document.getElementById('filterbar-more')
    expect(more).not.toHaveClass('open')
    expect(screen.getByRole('button', { name: /Sort ·/ })).toBeInTheDocument()

    await user.click(toggle)

    expect(screen.getByRole('button', { name: '▲ Fewer filters' })).toHaveAttribute(
      'aria-expanded',
      'true',
    )
    expect(more).toHaveClass('open')
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

  it('treats an empty label_id in the URL as no artist filter, not band id 0', async () => {
    // Number('') is 0, which Number.isInteger accepts — a hand-edited or
    // partially-stripped bookmarked URL (`?label_id=` with nothing after the
    // `=`) must not silently turn into "filtered to band 0".
    mockFetch(feedRoutes())
    renderApp('/scans/1?label_id=')

    expect(await screen.findByText('Eyes of Infinity')).toBeInTheDocument()
    expect(screen.queryByText(/artist:/)).not.toBeInTheDocument()
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

  it('offers a "Clear filters" button in the zero-result empty state, even for a single facet', async () => {
    // The "Clear all filters" pill only shows once 2+ facets stack, so a
    // single active filter that zeroes out the feed otherwise has no
    // clear-action anywhere on screen.
    mockFetch(feedRoutes([]))
    renderApp('/scans/1?tag=psybient')
    const user = userEvent.setup()

    expect(await screen.findByText('Nothing matches these filters — try clearing one.')).toBeInTheDocument()
    expect(currentLocation().search).toContain('tag=psybient')

    await user.click(screen.getByRole('button', { name: 'Clear filters' }))

    expect(currentLocation().search).not.toContain('tag=psybient')
  })

  const threeRecs = [
    fakeRec({ album_id: 1, title: 'First album' }),
    fakeRec({ album_id: 2, title: 'Second album' }),
    fakeRec({ album_id: 3, title: 'Third album' }),
  ]

  it('starts with only the first card as a tab stop, and ArrowDown moves it to the next', async () => {
    mockFetch(feedRoutes(threeRecs))
    renderApp('/scans/1')
    await screen.findByText('First album')

    const cards = screen.getAllByRole('article')
    expect(cards).toHaveLength(3)
    expect(cards[0]).toHaveAttribute('tabindex', '0')
    expect(cards[1]).toHaveAttribute('tabindex', '-1')
    expect(cards[2]).toHaveAttribute('tabindex', '-1')

    cards[0].focus()
    fireEvent.keyDown(cards[0], { key: 'ArrowDown' })

    expect(cards[0]).toHaveAttribute('tabindex', '-1')
    expect(cards[1]).toHaveAttribute('tabindex', '0')
    expect(document.activeElement).toBe(cards[1])
  })

  it('does not move past the first card on ArrowUp, or the last on ArrowDown', async () => {
    mockFetch(feedRoutes(threeRecs))
    renderApp('/scans/1')
    await screen.findByText('First album')

    const cards = screen.getAllByRole('article')
    cards[0].focus()
    fireEvent.keyDown(cards[0], { key: 'ArrowUp' })
    expect(document.activeElement).toBe(cards[0])

    fireEvent.keyDown(cards[0], { key: 'End' })
    expect(document.activeElement).toBe(cards[2])

    fireEvent.keyDown(cards[2], { key: 'ArrowDown' })
    expect(document.activeElement).toBe(cards[2])

    fireEvent.keyDown(cards[2], { key: 'Home' })
    expect(document.activeElement).toBe(cards[0])
  })

  it('narrows the rendered cards to a title/band match, with no new fetch', async () => {
    mockFetch(feedRoutes(threeRecs))
    renderApp('/scans/1')
    await screen.findByText('First album')
    expect(screen.getAllByRole('article')).toHaveLength(3)

    const user = userEvent.setup()
    await user.type(screen.getByPlaceholderText('Search (/)'), 'second')

    expect(screen.getAllByRole('article')).toHaveLength(1)
    expect(screen.getByText('Second album')).toBeInTheDocument()
  })

  it('shows a distinct empty message when the quick filter matches nothing, not the real empty state', async () => {
    mockFetch(feedRoutes(threeRecs))
    renderApp('/scans/1')
    await screen.findByText('First album')

    const user = userEvent.setup()
    await user.type(screen.getByPlaceholderText('Search (/)'), 'nonexistent-xyz')

    expect(await screen.findByText('No loaded cards match “nonexistent-xyz”.')).toBeInTheDocument()
    expect(screen.queryByText('No recommendations in this scan yet.')).not.toBeInTheDocument()
  })

  it('"/" focuses the quick filter input from anywhere on the page', async () => {
    mockFetch(feedRoutes(threeRecs))
    renderApp('/scans/1')
    await screen.findByText('First album')

    fireEvent.keyDown(document, { key: '/' })

    expect(document.activeElement).toBe(screen.getByPlaceholderText('Search (/)'))
  })

  const bulkRecs = [
    fakeRec({ album_id: 1, band_id: 101, title: 'First album', band_name: 'Band One' }),
    fakeRec({ album_id: 2, band_id: 102, title: 'Second album', band_name: 'Band Two' }),
    fakeRec({ album_id: 3, band_id: 103, title: 'Third album', band_name: 'Band Three' }),
  ]

  it('offers no checkboxes or bulk bar until select mode is turned on', async () => {
    mockFetch(feedRoutes(bulkRecs))
    renderApp('/scans/1')
    await screen.findByText('First album')

    expect(screen.queryAllByRole('checkbox')).toHaveLength(0)
    expect(screen.queryByText('selected')).not.toBeInTheDocument()
  })

  it('selecting two cards and clicking "Block selected" blocks exactly those two bands, then clears the selection', async () => {
    const fetchMock = mockFetch(feedRoutes(bulkRecs))
    renderApp('/scans/1')
    await screen.findByText('First album')
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: '☑ Select' }))
    const checkboxes = screen.getAllByRole('checkbox')
    expect(checkboxes).toHaveLength(3)

    await user.click(checkboxes[0])
    await user.click(checkboxes[1])

    expect(await screen.findByText('2')).toBeInTheDocument()
    expect(screen.getByText('selected')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Block selected' }))

    await waitFor(() => {
      const blockCalls = fetchMock.mock.calls.filter(([u, init]) => {
        const url = String(u)
        return url.includes('/api/blacklist') && !url.includes('unblock') && init?.method === 'POST'
      })
      expect(blockCalls).toHaveLength(2)
      const blockedIds = blockCalls
        .map(([, init]) => JSON.parse(String(init?.body)).band_id)
        .sort((a: number, b: number) => a - b)
      expect(blockedIds).toEqual([101, 102])
    })

    // Selection clears and select mode exits once the batch settles.
    await waitFor(() => {
      expect(screen.queryByText('selected')).not.toBeInTheDocument()
      expect(screen.queryAllByRole('checkbox')).toHaveLength(0)
    })
  })

  it('"Cancel" in the bulk bar clears the selection without blocking anything', async () => {
    const fetchMock = mockFetch(feedRoutes(bulkRecs))
    renderApp('/scans/1')
    await screen.findByText('First album')
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: '☑ Select' }))
    await user.click(screen.getAllByRole('checkbox')[0])
    expect(await screen.findByText('1')).toBeInTheDocument()
    expect(screen.getByText('selected')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(screen.queryByText('selected')).not.toBeInTheDocument()
    expect(
      fetchMock.mock.calls.some(([u, init]) => {
        const url = String(u)
        return url.includes('/api/blacklist') && !url.includes('unblock') && init?.method === 'POST'
      }),
    ).toBe(false)
  })

  it('"Select all loaded" checks every visible card, and a second click clears them all', async () => {
    mockFetch(feedRoutes(bulkRecs))
    renderApp('/scans/1')
    await screen.findByText('First album')
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: '☑ Select' }))
    expect(screen.queryByRole('button', { name: /select all loaded/i })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /select all loaded/i }))

    const checkboxes = screen.getAllByRole('checkbox') as HTMLInputElement[]
    expect(checkboxes).toHaveLength(3)
    expect(checkboxes.every((cb) => cb.checked)).toBe(true)
    // The feed's own countline also reads "3" here (unfiltered total), so
    // scope the count assertion to the bulk bar rather than a bare
    // `findByText('3')`, which would ambiguously match both.
    const bulkBar = await screen.findByText('selected')
    expect(within(bulkBar.closest('.bulkbar')!).getByText('3')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /deselect all/i }))

    expect(screen.getAllByRole('checkbox').every((cb) => !(cb as HTMLInputElement).checked)).toBe(true)
    expect(screen.queryByText('selected')).not.toBeInTheDocument()
  })

  it('"Select all loaded" only offers what quick-filter narrowed to', async () => {
    mockFetch(feedRoutes(bulkRecs))
    renderApp('/scans/1')
    await screen.findByText('First album')
    const user = userEvent.setup()

    await user.type(screen.getByPlaceholderText('Search (/)'), 'Second')
    await screen.findByText('Second album')
    expect(screen.queryByText('First album')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '☑ Select' }))
    await user.click(screen.getByRole('button', { name: /select all loaded/i }))

    expect(screen.getAllByRole('checkbox')).toHaveLength(1)
    expect(await screen.findByText('1')).toBeInTheDocument()
  })
})

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('initial page-load failure', () => {
  beforeEach(() => {
    localStorage.clear()
    signedIn()
  })
  afterEach(() => vi.unstubAllGlobals())

  it('offers a Retry button when the scan list fails to load, which re-fetches on click', async () => {
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes('/api/auth/me')) return jsonResponse(fakeMe)
      if (url.includes('/api/scans')) return jsonResponse({ detail: 'boom' }, 500)
      throw new Error(`no mock route for ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderApp('/scans')
    const retry = await screen.findByRole('button', { name: 'Retry' })
    expect(screen.getByRole('alert')).toBeInTheDocument()

    fetchMock.mockImplementation(async (input: string | URL | Request) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes('/api/auth/me')) return jsonResponse(fakeMe)
      if (url.includes('/api/scans')) return jsonResponse([fakeScan])
      throw new Error(`no mock route for ${url}`)
    })
    fireEvent.click(retry)

    expect(await screen.findByText('My collection')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('offers a Retry button when the scan itself fails to load, which re-fetches on click', async () => {
    // Distinct from the scan-list case: ScanFeedPage's in-feed `error` state
    // only renders inside `showFeed`, which requires `scan !== null` — so a
    // failed *initial* loadScan() left the page silently stuck on "Loading…"
    // before this fix. This pins the separate `scanError` surface instead.
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes('/api/auth/me')) return jsonResponse(fakeMe)
      if (url.includes('/api/scans/1')) return jsonResponse({ detail: 'boom' }, 500)
      throw new Error(`no mock route for ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderApp('/scans/1')
    const retry = await screen.findByRole('button', { name: 'Retry' })
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.getByText('Loading…')).toBeInTheDocument()

    fetchMock.mockImplementation(async (input: string | URL | Request) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes('/api/auth/me')) return jsonResponse(fakeMe)
      if (url.includes('/api/scans/1')) return jsonResponse({ ...fakeScan, seeds: [] })
      if (url.includes('/api/recommendations/count')) return jsonResponse({ count: 0 })
      if (url.includes('/api/recommendations')) return jsonResponse([])
      if (url.includes('/api/facets')) return jsonResponse({ tags: [], labels: [], seed_tags: [] })
      if (url.includes('/api/likes')) return jsonResponse([])
      if (url.includes('/api/blacklist')) return jsonResponse([])
      throw new Error(`no mock route for ${url}`)
    })
    fireEvent.click(retry)

    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
    expect(screen.getByText('My collection')).toBeInTheDocument()
  })
})

describe('delete scan', () => {
  beforeEach(() => {
    localStorage.clear()
    signedIn()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

  /** `deleteOk: false` fails the DELETE call (a 400, mirroring the backend's
   *  real "the collection scan can't be deleted" response shape) so a test
   *  can exercise the error path without touching the collection-scan guard,
   *  which is rendered client-side instead (see the "collection scans" test
   *  below). */
  function mockCustomScan({ deleteOk = true } = {}) {
    return vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes('/api/auth/me')) return json(fakeMe)
      if (url.includes('/api/scans/1') && init?.method === 'DELETE') {
        return deleteOk ? json({ deleted: 1 }) : json({ detail: 'nope' }, 400)
      }
      if (url.includes('/api/scans/1')) return json({ ...fakeScan, id: 1, kind: 'custom', seeds: [] })
      if (url.includes('/api/likes') || url.includes('/api/blacklist')) return json([])
      if (url.includes('/api/facets')) return json({ tags: [], labels: [], seed_tags: [] })
      if (url.includes('/api/recommendations/count')) return json({ count: 1 })
      if (url.includes('/api/recommendations')) return json([fakeRec()])
      throw new Error(`no mock route for ${url}`)
    })
  }

  it('does not render for the collection scan', async () => {
    mockFetch([
      ['/api/auth/me', fakeMe],
      ['/api/scans/1', { ...fakeScan, seeds: [] }], // fakeScan defaults to kind: 'collection'
      ['/api/recommendations/count', { count: 1 }],
      ['/api/recommendations', [fakeRec()]],
      ['/api/facets', { tags: [], labels: [], seed_tags: [] }],
      ['/api/likes', []],
      ['/api/blacklist', []],
    ])
    renderApp('/scans/1')

    await screen.findByText('Eyes of Infinity')
    expect(screen.queryByRole('button', { name: /Delete scan/ })).not.toBeInTheDocument()
  })

  it('requires a second click, and reverts if the second click never comes', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.stubGlobal('fetch', mockCustomScan())

    renderApp('/scans/1')
    const deleteBtn = await screen.findByRole('button', { name: 'Delete scan "My collection"' })

    fireEvent.click(deleteBtn)
    expect(await screen.findByRole('button', { name: 'Confirm delete?' })).toBeInTheDocument()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000)
    })

    expect(screen.queryByRole('button', { name: 'Confirm delete?' })).not.toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'Delete scan "My collection"' })).toBeInTheDocument()
  })

  it('"Cancel" reverts immediately without ever calling the API', async () => {
    const fetchMock = mockCustomScan()
    vi.stubGlobal('fetch', fetchMock)

    renderApp('/scans/1')
    fireEvent.click(await screen.findByRole('button', { name: 'Delete scan "My collection"' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Cancel' }))

    expect(await screen.findByRole('button', { name: 'Delete scan "My collection"' })).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(false)
  })

  it('confirming deletes the scan and returns to the scans list', async () => {
    vi.stubGlobal('fetch', mockCustomScan())

    renderApp('/scans/1')
    fireEvent.click(await screen.findByRole('button', { name: 'Delete scan "My collection"' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Confirm delete?' }))

    await waitFor(() => expect(currentLocation().pathname).toBe('/scans'))
  })

  it('a failed delete shows an error and leaves the scan in place', async () => {
    vi.stubGlobal('fetch', mockCustomScan({ deleteOk: false }))

    renderApp('/scans/1')
    fireEvent.click(await screen.findByRole('button', { name: 'Delete scan "My collection"' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Confirm delete?' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('nope')
    expect(await screen.findByRole('button', { name: 'Delete scan "My collection"' })).toBeInTheDocument()
    expect(currentLocation().pathname).toBe('/scans/1')
  })
})

describe('focus on route change', () => {
  beforeEach(() => {
    localStorage.clear()
    signedIn()
  })
  afterEach(() => vi.unstubAllGlobals())

  // '/api/scans/1' must be listed before '/api/scans' — mockFetch matches by
  // substring in order, and the list route would otherwise swallow it too.
  const combinedRoutes: Array<[string, unknown, number?]> = [
    ['/api/auth/me', fakeMe],
    ['/api/scans/1', { ...fakeScan, seeds: [] }],
    ['/api/scans', [fakeScan]],
    ['/api/recommendations/count', { count: 1 }],
    ['/api/recommendations', [fakeRec()]],
    ['/api/facets', { tags: [], labels: [], seed_tags: [] }],
    ['/api/likes', []],
    ['/api/blacklist', []],
  ]

  it('moves focus to the page heading on landing, and again after navigating to another page', async () => {
    mockFetch(combinedRoutes)
    const user = userEvent.setup()
    renderApp('/scans')

    expect(await screen.findByRole('heading', { name: 'Your scans' })).toHaveFocus()

    await user.click(await screen.findByRole('link', { name: /My collection/ }))
    expect(await screen.findByRole('heading', { name: /My collection/ })).toHaveFocus()

    await user.click(screen.getByRole('link', { name: /Scans/ }))
    expect(await screen.findByRole('heading', { name: 'Your scans' })).toHaveFocus()
  })
})

describe('document title', () => {
  beforeEach(() => {
    localStorage.clear()
    signedIn()
  })
  afterEach(() => vi.unstubAllGlobals())

  // '/api/scans/1' must be listed before '/api/scans' — mockFetch matches by
  // substring in order, and the list route would otherwise swallow it too.
  const combinedRoutes: Array<[string, unknown, number?]> = [
    ['/api/auth/me', fakeMe],
    ['/api/scans/1', { ...fakeScan, seeds: [] }],
    ['/api/scans', [fakeScan]],
    ['/api/recommendations/count', { count: 1 }],
    ['/api/recommendations', [fakeRec()]],
    ['/api/facets', { tags: [], labels: [], seed_tags: [] }],
    ['/api/likes', []],
    ['/api/blacklist', []],
  ]

  it('reflects the current page in the tab/history title, and updates on navigation', async () => {
    mockFetch(combinedRoutes)
    const user = userEvent.setup()
    renderApp('/scans')

    await screen.findByRole('heading', { name: 'Your scans' })
    expect(document.title).toBe('Scans · bandcamp music finder')

    await user.click(await screen.findByRole('link', { name: /My collection/ }))
    await screen.findByRole('heading', { name: /My collection/ })
    expect(document.title).toBe('My collection · bandcamp music finder')

    await user.click(screen.getByRole('link', { name: /Scans/ }))
    await screen.findByRole('heading', { name: 'Your scans' })
    expect(document.title).toBe('Scans · bandcamp music finder')
  })

  it('marks the tab title when a scan finishes while the tab is hidden, and clears it on refocus', async () => {
    const json = (body: unknown) =>
      new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
    const state = { status: 'running' as 'running' | 'done' }
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: string | URL | Request) => {
        const url = String(input)
        if (url.includes('/api/auth/me')) return json(fakeMe)
        if (url.includes('/api/scans/1')) return json({ ...fakeScan, status: state.status, seeds: [] })
        if (url.includes('/api/recommendations/count')) return json({ count: 1 })
        if (url.includes('/api/recommendations')) return json([fakeRec()])
        if (url.includes('/api/facets')) return json({ tags: [], labels: [], seed_tags: [] })
        if (url.includes('/api/likes') || url.includes('/api/blacklist')) return json([])
        throw new Error(`no mock route for ${url}`)
      }),
    )
    Object.defineProperty(document, 'hidden', { configurable: true, value: true })
    vi.useFakeTimers({ shouldAdvanceTime: true })

    renderApp('/scans/1')
    await screen.findByText('Eyes of Infinity')
    expect(document.title).toBe('My collection · bandcamp music finder')

    state.status = 'done'
    await act(async () => {
      await vi.advanceTimersByTimeAsync(SCAN_POLL_MS)
    })
    expect(document.title).toBe('✓ My collection · bandcamp music finder')

    await act(async () => {
      Object.defineProperty(document, 'hidden', { configurable: true, value: false })
      document.dispatchEvent(new Event('visibilitychange'))
    })
    expect(document.title).toBe('My collection · bandcamp music finder')

    Object.defineProperty(document, 'hidden', { configurable: true, value: false })
    vi.useRealTimers()
  })
})

describe('skip to content', () => {
  beforeEach(() => {
    localStorage.clear()
    signedIn()
  })
  afterEach(() => vi.unstubAllGlobals())

  it('offers a skip-to-content link ahead of the header, targeting the shared main landmark', async () => {
    mockFetch([
      ['/api/auth/me', fakeMe],
      ['/api/scans', [fakeScan]],
    ])
    renderApp('/scans')

    const skipLink = await screen.findByRole('link', { name: 'Skip to content' })
    expect(skipLink).toHaveAttribute('href', '#main-content')

    const main = document.getElementById('main-content')
    expect(main?.tagName).toBe('MAIN')

    // Must be reachable by a single Tab from page load, before the header's
    // own content — not just present somewhere in the document.
    const header = screen.getByRole('banner')
    expect(skipLink.compareDocumentPosition(header) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })
})

describe('undo after like/block', () => {
  beforeEach(() => {
    localStorage.clear()
    signedIn()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  const feedRoutes = (recs = [fakeRec()]) =>
    [
      ['/api/auth/me', fakeMe],
      ['/api/scans/1', { ...fakeScan, seeds: [] }],
      ['/api/recommendations/count', { count: recs.length }],
      ['/api/recommendations', recs],
      ['/api/facets', { tags: [], labels: [], seed_tags: [] }],
      ['/api/likes', []],
      ['/api/blacklist', []],
    ] as Array<[string, unknown, number?]>

  const recFetchCount = (fetchMock: ReturnType<typeof mockFetch>) =>
    fetchMock.mock.calls.filter(
      (c) => String(c[0]).includes('/api/recommendations') && !String(c[0]).includes('count'),
    ).length

  it('offers Undo after liking a card, and undo restores it without a network refetch', async () => {
    const fetchMock = mockFetch(feedRoutes())
    vi.useFakeTimers({ shouldAdvanceTime: true })

    renderApp('/scans/1')
    expect(await screen.findByText('Eyes of Infinity')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '♥ like' }))
    // The card animates out before it's actually dropped from state.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(CARD_EXIT_MS)
    })

    expect(screen.queryByText('Eyes of Infinity')).not.toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'Undo' })).toBeInTheDocument()
    const fetchesBeforeUndo = recFetchCount(fetchMock)

    fireEvent.click(screen.getByRole('button', { name: 'Undo' }))

    expect(await screen.findByText('Eyes of Infinity')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Undo' })).not.toBeInTheDocument()
    // Restored from local state, not a fresh /api/recommendations fetch — that
    // would have reset pagination/scroll for every other row on screen too.
    expect(recFetchCount(fetchMock)).toBe(fetchesBeforeUndo)
    expect(fetchMock.mock.calls.some((c) => String(c[0]).includes('/api/likes/unlike'))).toBe(true)
  })

  it('offers Undo after blocking a card', async () => {
    mockFetch(feedRoutes())
    vi.useFakeTimers({ shouldAdvanceTime: true })

    renderApp('/scans/1')
    expect(await screen.findByText('Eyes of Infinity')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '⊘ block' }))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(CARD_EXIT_MS)
    })

    expect(await screen.findByText(/Blocked Minds of Infinity/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }))
    expect(await screen.findByText('Eyes of Infinity')).toBeInTheDocument()
  })

  it('auto-dismisses the Undo affordance after its window elapses', async () => {
    mockFetch(feedRoutes())
    vi.useFakeTimers({ shouldAdvanceTime: true })

    renderApp('/scans/1')
    expect(await screen.findByText('Eyes of Infinity')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '♥ like' }))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(CARD_EXIT_MS)
    })
    expect(await screen.findByRole('button', { name: 'Undo' })).toBeInTheDocument()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(UNDO_WINDOW_MS)
    })
    expect(screen.queryByRole('button', { name: 'Undo' })).not.toBeInTheDocument()
  })
})

describe('optimistic like/block', () => {
  beforeEach(() => {
    localStorage.clear()
    signedIn()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

  it('starts the exit animation immediately, without waiting for the like request to resolve', async () => {
    let releaseLike = () => {}
    const likeHeld = new Promise<void>((resolve) => {
      releaseLike = resolve
    })
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
        const url = String(input)
        const method = (init?.method ?? 'GET').toUpperCase()
        if (url.includes('/api/auth/me')) return json(fakeMe)
        if (url.includes('/api/scans/1')) return json({ ...fakeScan, seeds: [] })
        if (url.includes('/api/recommendations/count')) return json({ count: 1 })
        if (url.includes('/api/recommendations')) return json([fakeRec()])
        if (url.includes('/api/facets')) return json({ tags: [], labels: [], seed_tags: [] })
        if (url.includes('/api/likes') && method === 'POST') {
          await likeHeld
          return json({})
        }
        if (url.includes('/api/likes')) return json([])
        if (url.includes('/api/blacklist')) return json([])
        throw new Error(`no mock route for ${url}`)
      }),
    )

    renderApp('/scans/1')
    expect(await screen.findByText('Eyes of Infinity')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '♥ like' }))

    // The exit animation is already running even though the like request is
    // still in flight — that's the optimistic part. Previously this card
    // wouldn't even start leaving until the request round-tripped. Asserted
    // synchronously, not via waitFor: `retire()` sets this class before
    // `like()`'s first `await`, in the same tick as the click.
    expect(screen.getByRole('article')).toHaveClass('likeing')
    expect(screen.getByText('Eyes of Infinity')).toBeInTheDocument()

    await act(async () => {
      releaseLike()
      await vi.advanceTimersByTimeAsync(0)
    })
  })

  it('reverts the optimistic like and shows an error if the request fails before the exit animation finishes', async () => {
    mockFetch([
      ['/api/auth/me', fakeMe],
      ['/api/scans/1', { ...fakeScan, seeds: [] }],
      ['/api/recommendations/count', { count: 1 }],
      ['/api/recommendations', [fakeRec()]],
      ['/api/facets', { tags: [], labels: [], seed_tags: [] }],
      ['/api/likes', {}, 500],
      ['/api/blacklist', []],
    ])
    vi.useFakeTimers({ shouldAdvanceTime: true })

    renderApp('/scans/1')
    expect(await screen.findByText('Eyes of Infinity')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '♥ like' }))

    // Let the failed request's rejection reach the catch handler well before
    // CARD_EXIT_MS would have removed the row.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    expect(screen.getByText('Eyes of Infinity')).toBeInTheDocument()
    expect(screen.getByRole('article')).not.toHaveClass('likeing')
    expect(await screen.findByText('Request failed (500)')).toBeInTheDocument()

    // The animation timer was cancelled, not just outrun — advancing past
    // CARD_EXIT_MS must not belatedly remove a card the failure already put
    // back.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(CARD_EXIT_MS)
    })
    expect(screen.getByText('Eyes of Infinity')).toBeInTheDocument()
  })

  it('offers a Retry action on the failure toast that re-sends the like', async () => {
    let likeCalls = 0
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
        const url = String(input)
        const method = (init?.method ?? 'GET').toUpperCase()
        if (url.includes('/api/auth/me')) return json(fakeMe)
        if (url.includes('/api/scans/1')) return json({ ...fakeScan, seeds: [] })
        if (url.includes('/api/recommendations/count')) return json({ count: 1 })
        if (url.includes('/api/recommendations')) return json([fakeRec()])
        if (url.includes('/api/facets')) return json({ tags: [], labels: [], seed_tags: [] })
        if (url.includes('/api/likes') && method === 'POST') {
          likeCalls += 1
          return likeCalls === 1 ? json({}, 500) : json({})
        }
        if (url.includes('/api/likes')) return json([])
        if (url.includes('/api/blacklist')) return json([])
        throw new Error(`no mock route for ${url}`)
      }),
    )

    renderApp('/scans/1')
    expect(await screen.findByText('Eyes of Infinity')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '♥ like' }))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(likeCalls).toBe(1)
    // The failed request restored the card; it hasn't retired yet.
    expect(screen.getByText('Eyes of Infinity')).toBeInTheDocument()

    fireEvent.click(await screen.findByRole('button', { name: 'Retry' }))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(CARD_EXIT_MS)
    })

    expect(likeCalls).toBe(2)
    // The retry succeeded, so this time the optimistic retire completes.
    expect(screen.queryByText('Eyes of Infinity')).not.toBeInTheDocument()
  })

  it('reverts a failed optimistic block after the row was already removed, clearing the Undo it armed', async () => {
    // A held gate on the POST specifically: a mocked fetch otherwise resolves
    // fast enough that the failure would routinely beat CARD_EXIT_MS, which
    // would only ever exercise `cancelRetire`'s "timer still pending" path.
    // This test is for the other path — the row already gone, Undo armed.
    let releaseBlock = () => {}
    const blockHeld = new Promise<void>((resolve) => {
      releaseBlock = resolve
    })
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
        const url = String(input)
        const method = (init?.method ?? 'GET').toUpperCase()
        if (url.includes('/api/auth/me')) return json(fakeMe)
        if (url.includes('/api/scans/1')) return json({ ...fakeScan, seeds: [] })
        if (url.includes('/api/recommendations/count')) return json({ count: 1 })
        if (url.includes('/api/recommendations')) return json([fakeRec()])
        if (url.includes('/api/facets')) return json({ tags: [], labels: [], seed_tags: [] })
        if (url.includes('/api/likes')) return json([])
        if (url.includes('/api/blacklist') && method === 'POST') {
          await blockHeld
          return json({}, 500)
        }
        if (url.includes('/api/blacklist')) return json([])
        throw new Error(`no mock route for ${url}`)
      }),
    )

    renderApp('/scans/1')
    expect(await screen.findByText('Eyes of Infinity')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '⊘ block' }))

    // Let the exit timer fire and remove the row (and arm Undo for it) while
    // the request is still held.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(CARD_EXIT_MS)
    })
    expect(screen.queryByText('Eyes of Infinity')).not.toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'Undo' })).toBeInTheDocument()

    await act(async () => {
      releaseBlock()
      await vi.advanceTimersByTimeAsync(0)
    })

    expect(await screen.findByText('Eyes of Infinity')).toBeInTheDocument()
    expect(screen.getByText('Request failed (500)')).toBeInTheDocument()
    // Nothing left to undo — the failure already restored the card.
    expect(screen.queryByRole('button', { name: 'Undo' })).not.toBeInTheDocument()
  })
})

describe('unlike/unblock from the side panels', () => {
  beforeEach(() => {
    localStorage.clear()
    signedIn()
  })
  afterEach(() => vi.unstubAllGlobals())

  const fakeLiked = { id: 1, item_type: 'album', album_id: 9, track_id: null, title: 'Liked One', band_name: 'A Band', url: null } as const
  const fakeBlocked = {
    id: 1,
    band_id: 5,
    band_name: 'Blocked Band',
    band_url: null,
    reason: null,
    expires_at: null,
  } as const

  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

  it('shows "Unliking…" while an unlike is in flight, then removes the row', async () => {
    let releaseUnlike = () => {}
    const unlikeHeld = new Promise<void>((resolve) => {
      releaseUnlike = resolve
    })
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: string | URL | Request) => {
        const url = String(input)
        if (url.includes('/api/auth/me')) return json(fakeMe)
        if (url.includes('/api/scans/1')) return json({ ...fakeScan, seeds: [] })
        if (url.includes('/api/likes/unlike')) {
          await unlikeHeld
          return json({ unliked: true })
        }
        if (url.includes('/api/likes')) return json([fakeLiked])
        if (url.includes('/api/blacklist')) return json([])
        if (url.includes('/api/facets')) return json({ tags: [], labels: [], seed_tags: [] })
        if (url.includes('/api/recommendations/count')) return json({ count: 1 })
        if (url.includes('/api/recommendations')) return json([fakeRec()])
        throw new Error(`no mock route for ${url}`)
      }),
    )

    renderApp('/scans/1')
    await screen.findByText('Eyes of Infinity')

    fireEvent.click(screen.getByRole('button', { name: /♥ Liked/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'unlike' }))

    expect(await screen.findByRole('button', { name: 'Unliking…' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Unliking…' })).toBeDisabled()

    await act(async () => {
      releaseUnlike()
      await new Promise((r) => setTimeout(r, 0))
    })

    // The mock server doesn't actually drop the item from its liked list, so
    // the row is still here after the refetch — the point is that it's no
    // longer stuck on the busy label once the request settles.
    expect(screen.queryByRole('button', { name: 'Unliking…' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'unlike' })).not.toBeDisabled()
  })

  it('surfaces an error and leaves the row usable when an unblock fails', async () => {
    mockFetch([
      ['/api/auth/me', fakeMe],
      ['/api/scans/1', { ...fakeScan, seeds: [] }],
      ['/api/blacklist/5/unblock', { detail: 'nope' }, 500],
      ['/api/blacklist', [fakeBlocked]],
      ['/api/likes', []],
      ['/api/facets', { tags: [], labels: [], seed_tags: [] }],
      ['/api/recommendations/count', { count: 1 }],
      ['/api/recommendations', [fakeRec()]],
    ])

    renderApp('/scans/1')
    await screen.findByText('Eyes of Infinity')

    fireEvent.click(screen.getByRole('button', { name: /Blocked/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'unblock' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/nope/i)
    // Not left stuck busy after the failure — the row is clickable again.
    expect(screen.getByRole('button', { name: 'unblock' })).not.toBeDisabled()
  })

  it('shows an expiry label on a temporary block, and none on a permanent one', async () => {
    const soon = new Date(Date.now() + 3 * 3600 * 1000).toISOString()
    mockFetch([
      ['/api/auth/me', fakeMe],
      ['/api/scans/1', { ...fakeScan, seeds: [] }],
      ['/api/blacklist', [{ ...fakeBlocked, expires_at: soon }, { ...fakeBlocked, id: 2, band_id: 6, band_name: 'Forever Blocked', expires_at: null }]],
      ['/api/likes', []],
      ['/api/facets', { tags: [], labels: [], seed_tags: [] }],
      ['/api/recommendations/count', { count: 1 }],
      ['/api/recommendations', [fakeRec()]],
    ])

    renderApp('/scans/1')
    await screen.findByText('Eyes of Infinity')
    fireEvent.click(screen.getByRole('button', { name: /Blocked/ }))

    const temporaryRow = (await screen.findByText('Blocked Band')).closest('li')
    expect(temporaryRow).not.toBeNull()
    expect(temporaryRow).toHaveTextContent(/expires in \d+h/)

    const permanentRow = screen.getByText('Forever Blocked').closest('li')
    expect(permanentRow).not.toBeNull()
    expect(permanentRow).not.toHaveTextContent(/expires in/)
  })

  it('links a blocked band to Bandcamp when it has a URL, and shows nothing when it does not', async () => {
    mockFetch([
      ['/api/auth/me', fakeMe],
      ['/api/scans/1', { ...fakeScan, seeds: [] }],
      [
        '/api/blacklist',
        [
          { ...fakeBlocked, band_url: 'https://someartist.bandcamp.com' },
          { ...fakeBlocked, id: 2, band_id: 6, band_name: 'No Link Band', band_url: null },
        ],
      ],
      ['/api/likes', []],
      ['/api/facets', { tags: [], labels: [], seed_tags: [] }],
      ['/api/recommendations/count', { count: 1 }],
      ['/api/recommendations', [fakeRec()]],
    ])

    renderApp('/scans/1')
    await screen.findByText('Eyes of Infinity')
    fireEvent.click(screen.getByRole('button', { name: /Blocked/ }))

    const link = await screen.findByRole('link', { name: 'Open Blocked Band on Bandcamp' })
    expect(link).toHaveAttribute('href', 'https://someartist.bandcamp.com')

    const noLinkRow = screen.getByText('No Link Band').closest('li')
    expect(noLinkRow).not.toBeNull()
    expect(within(noLinkRow as HTMLElement).queryByRole('link')).not.toBeInTheDocument()
  })

  it('ignores a second click on the same row while the first unlike is still in flight', async () => {
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      if (url.includes('/api/auth/me')) return json(fakeMe)
      if (url.includes('/api/scans/1')) return json({ ...fakeScan, seeds: [] })
      if (url.includes('/api/likes/unlike')) return json({ unliked: true })
      if (url.includes('/api/likes')) return json([fakeLiked])
      if (url.includes('/api/blacklist')) return json([])
      if (url.includes('/api/facets')) return json({ tags: [], labels: [], seed_tags: [] })
      if (url.includes('/api/recommendations/count')) return json({ count: 1 })
      if (url.includes('/api/recommendations')) return json([fakeRec()])
      throw new Error(`no mock route for ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderApp('/scans/1')
    await screen.findByText('Eyes of Infinity')

    fireEvent.click(screen.getByRole('button', { name: /♥ Liked/ }))
    const unlikeBtn = await screen.findByRole('button', { name: 'unlike' })
    fireEvent.click(unlikeBtn)
    fireEvent.click(unlikeBtn)

    await waitFor(() =>
      expect(fetchMock.mock.calls.filter((c) => String(c[0]).includes('/api/likes/unlike')).length).toBe(
        1,
      ),
    )
  })

  it('offers "renew" only on a block expiring within a day, and lists soonest-expiring first', async () => {
    const soon = new Date(Date.now() + 2 * 3600 * 1000).toISOString()
    const later = new Date(Date.now() + 5 * 24 * 3600 * 1000).toISOString()
    mockFetch([
      ['/api/auth/me', fakeMe],
      ['/api/scans/1', { ...fakeScan, seeds: [] }],
      [
        '/api/blacklist',
        [
          { ...fakeBlocked, id: 3, band_id: 7, band_name: 'Forever Blocked', expires_at: null },
          { ...fakeBlocked, id: 2, band_id: 6, band_name: 'Later Band', expires_at: later },
          { ...fakeBlocked, id: 1, band_id: 5, band_name: 'Blocked Band', expires_at: soon },
        ],
      ],
      ['/api/likes', []],
      ['/api/facets', { tags: [], labels: [], seed_tags: [] }],
      ['/api/recommendations/count', { count: 1 }],
      ['/api/recommendations', [fakeRec()]],
    ])

    renderApp('/scans/1')
    await screen.findByText('Eyes of Infinity')
    fireEvent.click(screen.getByRole('button', { name: /Blocked/ }))
    await screen.findByText('Blocked Band')

    // Only the row expiring soon gets a renew action, even though "Later
    // Band" also has a (non-imminent) expiry.
    expect(screen.getAllByRole('button', { name: 'renew ▾' })).toHaveLength(1)

    const rows = screen.getAllByRole('listitem').map((li) => li.textContent)
    expect(rows[0]).toMatch(/Blocked Band/)
    expect(rows[1]).toMatch(/Later Band/)
    expect(rows[2]).toMatch(/Forever Blocked/)
  })

  it('renewing a soon-to-expire block posts a fresh expires_at for the same band', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.setSystemTime(new Date('2026-09-03T00:00:00.000Z'))
    const soon = new Date(Date.now() + 2 * 3600 * 1000).toISOString()
    const fetchMock = mockFetch([
      ['/api/auth/me', fakeMe],
      ['/api/scans/1', { ...fakeScan, seeds: [] }],
      ['/api/blacklist', [{ ...fakeBlocked, expires_at: soon }]],
      ['/api/likes', []],
      ['/api/facets', { tags: [], labels: [], seed_tags: [] }],
      ['/api/recommendations/count', { count: 1 }],
      ['/api/recommendations', [fakeRec()]],
    ])

    renderApp('/scans/1')
    expect(await screen.findByText('Eyes of Infinity')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Blocked/ }))

    fireEvent.click(await screen.findByRole('button', { name: 'renew ▾' }))
    fireEvent.click(screen.getByRole('button', { name: '1 week' }))

    await waitFor(() => {
      const renewCall = fetchMock.mock.calls.find(([u, init]) => {
        const url = String(u)
        return url.includes('/api/blacklist') && !url.includes('unblock') && init?.method === 'POST'
      })
      expect(renewCall).toBeDefined()
      const body = JSON.parse(String(renewCall?.[1]?.body))
      expect(body.band_id).toBe(5)
      const expiresAtMs = new Date(body.expires_at).getTime()
      const expectedMs = new Date('2026-09-03T00:00:00.000Z').getTime() + 7 * 24 * 3600 * 1000
      expect(Math.abs(expiresAtMs - expectedMs)).toBeLessThan(5000)
    })

    vi.useRealTimers()
  })

  it('does not offer renew on a block expiring in several days, or a permanent one', async () => {
    const later = new Date(Date.now() + 5 * 24 * 3600 * 1000).toISOString()
    mockFetch([
      ['/api/auth/me', fakeMe],
      ['/api/scans/1', { ...fakeScan, seeds: [] }],
      [
        '/api/blacklist',
        [
          { ...fakeBlocked, expires_at: later },
          { ...fakeBlocked, id: 2, band_id: 6, band_name: 'Forever Blocked', expires_at: null },
        ],
      ],
      ['/api/likes', []],
      ['/api/facets', { tags: [], labels: [], seed_tags: [] }],
      ['/api/recommendations/count', { count: 1 }],
      ['/api/recommendations', [fakeRec()]],
    ])

    renderApp('/scans/1')
    await screen.findByText('Eyes of Infinity')
    fireEvent.click(screen.getByRole('button', { name: /Blocked/ }))
    await screen.findByText('Blocked Band')

    expect(screen.queryByRole('button', { name: 'renew ▾' })).not.toBeInTheDocument()
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

  it('explains a genuinely empty feed with the cold-start diagnostics', async () => {
    mockFetch([
      ['/api/auth/me', fakeMe],
      ['/api/scans/1', { ...fakeScan, seeds: [] }],
      ['/api/recommendations/count', { count: 0 }],
      ['/api/recommendations', []],
      ['/api/facets', { tags: [], labels: [], seed_tags: [] }],
      ['/api/likes', []],
      ['/api/blacklist', []],
      [
        '/api/stats',
        {
          recommendations: 0,
          fans: 20,
          neighbours: 12,
          albums: 500,
          tracks: 900,
          my_owned: 300,
          my_wishlist: 10,
          follows: 15,
          liked: 0,
          requests_used: 40,
          request_budget: 100,
          cold_start: {
            neighbour_count: 12,
            candidates: 340,
            excluded_owned: 210,
            excluded_wishlisted: 40,
            excluded_followed: 55,
            excluded_blacklisted: 3,
          },
          recompute_generation: 1,
        },
      ],
    ])
    renderApp('/scans/1')

    expect(await screen.findByText('No recommendations in this scan yet.')).toBeInTheDocument()
    expect(await screen.findByText('340')).toBeInTheDocument()
    expect(screen.getByText(/candidates/)).toBeInTheDocument()
  })

  it('does not fetch stats, or show cold-start diagnostics, while the feed has rows', async () => {
    const fetchMock = mockFetch([
      ['/api/auth/me', fakeMe],
      ['/api/scans/1', { ...fakeScan, seeds: [] }],
      ['/api/recommendations/count', { count: 1 }],
      ['/api/recommendations', [fakeRec()]],
      ['/api/facets', { tags: [], labels: [], seed_tags: [] }],
      ['/api/likes', []],
      ['/api/blacklist', []],
    ])
    renderApp('/scans/1')

    expect(await screen.findByText('Eyes of Infinity')).toBeInTheDocument()
    expect(fetchMock.mock.calls.some((c) => String(c[0]).includes('/api/stats'))).toBe(false)
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

describe('updated-since-last-visit notice', () => {
  beforeEach(() => {
    localStorage.clear()
    signedIn()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  const json = (body: unknown) =>
    new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })

  function mockScanAtGeneration(generation: number) {
    return vi.fn(async (input: string | URL | Request) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes('/api/auth/me')) return json(fakeMe)
      if (url.includes('/api/scans/1')) {
        return json({ ...fakeScan, recompute_generation: generation, seeds: [] })
      }
      if (url.includes('/api/likes') || url.includes('/api/blacklist')) return json([])
      if (url.includes('/api/facets')) return json({ tags: [], labels: [], seed_tags: [] })
      if (url.includes('/api/recommendations/count')) return json({ count: 1 })
      if (url.includes('/api/recommendations')) return json([fakeRec()])
      throw new Error(`no mock route for ${url}`)
    })
  }

  it('shows nothing on a scan’s first-ever visit, with no prior generation on record', async () => {
    vi.stubGlobal('fetch', mockScanAtGeneration(1))

    renderApp('/scans/1')

    expect(await screen.findByText(fakeRec().title!)).toBeInTheDocument()
    expect(screen.queryByText(/changed since your last visit/i)).not.toBeInTheDocument()
  })

  it('shows the notice when the scan moved on since the recorded last visit', async () => {
    localStorage.setItem('crate-digger.lastSeenGeneration:1', '1')
    vi.stubGlobal('fetch', mockScanAtGeneration(2))

    renderApp('/scans/1')

    expect(await screen.findByText(/changed since your last visit/i)).toBeInTheDocument()
    // Dismissing just hides the notice — it doesn't re-trigger a fetch.
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }))
    expect(screen.queryByText(/changed since your last visit/i)).not.toBeInTheDocument()
  })

  it('shows nothing when the recorded last visit already matches the current generation', async () => {
    localStorage.setItem('crate-digger.lastSeenGeneration:1', '2')
    vi.stubGlobal('fetch', mockScanAtGeneration(2))

    renderApp('/scans/1')

    expect(await screen.findByText(fakeRec().title!)).toBeInTheDocument()
    expect(screen.queryByText(/changed since your last visit/i)).not.toBeInTheDocument()
  })

  it('records the current generation as seen, so a same-session reload would not repeat the notice', async () => {
    localStorage.setItem('crate-digger.lastSeenGeneration:1', '1')
    vi.stubGlobal('fetch', mockScanAtGeneration(2))

    renderApp('/scans/1')

    expect(await screen.findByText(/changed since your last visit/i)).toBeInTheDocument()
    expect(localStorage.getItem('crate-digger.lastSeenGeneration:1')).toBe('2')
  })
})

describe('auto-prune stale tag filters', () => {
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

  // The feed's countline (`.countline`) also carries `role="status"` now (see
  // the "announces the match count" test above), so a bare `*ByRole('status')`
  // no longer uniquely identifies the prune toast — narrow to the toast's own
  // class, same as `ToastStack.tsx` renders it.
  const toastStatus = () => screen.queryAllByRole('status').find((el) => el.classList.contains('toast'))

  /** A running scan whose recommendation count and facets tags are both
   *  controlled by the two out-of-band flags, so a test can change what the
   *  *next* poll turns up (mimicking a recompute that dropped a genre from
   *  every current rec) before advancing the clock. */
  function mockScanWhoseFacetsChange(state: { recCount: number; hasPsybient: boolean }) {
    return vi.fn(async (input: string | URL | Request) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes('/api/auth/me')) return json(fakeMe)
      if (url.includes('/api/scans/1')) {
        return json({ ...fakeScan, status: 'running', stats: { recommendations: state.recCount }, seeds: [] })
      }
      if (url.includes('/api/likes') || url.includes('/api/blacklist')) return json([])
      if (url.includes('/api/facets')) {
        return json({
          tags: state.hasPsybient ? [{ value: 'psybient', label: 'psybient', count: 1 }] : [],
          labels: [],
          seed_tags: [],
        })
      }
      if (url.includes('/api/recommendations/count')) return json({ count: 1 })
      if (url.includes('/api/recommendations')) return json([fakeRec()])
      throw new Error(`no mock route for ${url}`)
    })
  }

  it('drops an include-mode tag filter once it is gone from facets, with a toast naming it', async () => {
    const state = { recCount: 1, hasPsybient: true }
    vi.stubGlobal('fetch', mockScanWhoseFacetsChange(state))
    vi.useFakeTimers({ shouldAdvanceTime: true })

    renderApp('/scans/1?tag=psybient')
    expect(await screen.findByText(fakeRec().title!)).toBeInTheDocument()
    expect(currentLocation().search).toContain('tag=psybient')

    // The recompute that dropped this genre from every current rec.
    state.hasPsybient = false
    state.recCount = 2
    await act(async () => {
      await vi.advanceTimersByTimeAsync(SCAN_POLL_MS)
    })

    await waitFor(() => expect(currentLocation().search).not.toContain('tag=psybient'))
    await waitFor(() => expect(toastStatus()).toBeTruthy())
    expect(toastStatus()).toHaveTextContent(/psybient/)
  })

  it('leaves an exclude-mode tag filter alone even once it is absent from facets', async () => {
    const state = { recCount: 1, hasPsybient: false }
    vi.stubGlobal('fetch', mockScanWhoseFacetsChange(state))
    vi.useFakeTimers({ shouldAdvanceTime: true })

    renderApp('/scans/1?exclude_tag=psybient')
    expect(await screen.findByText(fakeRec().title!)).toBeInTheDocument()
    expect(currentLocation().search).toContain('exclude_tag=psybient')

    state.recCount = 2
    await act(async () => {
      await vi.advanceTimersByTimeAsync(SCAN_POLL_MS)
    })

    await waitFor(() => expect(screen.getByText(fakeRec().title!)).toBeInTheDocument())
    // An excluded value that's already absent is a no-op, not a stuck filter —
    // nothing to auto-clear, so the param and no toast should appear.
    expect(currentLocation().search).toContain('exclude_tag=psybient')
    expect(toastStatus()).toBeUndefined()
  })

  it('keeps a still-valid tag filter untouched across a recompute', async () => {
    const state = { recCount: 1, hasPsybient: true }
    vi.stubGlobal('fetch', mockScanWhoseFacetsChange(state))
    vi.useFakeTimers({ shouldAdvanceTime: true })

    renderApp('/scans/1?tag=psybient')
    expect(await screen.findByText(fakeRec().title!)).toBeInTheDocument()

    state.recCount = 2
    await act(async () => {
      await vi.advanceTimersByTimeAsync(SCAN_POLL_MS)
    })

    await waitFor(() => expect(screen.getByText(fakeRec().title!)).toBeInTheDocument())
    expect(currentLocation().search).toContain('tag=psybient')
    expect(toastStatus()).toBeUndefined()
  })
})

describe('resume scroll position', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    signedIn()
  })
  afterEach(() => vi.unstubAllGlobals())

  const feedRoutes = (recs = [fakeRec()]) =>
    [
      ['/api/auth/me', fakeMe],
      ['/api/scans/1', { ...fakeScan, seeds: [] }],
      ['/api/recommendations/count', { count: recs.length }],
      ['/api/recommendations', recs],
      ['/api/facets', { tags: [], labels: [], seed_tags: [] }],
      ['/api/likes', []],
      ['/api/blacklist', []],
    ] as Array<[string, unknown, number?]>

  it('restores the saved scroll offset when returning to the same filtered view', async () => {
    mockFetch(feedRoutes())
    const first = renderApp('/scans/1')
    await screen.findByText('Eyes of Infinity')

    Object.defineProperty(window, 'scrollY', { value: 400, configurable: true })
    fireEvent.scroll(window)
    // Leaving the page (a real app would navigate away; unmounting here is
    // the JSDOM stand-in for "the component goes away and comes back").
    first.unmount()

    const scrollTo = vi.fn()
    vi.stubGlobal('scrollTo', scrollTo)
    renderApp('/scans/1')
    await screen.findByText('Eyes of Infinity')

    expect(scrollTo).toHaveBeenCalledWith(0, 400)
  })

  it('does not restore a scroll offset saved under a different filter', async () => {
    mockFetch(feedRoutes())
    const first = renderApp('/scans/1?tag=psybient')
    await screen.findByText('Eyes of Infinity')

    Object.defineProperty(window, 'scrollY', { value: 400, configurable: true })
    fireEvent.scroll(window)
    first.unmount()

    const scrollTo = vi.fn()
    vi.stubGlobal('scrollTo', scrollTo)
    renderApp('/scans/1')
    await screen.findByText('Eyes of Infinity')

    expect(scrollTo).not.toHaveBeenCalled()
  })
})

describe('scroll-to-top button', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    signedIn()
  })
  afterEach(() => vi.unstubAllGlobals())

  it('scrolls to the top and refocuses the heading when clicked', async () => {
    mockFetch([
      ['/api/auth/me', fakeMe],
      ['/api/scans/1', { ...fakeScan, seeds: [] }],
      ['/api/recommendations/count', { count: 1 }],
      ['/api/recommendations', [fakeRec()]],
      ['/api/facets', { tags: [], labels: [], seed_tags: [] }],
      ['/api/likes', []],
      ['/api/blacklist', []],
    ])
    renderApp('/scans/1')
    await screen.findByText('Eyes of Infinity')

    Object.defineProperty(window, 'scrollY', { value: 700, configurable: true })
    fireEvent.scroll(window)

    const scrollTo = vi.fn()
    vi.stubGlobal('scrollTo', scrollTo)
    fireEvent.click(await screen.findByRole('button', { name: 'Back to top' }))

    expect(scrollTo).toHaveBeenCalledWith({ top: 0, behavior: 'smooth' })
    expect(screen.getByRole('heading', { name: /My collection/ })).toHaveFocus()
  })
})

describe('export feed as CSV', () => {
  beforeEach(() => {
    localStorage.clear()
    signedIn()
  })
  afterEach(() => vi.unstubAllGlobals())

  it('is disabled with nothing loaded, then downloads the loaded rows via a Blob URL', async () => {
    mockFetch([
      ['/api/auth/me', fakeMe],
      ['/api/scans/1', { ...fakeScan, seeds: [] }],
      ['/api/recommendations/count', { count: 0 }],
      ['/api/recommendations', []],
      ['/api/facets', { tags: [], labels: [], seed_tags: [] }],
      ['/api/likes', []],
      ['/api/blacklist', []],
    ])
    renderApp('/scans/1')
    expect(await screen.findByRole('button', { name: /Export CSV/ })).toBeDisabled()
  })

  it('downloads the currently-loaded rows as a CSV via a Blob URL', async () => {
    mockFetch([
      ['/api/auth/me', fakeMe],
      ['/api/scans/1', { ...fakeScan, seeds: [] }],
      ['/api/recommendations/count', { count: 1 }],
      ['/api/recommendations', [fakeRec()]],
      ['/api/facets', { tags: [], labels: [], seed_tags: [] }],
      ['/api/likes', []],
      ['/api/blacklist', []],
    ])
    renderApp('/scans/1')
    await screen.findByText('Eyes of Infinity')

    const originalCreateObjectURL = URL.createObjectURL
    const originalRevokeObjectURL = URL.revokeObjectURL
    const createObjectURL = vi.fn((_blob: Blob) => 'blob:mock')
    const revokeObjectURL = vi.fn()
    URL.createObjectURL = createObjectURL
    URL.revokeObjectURL = revokeObjectURL
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    try {
      const button = await screen.findByRole('button', { name: /Export CSV/ })
      expect(button).not.toBeDisabled()
      fireEvent.click(button)

      expect(createObjectURL).toHaveBeenCalledTimes(1)
      const blob = createObjectURL.mock.calls[0]?.[0]
      if (!blob) throw new Error('createObjectURL was not called with a Blob')
      expect(blob.type).toContain('text/csv')
      expect(await blob.text()).toContain('Eyes of Infinity')
      expect(click).toHaveBeenCalledTimes(1)
      expect(revokeObjectURL).toHaveBeenCalledWith('blob:mock')
    } finally {
      URL.createObjectURL = originalCreateObjectURL
      URL.revokeObjectURL = originalRevokeObjectURL
      click.mockRestore()
    }
  })
})

describe('command palette', () => {
  beforeEach(() => {
    localStorage.clear()
    signedIn()
  })
  afterEach(() => vi.unstubAllGlobals())

  const twoScans = [fakeScan, { ...fakeScan, id: 2, name: 'Psy dig', kind: 'custom' as const }]

  // '/api/scans/2' before '/api/scans' — mockFetch matches by substring in
  // order, and the bare list route would otherwise swallow the scan-2 route.
  const routes: Array<[string, unknown, number?]> = [
    ['/api/auth/me', fakeMe],
    ['/api/scans/2', { ...twoScans[1], seeds: [] }],
    ['/api/scans', twoScans],
    ['/api/recommendations/count', { count: 0 }],
    ['/api/recommendations', []],
    ['/api/facets', { tags: [], labels: [], seed_tags: [] }],
    ['/api/likes', []],
    ['/api/blacklist', []],
  ]

  it('opens on Ctrl+K and lists a jump-to-Scans action plus every scan', async () => {
    mockFetch(routes)
    renderApp('/scans')
    await screen.findByRole('heading', { name: 'Your scans' })

    fireEvent.keyDown(document, { key: 'k', ctrlKey: true })

    expect(await screen.findByRole('dialog', { name: 'Command palette' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Go to Scans' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: /My collection/ })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Psy dig' })).toBeInTheDocument()
  })

  it('filters by typed text, and Enter on the highlighted row navigates there', async () => {
    mockFetch(routes)
    renderApp('/scans')
    await screen.findByRole('heading', { name: 'Your scans' })

    fireEvent.keyDown(document, { key: 'k', ctrlKey: true })
    const input = await screen.findByRole('textbox', { name: 'Jump to…' })
    fireEvent.change(input, { target: { value: 'psy' } })

    expect(screen.getAllByRole('option')).toHaveLength(1)
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await screen.findByRole('heading', { name: /Psy dig/ })
    expect(currentLocation().pathname).toBe('/scans/2')
  })

  it('a mouse click on a scan option navigates there too', async () => {
    mockFetch(routes)
    renderApp('/scans')
    await screen.findByRole('heading', { name: 'Your scans' })

    fireEvent.keyDown(document, { key: 'k', ctrlKey: true })
    fireEvent.click(await screen.findByRole('option', { name: 'Psy dig' }))

    await screen.findByRole('heading', { name: /Psy dig/ })
    expect(currentLocation().pathname).toBe('/scans/2')
  })
})
