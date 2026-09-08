import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { BULK_CONFIRM_THRESHOLD, BULK_CONFIRM_WINDOW_MS } from '../config'
import { BulkActionBar } from './BulkActionBar'

describe('BulkActionBar', () => {
  it('renders nothing when the selection is empty', () => {
    const { container } = render(
      <BulkActionBar count={0} busyAction={null} onLike={vi.fn()} onBlock={vi.fn()} onCancel={vi.fn()} />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('shows the count and calls onLike/onBlock/onCancel from their respective buttons', () => {
    const onLike = vi.fn()
    const onBlock = vi.fn()
    const onCancel = vi.fn()
    render(<BulkActionBar count={3} busyAction={null} onLike={onLike} onBlock={onBlock} onCancel={onCancel} />)

    expect(screen.getByText('3')).toBeInTheDocument()
    expect(screen.getByText('selected')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Like selected' }))
    expect(onLike).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByRole('button', { name: 'Block selected' }))
    expect(onBlock).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onCancel).toHaveBeenCalledTimes(1)
  })

  it('"Like selected" fires immediately with no confirm step, at any count', () => {
    const onLike = vi.fn()
    const overThreshold = BULK_CONFIRM_THRESHOLD + 1
    render(
      <BulkActionBar count={overThreshold} busyAction={null} onLike={onLike} onBlock={vi.fn()} onCancel={vi.fn()} />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Like selected' }))
    expect(onLike).toHaveBeenCalledTimes(1)
    expect(screen.queryByText(/Like \d+/)).not.toBeInTheDocument()
  })

  it('disables all three buttons and relabels the busy action while a bulk action is in flight', () => {
    render(
      <BulkActionBar count={2} busyAction="block" onLike={vi.fn()} onBlock={vi.fn()} onCancel={vi.fn()} />,
    )

    expect(screen.getByRole('button', { name: 'Blocking…' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Like selected' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled()
  })

  it('relabels "Like selected" to "Liking…" while a bulk like is in flight', () => {
    render(<BulkActionBar count={2} busyAction="like" onLike={vi.fn()} onBlock={vi.fn()} onCancel={vi.fn()} />)

    expect(screen.getByRole('button', { name: 'Liking…' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Block selected' })).toBeDisabled()
  })

  describe('confirm step above the threshold (block only)', () => {
    afterEach(() => {
      vi.useRealTimers()
    })

    const overThreshold = BULK_CONFIRM_THRESHOLD + 1

    it('requires a second click above the threshold, and does not block on the first', () => {
      const onBlock = vi.fn()
      render(
        <BulkActionBar count={overThreshold} busyAction={null} onLike={vi.fn()} onBlock={onBlock} onCancel={vi.fn()} />,
      )

      fireEvent.click(screen.getByRole('button', { name: 'Block selected' }))
      expect(onBlock).not.toHaveBeenCalled()
      expect(screen.getByRole('button', { name: `Block ${overThreshold} bands?` })).toBeInTheDocument()

      fireEvent.click(screen.getByRole('button', { name: `Block ${overThreshold} bands?` }))
      expect(onBlock).toHaveBeenCalledTimes(1)
    })

    it('blocks immediately at or below the threshold — no confirm step', () => {
      const onBlock = vi.fn()
      render(
        <BulkActionBar
          count={BULK_CONFIRM_THRESHOLD}
          busyAction={null}
          onLike={vi.fn()}
          onBlock={onBlock}
          onCancel={vi.fn()}
        />,
      )

      fireEvent.click(screen.getByRole('button', { name: 'Block selected' }))
      expect(onBlock).toHaveBeenCalledTimes(1)
      expect(screen.queryByText(/bands\?/)).not.toBeInTheDocument()
    })

    it('canceling the confirm step returns to the normal bar without blocking', () => {
      const onBlock = vi.fn()
      const onCancel = vi.fn()
      render(
        <BulkActionBar
          count={overThreshold}
          busyAction={null}
          onLike={vi.fn()}
          onBlock={onBlock}
          onCancel={onCancel}
        />,
      )

      fireEvent.click(screen.getByRole('button', { name: 'Block selected' }))
      fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))

      expect(onBlock).not.toHaveBeenCalled()
      expect(onCancel).not.toHaveBeenCalled()
      expect(screen.getByRole('button', { name: 'Block selected' })).toBeInTheDocument()
    })

    it('the armed confirm reverts on its own after the confirm window elapses', () => {
      vi.useFakeTimers()
      render(
        <BulkActionBar
          count={overThreshold}
          busyAction={null}
          onLike={vi.fn()}
          onBlock={vi.fn()}
          onCancel={vi.fn()}
        />,
      )

      fireEvent.click(screen.getByRole('button', { name: 'Block selected' }))
      expect(screen.getByRole('button', { name: `Block ${overThreshold} bands?` })).toBeInTheDocument()

      act(() => {
        vi.advanceTimersByTime(BULK_CONFIRM_WINDOW_MS)
      })

      expect(screen.getByRole('button', { name: 'Block selected' })).toBeInTheDocument()
    })
  })
})
