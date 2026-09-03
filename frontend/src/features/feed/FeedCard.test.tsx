import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fakeRec } from '../../test/renderApp'
import { FeedCard } from './FeedCard'

function renderCard(
  over: {
    busyAction?: 'like' | 'block' | null
    bandId?: number | null
    selectMode?: boolean
    selected?: boolean
  } = {},
) {
  const rec = fakeRec(over.bandId === undefined ? {} : { band_id: over.bandId })
  const onLike = vi.fn()
  const onBlock = vi.fn()
  const onTagClick = vi.fn()
  const onBandClick = vi.fn()
  const onToggleSelect = vi.fn()
  render(
    <FeedCard
      rec={rec}
      cardId="card-test"
      active
      exiting={null}
      busyAction={over.busyAction ?? null}
      selectMode={over.selectMode ?? false}
      selected={over.selected ?? false}
      onLike={onLike}
      onBlock={onBlock}
      onTagClick={onTagClick}
      onBandClick={onBandClick}
      onToggleSelect={onToggleSelect}
    />,
  )
  return { rec, onLike, onBlock, onTagClick, onBandClick, onToggleSelect }
}

describe('FeedCard keyboard shortcuts', () => {
  it('likes the card on "l" when focus is anywhere inside it', () => {
    const { onLike, rec } = renderCard()
    screen.getByRole('button', { name: '♥ like' }).focus()

    fireEvent.keyDown(document.activeElement!, { key: 'l' })

    expect(onLike).toHaveBeenCalledTimes(1)
    expect(onLike).toHaveBeenCalledWith(rec)
  })

  it('blocks the card on "b" when focus is anywhere inside it', () => {
    const { onBlock, rec } = renderCard()
    // Focus on a different element within the card than the block button
    // itself, to confirm the listener is scoped to the card, not the button.
    screen.getByRole('button', { name: /Minds of Infinity/ }).focus()

    fireEvent.keyDown(document.activeElement!, { key: 'b' })

    expect(onBlock).toHaveBeenCalledTimes(1)
    expect(onBlock).toHaveBeenCalledWith(rec)
  })

  it('ignores the shortcut while the card is busy', () => {
    const { onLike } = renderCard({ busyAction: 'like' })
    screen.getByRole('button', { name: /Minds of Infinity/ }).focus()

    fireEvent.keyDown(document.activeElement!, { key: 'l' })

    expect(onLike).not.toHaveBeenCalled()
  })

  it('leaves browser/OS shortcuts alone when a modifier key is held', () => {
    const { onBlock } = renderCard()
    screen.getByRole('button', { name: /Minds of Infinity/ }).focus()

    fireEvent.keyDown(document.activeElement!, { key: 'b', metaKey: true })

    expect(onBlock).not.toHaveBeenCalled()
  })

  it('does not offer a block shortcut when the card has no band', () => {
    const { onBlock } = renderCard({ bandId: null })
    expect(screen.queryByRole('button', { name: '⊘ block' })).not.toBeInTheDocument()

    fireEvent.keyDown(screen.getByRole('button', { name: '♥ like' }), { key: 'b' })

    expect(onBlock).not.toHaveBeenCalled()
  })
})

