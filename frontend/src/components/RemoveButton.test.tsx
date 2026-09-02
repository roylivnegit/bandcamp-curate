import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { RemoveButton } from './RemoveButton'

describe('RemoveButton', () => {
  it('renders with the given accessible name and calls onClick when clicked', () => {
    const onClick = vi.fn()
    render(<RemoveButton label="Remove foo" onClick={onClick} />)

    const btn = screen.getByRole('button', { name: 'Remove foo' })
    expect(btn).toHaveClass('rm')

    fireEvent.click(btn)
    expect(onClick).toHaveBeenCalledTimes(1)
  })
})
