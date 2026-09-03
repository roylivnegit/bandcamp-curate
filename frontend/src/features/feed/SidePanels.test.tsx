import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { Blocked, Liked } from '../../api/types'
import { SIDEPANEL_PAGE_SIZE } from '../../config'
import { BlockedPanel, LikedPanel } from './SidePanels'

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
        busy={() => false}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Show more' }))

    expect(screen.getAllByRole('button', { name: 'unblock' })).toHaveLength(30)
    expect(screen.queryByRole('button', { name: 'Show more' })).not.toBeInTheDocument()
  })
})
