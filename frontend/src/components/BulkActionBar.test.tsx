import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { BULK_CONFIRM_THRESHOLD, BULK_CONFIRM_WINDOW_MS } from '../config'
import { BulkActionBar } from './BulkActionBar'

describe('BulkActionBar', () => {
  it('renders nothing when the selection is empty', () => {
    const { container } = render(
      <BulkActionBar count={0} busy={false} onBlock={vi.fn()} onCancel={vi.fn()} />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('shows the count and calls onBlock/onCancel from their respective buttons', () => {
    const onBlock = vi.fn()
    const onCancel = vi.fn()
    render(<BulkActionBar count={3} busy={false} onBlock={onBlock} onCancel={onCancel} />)

    expect(screen.getByText('3')).toBeInTheDocument()
    expect(screen.getByText('selected')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Block selected' }))
    expect(onBlock).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onCancel).toHaveBeenCalledTimes(1)
  })

  it('disables both buttons and relabels Block while busy', () => {
    render(<BulkActionBar count={2} busy={true} onBlock={vi.fn()} onCancel={vi.fn()} />)

    expect(screen.getByRole('button', { name: 'Blocking…' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled()
  })

  describe('confirm step above the threshold', () => {
    afterEach(() => {
      vi.useRealTimers()
    })

    const overThreshold = BULK_CONFIRM_THRESHOLD + 1

    it('requires a second click above the threshold, and does not block on the first', () => {
      const onBlock = vi.fn()
      render(<BulkActionBar count={overThreshold} busy={false} onBlock={onBlock} onCancel={vi.fn()} />)

      fireEvent.click(screen.getByRole('button', { name: 'Block selected' }))
      expect(onBlock).not.toHaveBeenCalled()
      expect(screen.getByRole('button', { name: `Block ${overThreshold} bands?` })).toBeInTheDocument()

      fireEvent.click(screen.getByRole('button', { name: `Block ${overThreshold} bands?` }))
      expect(onBlock).toHaveBeenCalledTimes(1)
    })

    it('blocks immediately at or below the threshold — no confirm step', () => {
      const onBlock = vi.fn()
      render(
        <BulkActionBar count={BULK_CONFIRM_THRESHOLD} busy={false} onBlock={onBlock} onCancel={vi.fn()} />,
      )

      fireEvent.click(screen.getByRole('button', { name: 'Block selected' }))
      expect(onBlock).toHaveBeenCalledTimes(1)
      expect(screen.queryByText(/bands\?/)).not.toBeInTheDocument()
    })

    it('canceling the confirm step returns to the normal bar without blocking', () => {
      const onBlock = vi.fn()
      const onCancel = vi.fn()
      render(<BulkActionBar count={overThreshold} busy={false} onBlock={onBlock} onCancel={onCancel} />)

      fireEvent.click(screen.getByRole('button', { name: 'Block selected' }))
      fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))

      expect(onBlock).not.toHaveBeenCalled()
      expect(onCancel).not.toHaveBeenCalled()
      expect(screen.getByRole('button', { name: 'Block selected' })).toBeInTheDocument()
    })

    it('the armed confirm reverts on its own after the confirm window elapses', () => {
      vi.useFakeTimers()
      render(<BulkActionBar count={overThreshold} busy={false} onBlock={vi.fn()} onCancel={vi.fn()} />)

      fireEvent.click(screen.getByRole('button', { name: 'Block selected' }))
      expect(screen.getByRole('button', { name: `Block ${overThreshold} bands?` })).toBeInTheDocument()

      act(() => {
        vi.advanceTimersByTime(BULK_CONFIRM_WINDOW_MS)
      })

      expect(screen.getByRole('button', { name: 'Block selected' })).toBeInTheDocument()
    })
  })
})
