import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { PasswordInput } from './PasswordInput'

function renderWith(value = 'hunter22') {
  const onChange = vi.fn()
  render(<PasswordInput id="pw" autoComplete="current-password" value={value} onChange={onChange} />)
  return { onChange }
}

describe('PasswordInput', () => {
  it('starts masked, with a "Show" toggle', () => {
    renderWith()
    expect(document.getElementById('pw')).toHaveAttribute('type', 'password')
    const toggle = screen.getByRole('button', { name: 'Show' })
    expect(toggle).toHaveAttribute('aria-pressed', 'false')
  })

  it('reveals the value and flips to "Hide" on click, then back on a second click', () => {
    renderWith()

    fireEvent.click(screen.getByRole('button', { name: 'Show' }))
    expect(document.getElementById('pw')).toHaveAttribute('type', 'text')
    const hideToggle = screen.getByRole('button', { name: 'Hide' })
    expect(hideToggle).toHaveAttribute('aria-pressed', 'true')

    fireEvent.click(hideToggle)
    expect(document.getElementById('pw')).toHaveAttribute('type', 'password')
    expect(screen.getByRole('button', { name: 'Show' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('keeps the value/onChange wiring intact', () => {
    const { onChange } = renderWith()
    fireEvent.change(document.getElementById('pw') as HTMLInputElement, { target: { value: 'new-pw' } })
    expect(onChange).toHaveBeenCalledTimes(1)
  })

  it('passes autoComplete through to the underlying input', () => {
    render(<PasswordInput id="pw2" autoComplete="new-password" value="" onChange={vi.fn()} />)
    expect(document.getElementById('pw2')).toHaveAttribute('autocomplete', 'new-password')
  })
})
