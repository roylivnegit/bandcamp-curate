import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { fakeMe, fakeRec, fakeScan, mockFetch, renderApp } from '../../test/renderApp'

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
  })

  it('filters to one artist when the band name is clicked', async () => {
    mockFetch(feedRoutes())
    renderApp('/scans/1')
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: /Minds of Infinity/ }))

    expect(await screen.findByText(/artist:/)).toBeInTheDocument()
  })
})
