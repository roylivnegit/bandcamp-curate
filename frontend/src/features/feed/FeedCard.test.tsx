import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { fakeRec } from '../../test/renderApp'
import { FeedCard } from './FeedCard'

function renderCard(over: { busy?: boolean; bandId?: number | null } = {}) {
  const rec = fakeRec(over.bandId === undefined ? {} : { band_id: over.bandId })
  const onLike = vi.fn()
  const onBlock = vi.fn()
  const onTagClick = vi.fn()
  const onBandClick = vi.fn()
  render(
    <FeedCard
      rec={rec}
      exiting={null}
      busy={over.busy ?? false}
      onLike={onLike}
      onBlock={onBlock}
      onTagClick={onTagClick}
      onBandClick={onBandClick}
    />,
  )
  return { rec, onLike, onBlock, onTagClick, onBandClick }
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
    const { onLike } = renderCard({ busy: true })
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