describe('FeedCard pending-state microcopy', () => {
  it('shows plain labels when nothing is in flight', () => {
    renderCard()

    expect(screen.getByRole('button', { name: '♥ like' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '⊘ block' })).toBeInTheDocument()
  })

  it('swaps the like button to "Liking…" while a like is in flight, leaving block alone', () => {
    renderCard({ busyAction: 'like' })

    expect(screen.getByRole('button', { name: 'Liking…' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '♥ like' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '⊘ block' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Blocking…' })).not.toBeInTheDocument()
  })

  it('swaps the block button to "Blocking…" while a block is in flight, leaving like alone', () => {
    renderCard({ busyAction: 'block' })

    expect(screen.getByRole('button', { name: 'Blocking…' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '⊘ block' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '♥ like' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Liking…' })).not.toBeInTheDocument()
  })

  it('disables both action buttons while either is in flight', () => {
    renderCard({ busyAction: 'like' })

    expect(screen.getByRole('button', { name: 'Liking…' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '⊘ block' })).toBeDisabled()
  })
})

describe('FeedCard block-duration picker', () => {
  it('offers a temporary-block duration for a card with a band', () => {
    renderCard()
    expect(screen.getByRole('button', { name: 'block for… ▾' })).toBeInTheDocument()
  })

  it('offers no duration picker for a card with no band', () => {
    renderCard({ bandId: null })
    expect(screen.queryByRole('button', { name: 'block for… ▾' })).not.toBeInTheDocument()
  })

  it('hides the duration picker while either action is in flight', () => {
    renderCard({ busyAction: 'like' })
    expect(screen.queryByRole('button', { name: 'block for… ▾' })).not.toBeInTheDocument()
  })

  it('calls onBlock with an expiry computed from the chosen duration, then closes', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-03T00:00:00.000Z'))
    const { onBlock, rec } = renderCard()

    fireEvent.click(screen.getByRole('button', { name: 'block for… ▾' }))
    fireEvent.click(screen.getByRole('button', { name: '1 week' }))

    expect(onBlock).toHaveBeenCalledTimes(1)
    expect(onBlock).toHaveBeenCalledWith(rec, '2026-09-10T00:00:00.000Z')
    expect(screen.queryByRole('button', { name: '1 week' })).not.toBeInTheDocument()
    vi.useRealTimers()
  })

  it('leaves the plain "⊘ block" button as an immediate, permanent block', () => {
    const { onBlock, rec } = renderCard()

    fireEvent.click(screen.getByRole('button', { name: '⊘ block' }))

    expect(onBlock).toHaveBeenCalledTimes(1)
    expect(onBlock).toHaveBeenCalledWith(rec)
  })
})

describe('FeedCard "seen" marker', () => {
  beforeEach(() => localStorage.clear())

  it('shows no "seen" marker for a card never opened before', () => {
    renderCard()

    expect(screen.queryByText('seen')).not.toBeInTheDocument()
    expect(screen.getByRole('article')).not.toHaveAttribute('data-visited')
  })

  it('marks the card visited immediately after clicking "Bandcamp ↗"', () => {
    renderCard()

    fireEvent.click(screen.getByRole('link', { name: 'Bandcamp ↗' }))

    expect(screen.getByText('seen')).toBeInTheDocument()
    expect(screen.getByRole('article')).toHaveAttribute('data-visited', 'true')
  })

  it('starts already marked "seen" if this card id was visited in an earlier session', () => {
    localStorage.setItem('crate-digger.visited', JSON.stringify(['card-test']))

    renderCard()

    expect(screen.getByText('seen')).toBeInTheDocument()
    expect(screen.getByRole('article')).toHaveAttribute('data-visited', 'true')
  })

  it('does not mark an unrelated card visited', () => {
    localStorage.setItem('crate-digger.visited', JSON.stringify(['some-other-card']))

    renderCard()

    expect(screen.queryByText('seen')).not.toBeInTheDocument()
  })
})

describe('FeedCard bulk select', () => {
  it('shows no checkbox outside select mode', () => {
    renderCard()
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  })

  it('shows an unchecked checkbox in select mode for a card with a band', () => {
    renderCard({ selectMode: true })
    expect(screen.getByRole('checkbox')).not.toBeChecked()
  })

  it('offers no checkbox in select mode for a card with no band', () => {
    renderCard({ selectMode: true, bandId: null })
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  })

  it('reflects the selected prop and calls onToggleSelect when clicked', () => {
    const { onToggleSelect, rec } = renderCard({ selectMode: true, selected: true })
    const box = screen.getByRole('checkbox')
    expect(box).toBeChecked()

    fireEvent.click(box)

    expect(onToggleSelect).toHaveBeenCalledTimes(1)
    expect(onToggleSelect).toHaveBeenCalledWith(rec)
  })
})
