import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { Blocked, Liked, ScanSeed } from '../../api/types'
import { SIDEPANEL_PAGE_SIZE } from '../../config'
import { BlockedPanel, LikedPanel, SeedsPanel } from './SidePanels'

function makeLiked(n: number): Liked[] {
  return Array.from({ length: n }, (_, i) => ({
    id: i,
    item_type: 'album',
    album_id: i,
    track_id: null,
    title: `Album ${i}`,
    band_name: `Band ${i}`,
    url: null,
  }))
}

function makeBlocked(n: number): Blocked[] {
  return Array.from({ length: n }, (_, i) => ({
    id: i,
    band_id: i,
    band_name: `Band ${i}`,
    band_url: null,
    reason: null,
    expires_at: null,
  }))
}

describe('LikedPanel row cap', () => {
  it('renders only the first page of rows, with a Show more button', () => {
    render(<LikedPanel items={makeLiked(30)} onUnlike={() => {}} busy={() => false} />)

    expect(screen.getAllByRole('button', { name: 'unlike' })).toHaveLength(SIDEPANEL_PAGE_SIZE)
    expect(screen.getByRole('button', { name: 'Show more' })).toBeInTheDocument()
  })

  it('reveals the rest on Show more, and hides the button once everything is shown', () => {
    render(<LikedPanel items={makeLiked(30)} onUnlike={() => {}} busy={() => false} />)

    fireEvent.click(screen.getByRole('button', { name: 'Show more' }))

    expect(screen.getAllByRole('button', { name: 'unlike' })).toHaveLength(30)
    expect(screen.queryByRole('button', { name: 'Show more' })).not.toBeInTheDocument()
  })

  it('shows no Show more button when everything already fits on one page', () => {
    render(<LikedPanel items={makeLiked(5)} onUnlike={() => {}} busy={() => false} />)

    expect(screen.getAllByRole('button', { name: 'unlike' })).toHaveLength(5)
    expect(screen.queryByRole('button', { name: 'Show more' })).not.toBeInTheDocument()
  })
})

describe('LikedPanel search', () => {
  it('narrows to matching rows by title or band name', () => {
    const items = makeLiked(3)
    items[0].title = 'Eyes of Infinity'
    items[1].title = 'Minds Collide'
    items[2].band_name = 'Infinity Records'
    render(<LikedPanel items={items} onUnlike={() => {}} busy={() => false} />)

    fireEvent.change(screen.getByLabelText('Search liked items'), { target: { value: 'infinity' } })

    expect(screen.getByText('Eyes of Infinity')).toBeInTheDocument()
    expect(screen.getByText('Infinity Records')).toBeInTheDocument()
    expect(screen.queryByText('Minds Collide')).not.toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'unlike' })).toHaveLength(2)
  })

  it('shows a distinct message when nothing matches, not the "nothing liked yet" one', () => {
    render(<LikedPanel items={makeLiked(3)} onUnlike={() => {}} busy={() => false} />)

    fireEvent.change(screen.getByLabelText('Search liked items'), { target: { value: 'nope' } })

    expect(screen.getByText('No matches for “nope”.')).toBeInTheDocument()
    expect(screen.queryByText(/Nothing liked yet/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'unlike' })).not.toBeInTheDocument()
  })

  it('shows no search box at all when there is nothing liked', () => {
    render(<LikedPanel items={[]} onUnlike={() => {}} busy={() => false} />)

    expect(screen.queryByLabelText('Search liked items')).not.toBeInTheDocument()
    expect(screen.getByText(/Nothing liked yet/)).toBeInTheDocument()
  })
})

