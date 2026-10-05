import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { resetToastsForTests } from '../../lib/toast'
import {
  currentLocation,
  fakeCollection,
  fakeCollectionItem,
  fakeMe,
  mockFetch,
  renderApp,
} from '../../test/renderApp'

const signedIn = () => localStorage.setItem('crate-digger.token', 'tok')

const DRUKQS = fakeCollectionItem({ album_id: 10, title: 'Drukqs', band_name: 'Aphex Twin' })
const GEOGADDI = fakeCollectionItem({ album_id: 11, title: 'Geogaddi', band_name: 'Boards of Canada' })
const TAKK = fakeCollectionItem({ album_id: 12, title: 'Takk...', band_name: 'Sigur Rós' })
const WINDOWLICKER = fakeCollectionItem({
  item_type: 'track',
  album_id: null,
  track_id: 30,
  title: 'Windowlicker',
  band_name: 'Aphex Twin',
})

/** `/api/collection` is the only call this page makes; `/api/auth/me` is the
 *  AuthProvider's. Needles are distinct substrings, so order doesn't matter. */
function routes(collection: ReturnType<typeof fakeCollection>) {
  return [
    ['/api/auth/me', fakeMe],
    ['/api/collection', collection],
  ] as Array<[string, unknown, number?]>
}

/** The row element for a given title. Section chips have to be asserted inside
 *  it: the tab bar uses the same words ("Owned", "Liked"), so a bare
 *  `getByText('Owned')` would match the tab and pass whatever the row shows. */
function rowFor(title: string): HTMLElement {
  const heading = screen.getByRole('heading', { name: title, level: 2 })
  const row = heading.closest('article')
  if (row === null) throw new Error(`no row found for ${title}`)
  return row
}

