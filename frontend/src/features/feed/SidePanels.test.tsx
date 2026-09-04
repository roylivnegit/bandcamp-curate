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
})
