import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ShortcutsHelp } from './ShortcutsHelp'

function renderWithControls() {
  render(
    <div>
      <button type="button">Trigger</button>
      <input aria-label="Search" />
      <ShortcutsHelp />
    </div>,
  )
}

describe('ShortcutsHelp', () => {
  it('opens on "?" and lists the shortcuts', () => {
    renderWithControls()
    fireEvent.keyDown(document, { key: '?' })

    const dialog = screen.getByRole('dialog', { name: 'Keyboard shortcuts' })
    expect(dialog).toBeInTheDocument()
    expect(dialog).toHaveTextContent('Like the focused recommendation')
    expect(dialog).toHaveTextContent("Block the focused recommendation's artist")
  })

  it('does not open while a text field has focus (typing a literal "?")', () => {
    renderWithControls()
    const input = screen.getByLabelText('Search')
    input.focus()
    fireEvent.keyDown(input, { key: '?' })

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('closes on Escape and returns focus to the element that had it before opening', () => {
    renderWithControls()
    const trigger = screen.getByRole('button', { name: 'Trigger' })
    trigger.focus()

    fireEvent.keyDown(document, { key: '?' })
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it('closes on an outside click, but not on a click inside the panel', () => {
    renderWithControls()
    fireEvent.keyDown(document, { key: '?' })
    const dialog = screen.getByRole('dialog')

    fireEvent.mouseDown(dialog)
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    fireEvent.mouseDown(document.body)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('toggles closed on a second "?" press', () => {
    renderWithControls()
    fireEvent.keyDown(document, { key: '?' })
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    fireEvent.keyDown(document, { key: '?' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