beforeEach(() => {
  localStorage.clear()
  signedIn()
  // The toast queue is module-scope by design, so an "Unliked …" toast raised
  // by one test is still mounted in the next one — and it carries
  // role="status", same as this page's count line.
  resetToastsForTests()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('CollectionPage', () => {
  it('shows rows from all three lists in the All view', async () => {
    mockFetch(routes(fakeCollection({ owned: [DRUKQS], wishlist: [GEOGADDI], liked: [TAKK] })))
    renderApp('/collection')

    // findBy*: /collection is a lazy route, so first paint is the Suspense fallback.
    expect(await screen.findByRole('heading', { name: 'Drukqs', level: 2 })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Geogaddi', level: 2 })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Takk...', level: 2 })).toBeInTheDocument()
  })

  it('merges an item that is both owned and liked into one row with both labels', async () => {
    mockFetch(routes(fakeCollection({ owned: [DRUKQS], liked: [DRUKQS] })))
    renderApp('/collection')

    expect(await screen.findAllByRole('heading', { name: 'Drukqs', level: 2 })).toHaveLength(1)
    const row = rowFor('Drukqs')
    expect(within(row).getByText('Owned')).toBeInTheDocument()
    expect(within(row).getByText('Liked')).toBeInTheDocument()
  })

  it('searches across every section at once and counts matches per tab', async () => {
    mockFetch(routes(fakeCollection({ owned: [DRUKQS], wishlist: [GEOGADDI] })))
    renderApp('/collection')
    await screen.findByRole('heading', { name: 'Drukqs', level: 2 })

    await userEvent.type(screen.getByLabelText('Search your collection'), 'geogaddi')

    // Found from the All view even though it lives in the wishlist…
    expect(await screen.findByRole('heading', { name: 'Geogaddi', level: 2 })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Drukqs', level: 2 })).not.toBeInTheDocument()
    // …and the badges say which section has it, so you needn't open each tab.
    expect(screen.getByRole('link', { name: /Wishlist 1/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Owned 0/ })).toBeInTheDocument()
  })

  it('filters without issuing another request', async () => {
    const fetchMock = mockFetch(
      routes(fakeCollection({ owned: [DRUKQS, GEOGADDI] })),
    )
    renderApp('/collection')
    await screen.findByRole('heading', { name: 'Drukqs', level: 2 })
    const before = fetchMock.mock.calls.length

    await userEvent.type(screen.getByLabelText('Search your collection'), 'drukqs')

    expect(screen.queryByRole('heading', { name: 'Geogaddi', level: 2 })).not.toBeInTheDocument()
    expect(fetchMock.mock.calls.length).toBe(before)
  })

  it('matches the artist name, not just the title', async () => {
    mockFetch(routes(fakeCollection({ owned: [DRUKQS, GEOGADDI] })))
    renderApp('/collection')
    await screen.findByRole('heading', { name: 'Drukqs', level: 2 })

    await userEvent.type(screen.getByLabelText('Search your collection'), 'boards')

    expect(await screen.findByRole('heading', { name: 'Geogaddi', level: 2 })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Drukqs', level: 2 })).not.toBeInTheDocument()
  })

  it('ignores diacritics, so "sigur ros" finds "Sigur Rós"', async () => {
    mockFetch(routes(fakeCollection({ owned: [DRUKQS, TAKK] })))
    renderApp('/collection')
    await screen.findByRole('heading', { name: 'Takk...', level: 2 })

    await userEvent.type(screen.getByLabelText('Search your collection'), 'sigur ros')

    expect(await screen.findByRole('heading', { name: 'Takk...', level: 2 })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Drukqs', level: 2 })).not.toBeInTheDocument()
  })

  it('requires every search term to match, in any order', async () => {
    mockFetch(routes(fakeCollection({ owned: [DRUKQS, WINDOWLICKER] })))
    renderApp('/collection')
    await screen.findByRole('heading', { name: 'Drukqs', level: 2 })

    // Both rows are "Aphex Twin"; only one is also "drukqs".
    await userEvent.type(screen.getByLabelText('Search your collection'), 'drukqs aphex')

    expect(await screen.findByRole('heading', { name: 'Drukqs', level: 2 })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Windowlicker', level: 2 })).not.toBeInTheDocument()
  })

  it('deep-links straight into a filtered section', async () => {
    mockFetch(routes(fakeCollection({ owned: [DRUKQS], wishlist: [GEOGADDI, TAKK] })))
    renderApp('/collection?tab=wishlist&q=geogaddi')

    expect(await screen.findByRole('heading', { name: 'Geogaddi', level: 2 })).toBeInTheDocument()
    // Not in the wishlist tab, and not a search match either.
    expect(screen.queryByRole('heading', { name: 'Drukqs', level: 2 })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Takk...', level: 2 })).not.toBeInTheDocument()
    expect(screen.getByDisplayValue('geogaddi')).toBeInTheDocument()
  })

  it('keeps the query in the URL so the view can be shared', async () => {
    mockFetch(routes(fakeCollection({ owned: [DRUKQS] })))
    renderApp('/collection')
    await screen.findByRole('heading', { name: 'Drukqs', level: 2 })

    await userEvent.type(screen.getByLabelText('Search your collection'), 'drukqs')

    // The URL write is debounced behind the typing on purpose — binding the
    // input straight to the URL dropped characters (see CollectionPage) — so
    // the address bar catches up a moment later, not on the keystroke.
    await waitFor(() => expect(currentLocation().search).toContain('q=drukqs'))
  })

  it('does not drop characters when the query is typed quickly', async () => {
    mockFetch(routes(fakeCollection({ owned: [DRUKQS] })))
    renderApp('/collection')
    await screen.findByRole('heading', { name: 'Drukqs', level: 2 })

    const box = screen.getByLabelText('Search your collection')
    // `delay: null` types with no gap between keystrokes, which is what
    // exposed the original bug: the field reset to a stale value mid-word and
    // "bjork vespertine 10" ended up as "0".
    await userEvent.type(box, 'bjork vespertine 10', { delay: null })

    expect(box).toHaveValue('bjork vespertine 10')
  })

  it('clicking the artist narrows the list to that artist', async () => {
    mockFetch(routes(fakeCollection({ owned: [DRUKQS, GEOGADDI] })))
    renderApp('/collection')
    await screen.findByRole('heading', { name: 'Drukqs', level: 2 })

    await userEvent.click(screen.getByRole('button', { name: /Boards of Canada/ }))

    expect(await screen.findByRole('heading', { name: 'Geogaddi', level: 2 })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Drukqs', level: 2 })).not.toBeInTheDocument()
  })

  it('renders no Bandcamp link for an item with no stored url', async () => {
    mockFetch(routes(fakeCollection({ owned: [fakeCollectionItem({ url: null })] })))
    renderApp('/collection')
    await screen.findByRole('heading', { name: 'Drukqs', level: 2 })

    expect(screen.queryByRole('link', { name: /Bandcamp/ })).not.toBeInTheDocument()
  })

  it('offers Unlike only on liked items, and keeps a row that is also owned', async () => {
    mockFetch([
      ...routes(fakeCollection({ owned: [DRUKQS, GEOGADDI], liked: [DRUKQS] })),
      ['/api/likes/unlike', { unliked: true }],
    ])
    renderApp('/collection')
    await screen.findByRole('heading', { name: 'Drukqs', level: 2 })

    // Geogaddi is owned only, so there is exactly one Unlike button on screen.
    const unlike = screen.getByRole('button', { name: 'Unlike' })
    await userEvent.click(unlike)

    // Still owned → the row stays, only the Liked chip goes.
    expect(await screen.findByRole('heading', { name: 'Drukqs', level: 2 })).toBeInTheDocument()
    const row = rowFor('Drukqs')
    expect(within(row).queryByText('Liked')).not.toBeInTheDocument()
    expect(within(row).getByText('Owned')).toBeInTheDocument()
    expect(within(row).queryByRole('button', { name: 'Unlike' })).not.toBeInTheDocument()
  })

  it('tells an uncrawled user their scan is still running instead of showing nothing', async () => {
    mockFetch([
      ['/api/auth/me', { ...fakeMe, has_crawled: false }],
      ['/api/collection', fakeCollection()],
    ])
    renderApp('/collection')

    expect(await screen.findByText(/collection scan hasn't finished yet/i)).toBeInTheDocument()
  })

  it('renders a bounded window of a large collection and grows on demand', async () => {
    // 250 rows: mounting every one of a real collection at once locks the main
    // thread, so the list pages even though the search covers everything.
    const many = Array.from({ length: 250 }, (_, i) =>
      fakeCollectionItem({ album_id: 1000 + i, title: `Record ${String(i).padStart(3, '0')}` }),
    )
    mockFetch(routes(fakeCollection({ owned: many })))
    renderApp('/collection')
    await screen.findByRole('heading', { name: 'Record 000', level: 2 })

    expect(screen.getAllByRole('heading', { level: 2 })).toHaveLength(100)
    // The count line still describes every match, not just what is rendered.
    expect(screen.getByRole('status')).toHaveTextContent('250')

    await userEvent.click(screen.getByRole('button', { name: /Show 100 more/ }))
    expect(screen.getAllByRole('heading', { level: 2 })).toHaveLength(200)
  })

  it('resets the window when the search changes', async () => {
    const many = Array.from({ length: 250 }, (_, i) =>
      fakeCollectionItem({ album_id: 1000 + i, title: `Record ${String(i).padStart(3, '0')}` }),
    )
    mockFetch(routes(fakeCollection({ owned: many })))
    renderApp('/collection')
    await screen.findByRole('heading', { name: 'Record 000', level: 2 })

    await userEvent.click(screen.getByRole('button', { name: /Show 100 more/ }))
    expect(screen.getAllByRole('heading', { level: 2 })).toHaveLength(200)

    // A narrower search must not keep showing a window sized for the old one.
    // "01" matches 010-019, plus 001, 101 and 201 — 13 in all.
    await userEvent.type(screen.getByLabelText('Search your collection'), 'Record 01')
    expect(await screen.findByRole('status')).toHaveTextContent('13 items match your search')
    expect(screen.getAllByRole('heading', { level: 2 })).toHaveLength(13)
    expect(screen.queryByRole('button', { name: /Show .* more/ })).not.toBeInTheDocument()
  })

  it('is reachable from the header menu', async () => {
    mockFetch([
      ['/api/auth/me', fakeMe],
      ['/api/scans', []],
      ['/api/collection', fakeCollection({ owned: [DRUKQS] })],
    ])
    renderApp('/scans')
    await screen.findByRole('heading', { name: 'Your scans' })

    await userEvent.click(screen.getByRole('button', { name: 'Menu' }))
    await userEvent.click(screen.getByRole('link', { name: 'Collection' }))

    expect(await screen.findByRole('heading', { name: 'Collection', level: 1 })).toBeInTheDocument()
    expect(currentLocation().pathname).toBe('/collection')
  })

  it('says so when the collection was too large to load in full', async () => {
    // Otherwise the tab counts read as totals and a search quietly reports
    // "nothing matches" for a record the user definitely owns.
    mockFetch(routes(fakeCollection({ owned: [DRUKQS], truncated: true })))
    renderApp('/collection')
    await screen.findByRole('heading', { name: 'Drukqs', level: 2 })

    expect(screen.getByText(/counts below are not totals/i)).toBeInTheDocument()
  })

  it('shows no truncation warning for a normal collection', async () => {
    mockFetch(routes(fakeCollection({ owned: [DRUKQS] })))
    renderApp('/collection')
    await screen.findByRole('heading', { name: 'Drukqs', level: 2 })

    expect(screen.queryByText(/counts below are not totals/i)).not.toBeInTheDocument()
  })

  it('announces a load failure', async () => {
    mockFetch([
      ['/api/auth/me', fakeMe],
      ['/api/collection', { detail: 'boom' }, 500],
    ])
    renderApp('/collection')

    expect(await screen.findByRole('alert')).toHaveTextContent(/boom/i)
  })
})