describe('BlockedPanel row cap', () => {
  it('renders only the first page of rows, with a Show more button', () => {
    render(
      <BlockedPanel
        items={makeBlocked(30)}
        onUnblock={() => {}}
        onRenew={() => {}}
        onSetReason={() => {}}
        busy={() => false}
      />,
    )

    expect(screen.getAllByRole('button', { name: 'unblock' })).toHaveLength(SIDEPANEL_PAGE_SIZE)
    expect(screen.getByRole('button', { name: 'Show more' })).toBeInTheDocument()
  })

  it('reveals the rest on Show more', () => {
    render(
      <BlockedPanel
        items={makeBlocked(30)}
        onUnblock={() => {}}
        onRenew={() => {}}
        onSetReason={() => {}}
        busy={() => false}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Show more' }))

    expect(screen.getAllByRole('button', { name: 'unblock' })).toHaveLength(30)
    expect(screen.queryByRole('button', { name: 'Show more' })).not.toBeInTheDocument()
  })
})

describe('BlockedPanel reason', () => {
  it('shows an existing reason next to the band name', () => {
    const items = makeBlocked(1)
    items[0].reason = 'too much noise'
    render(
      <BlockedPanel items={items} onUnblock={() => {}} onRenew={() => {}} onSetReason={() => {}} busy={() => false} />,
    )

    expect(screen.getByText(/too much noise/)).toBeInTheDocument()
  })

  it('shows no reason text when none is set', () => {
    render(
      <BlockedPanel
        items={makeBlocked(1)}
        onUnblock={() => {}}
        onRenew={() => {}}
        onSetReason={() => {}}
        busy={() => false}
      />,
    )

    expect(screen.getByLabelText('Reason for blocking Band 0')).toHaveValue('')
  })

  it('saves a typed reason on Enter', () => {
    const onSetReason = vi.fn()
    render(
      <BlockedPanel
        items={makeBlocked(1)}
        onUnblock={() => {}}
        onRenew={() => {}}
        onSetReason={onSetReason}
        busy={() => false}
      />,
    )

    const input = screen.getByLabelText('Reason for blocking Band 0')
    fireEvent.change(input, { target: { value: 'too repetitive' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(onSetReason).toHaveBeenCalledWith(0, 'too repetitive')
  })

  it('does not save on Enter when the text is unchanged or blank', () => {
    const items = makeBlocked(1)
    items[0].reason = 'too much noise'
    const onSetReason = vi.fn()
    render(
      <BlockedPanel items={items} onUnblock={() => {}} onRenew={() => {}} onSetReason={onSetReason} busy={() => false} />,
    )

    const input = screen.getByLabelText('Reason for blocking Band 0')
    fireEvent.keyDown(input, { key: 'Enter' })
    fireEvent.change(input, { target: { value: '   ' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(onSetReason).not.toHaveBeenCalled()
  })

  it('saves a typed reason on blur', () => {
    const onSetReason = vi.fn()
    render(
      <BlockedPanel
        items={makeBlocked(1)}
        onUnblock={() => {}}
        onRenew={() => {}}
        onSetReason={onSetReason}
        busy={() => false}
      />,
    )

    const input = screen.getByLabelText('Reason for blocking Band 0')
    fireEvent.change(input, { target: { value: 'too repetitive' } })
    fireEvent.blur(input)

    expect(onSetReason).toHaveBeenCalledWith(0, 'too repetitive')
  })

  it('does not save on blur when the text is unchanged or blank', () => {
    const items = makeBlocked(1)
    items[0].reason = 'too much noise'
    const onSetReason = vi.fn()
    render(
      <BlockedPanel items={items} onUnblock={() => {}} onRenew={() => {}} onSetReason={onSetReason} busy={() => false} />,
    )

    const input = screen.getByLabelText('Reason for blocking Band 0')
    fireEvent.blur(input)
    fireEvent.change(input, { target: { value: '   ' } })
    fireEvent.blur(input)

    expect(onSetReason).not.toHaveBeenCalled()
  })

  it('Escape reverts a typed reason without saving it', () => {
    const items = makeBlocked(1)
    items[0].reason = 'too much noise'
    const onSetReason = vi.fn()
    render(
      <BlockedPanel items={items} onUnblock={() => {}} onRenew={() => {}} onSetReason={onSetReason} busy={() => false} />,
    )

    const input = screen.getByLabelText('Reason for blocking Band 0')
    fireEvent.change(input, { target: { value: 'a stray keystroke' } })
    fireEvent.keyDown(input, { key: 'Escape' })

    expect(input).toHaveValue('too much noise')
    expect(onSetReason).not.toHaveBeenCalled()
  })

  it('Escape on a reason that was never set reverts to blank without saving', () => {
    const onSetReason = vi.fn()
    render(
      <BlockedPanel
        items={makeBlocked(1)}
        onUnblock={() => {}}
        onRenew={() => {}}
        onSetReason={onSetReason}
        busy={() => false}
      />,
    )

    const input = screen.getByLabelText('Reason for blocking Band 0')
    fireEvent.change(input, { target: { value: 'oops' } })
    fireEvent.keyDown(input, { key: 'Escape' })

    expect(input).toHaveValue('')
    expect(onSetReason).not.toHaveBeenCalled()
  })

  it('does not re-save on blur while a save for this row is already in flight', () => {
    const onSetReason = vi.fn()
    render(
      <BlockedPanel
        items={makeBlocked(1)}
        onUnblock={() => {}}
        onRenew={() => {}}
        onSetReason={onSetReason}
        busy={() => true}
      />,
    )

    const input = screen.getByLabelText('Reason for blocking Band 0')
    fireEvent.change(input, { target: { value: 'too repetitive' } })
    fireEvent.blur(input)

    expect(onSetReason).not.toHaveBeenCalled()
  })
})

describe('BlockedPanel search', () => {
  it('narrows to matching rows by band name or reason', () => {
    const items = makeBlocked(3)
    items[0].band_name = 'Noisy Label'
    items[1].band_name = 'Quiet Label'
    items[1].reason = 'too repetitive'
    items[2].band_name = 'Another Act'
    render(
      <BlockedPanel items={items} onUnblock={() => {}} onRenew={() => {}} onSetReason={() => {}} busy={() => false} />,
    )

    fireEvent.change(screen.getByLabelText('Search blocked artists'), { target: { value: 'repetitive' } })

    expect(screen.getByText(/Quiet Label/)).toBeInTheDocument()
    expect(screen.queryByText(/Noisy Label/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Another Act/)).not.toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'unblock' })).toHaveLength(1)
  })

  it('shows a distinct message when nothing matches, not the "nothing blocked yet" one', () => {
    render(
      <BlockedPanel
        items={makeBlocked(3)}
        onUnblock={() => {}}
        onRenew={() => {}}
        onSetReason={() => {}}
        busy={() => false}
      />,
    )

    fireEvent.change(screen.getByLabelText('Search blocked artists'), { target: { value: 'nope' } })

    expect(screen.getByText('No matches for “nope”.')).toBeInTheDocument()
    expect(screen.queryByText(/Nothing blocked yet/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'unblock' })).not.toBeInTheDocument()
  })

  it('shows no search box at all when there is nothing blocked', () => {
    render(
      <BlockedPanel items={[]} onUnblock={() => {}} onRenew={() => {}} onSetReason={() => {}} busy={() => false} />,
    )

    expect(screen.queryByLabelText('Search blocked artists')).not.toBeInTheDocument()
    expect(screen.getByText(/Nothing blocked yet/)).toBeInTheDocument()
  })
})

describe('SeedsPanel', () => {
  const seeds: ScanSeed[] = [
    { url: 'https://a.bandcamp.com/album/one', seed_type: 'album', resolved_album_id: 1, resolved_track_id: null },
    { url: 'https://b.bandcamp.com/track/two', seed_type: 'track', resolved_album_id: null, resolved_track_id: null },
  ]

  it('shows every seed url and its resolution status', () => {
    render(<SeedsPanel items={seeds} scanStatus="running" />)

    expect(screen.getByText('https://a.bandcamp.com/album/one')).toBeInTheDocument()
    expect(screen.getByText('Resolved')).toBeInTheDocument()
    expect(screen.getByText('https://b.bandcamp.com/track/two')).toBeInTheDocument()
    expect(screen.getByText('Pending')).toBeInTheDocument()
  })

  it('labels a still-unresolved seed "Not found" once the scan has finished', () => {
    render(<SeedsPanel items={seeds} scanStatus="done" />)

    expect(screen.getByText('Resolved')).toBeInTheDocument()
    expect(screen.getByText('Not found')).toBeInTheDocument()
  })

  it('announces a seed resolving via a live region, not just a silent re-render', () => {
    const pending: ScanSeed[] = [
      { url: 'https://a.bandcamp.com/album/one', seed_type: 'album', resolved_album_id: null, resolved_track_id: null },
    ]
    const { rerender } = render(<SeedsPanel items={pending} scanStatus="running" />)

    const status = screen.getByRole('status')
    expect(status).toHaveTextContent('Pending')

    rerender(<SeedsPanel items={seeds} scanStatus="running" />)
    expect(status).toHaveTextContent('Resolved')
  })
})
