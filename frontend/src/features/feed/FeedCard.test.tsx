import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { fakeRec } from '../../test/renderApp'
import { FeedCard } from './FeedCard'

function renderCard(
  over: {
    busyAction?: 'like' | 'block' | null
    bandId?: number | null
    selectMode?: boolean
    selected?: boolean
    artUrl?: string | null
  } = {},
) {
  const rec = fakeRec({
    ...(over.bandId === undefined ? {} : { band_id: over.bandId }),
    ...(over.artUrl === undefined ? {} : { art_url: over.artUrl }),
  })
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

describe('FeedCard block button', () => {
  it('has no card-level duration picker — "⊘ block" is an immediate, permanent block', () => {
    const { onBlock, rec } = renderCard()

    expect(screen.queryByRole('button', { name: 'block for… ▾' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '⊘ block' }))

    expect(onBlock).toHaveBeenCalledTimes(1)
    expect(onBlock).toHaveBeenCalledWith(rec)
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

  it('toggles selection on a click anywhere on the card, not just the checkbox', () => {
    const { onToggleSelect, rec } = renderCard({ selectMode: true })

    // The title is plain card real estate — no button, link, or checkbox of
    // its own — so a click there has nothing else to do but select the card.
    fireEvent.click(screen.getByText(rec.title!))

    expect(onToggleSelect).toHaveBeenCalledTimes(1)
    expect(onToggleSelect).toHaveBeenCalledWith(rec)
  })

  it('does not toggle selection when the click hits an actual control', () => {
    const { onLike, onToggleSelect } = renderCard({ selectMode: true })

    fireEvent.click(screen.getByRole('button', { name: '♥ like' }))

    expect(onLike).toHaveBeenCalledTimes(1)
    expect(onToggleSelect).not.toHaveBeenCalled()
  })

  it('does not turn a plain click into a selection outside select mode', () => {
    const { onToggleSelect, rec } = renderCard()

    fireEvent.click(screen.getByText(rec.title!))

    expect(onToggleSelect).not.toHaveBeenCalled()
  })

  it('offers no click-to-select for a card with no band, same as its missing checkbox', () => {
    const { onToggleSelect, rec } = renderCard({ selectMode: true, bandId: null })

    fireEvent.click(screen.getByText(rec.title!))

    expect(onToggleSelect).not.toHaveBeenCalled()
  })
})

describe('FeedCard cover art', () => {
  it('renders no image when the item has no art_url', () => {
    renderCard({ artUrl: null })

    expect(document.querySelector('.card-art')).toBeNull()
  })

  it('renders a decorative image with the art_url as its src when present', () => {
    renderCard({ artUrl: 'https://f4.bcbits.com/img/a10_10.jpg' })

    const img = document.querySelector('.card-art') as HTMLImageElement
    expect(img).not.toBeNull()
    expect(img.src).toBe('https://f4.bcbits.com/img/a10_10.jpg')
    // Decorative — the title/artist text right next to it already identifies
    // the item, so an empty alt avoids a redundant screen-reader announcement.
    expect(img.alt).toBe('')
  })

  it('falls back to no image once the art URL fails to load, instead of a broken-image icon', () => {
    renderCard({ artUrl: 'https://f4.bcbits.com/img/a10_10.jpg' })

    const img = document.querySelector('.card-art') as HTMLImageElement
    fireEvent.error(img)

    expect(document.querySelector('.card-art')).toBeNull()
  })
})
