import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

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
})
