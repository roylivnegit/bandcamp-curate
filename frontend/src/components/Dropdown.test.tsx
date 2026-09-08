import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Dropdown } from './Dropdown'

function renderOpenDropdown() {
  render(
    <Dropdown label="Sort">
      {() => (
        <div>
          <button type="button" className="ddrow">
            One
          </button>
          <button type="button" className="ddrow">
            Two
          </button>
          <button type="button" className="ddrow">
            Three
          </button>
        </div>
      )}
    </Dropdown>,
  )
  fireEvent.click(screen.getByRole('button', { name: 'Sort' }))
  return screen.getAllByRole('button', { name: /^(One|Two|Three)$/ })
}

describe('Dropdown arrow-key navigation', () => {
  it('moves focus down through the rows and wraps past the last one', () => {
    const rows = renderOpenDropdown()
    rows[0].focus()

    fireEvent.keyDown(rows[0], { key: 'ArrowDown' })
    expect(rows[1]).toHaveFocus()

    fireEvent.keyDown(rows[1], { key: 'ArrowDown' })
    expect(rows[2]).toHaveFocus()

    fireEvent.keyDown(rows[2], { key: 'ArrowDown' })
    expect(rows[0]).toHaveFocus()
  })

  it('moves focus up through the rows and wraps past the first one', () => {
    const rows = renderOpenDropdown()
    rows[0].focus()

    fireEvent.keyDown(rows[0], { key: 'ArrowUp' })
    expect(rows[2]).toHaveFocus()

    fireEvent.keyDown(rows[2], { key: 'ArrowUp' })
    expect(rows[1]).toHaveFocus()
  })

  it('jumps to the first row on Home and the last on End', () => {
    const rows = renderOpenDropdown()
    rows[1].focus()

    fireEvent.keyDown(rows[1], { key: 'End' })
    expect(rows[2]).toHaveFocus()

    fireEvent.keyDown(rows[2], { key: 'Home' })
    expect(rows[0]).toHaveFocus()
  })

  it('leaves a search input inside the panel alone — arrow keys only move focus among rows', () => {
    render(
      <Dropdown label="Genre">
        {() => (
          <div>
            <input className="ddsearch" placeholder="Search genres…" />
            <button type="button" className="ddrow">
              psybient
            </button>
          </div>
        )}
      </Dropdown>,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Genre' }))
    const input = screen.getByPlaceholderText('Search genres…')
    input.focus()

    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: 'Home' })

    expect(input).toHaveFocus()
  })
})

describe('Dropdown type-ahead', () => {
  function renderOpenLetterDropdown() {
    render(
      <Dropdown label="Genre">
        {() => (
          <div>
            <button type="button" className="ddrow">
              Apple
            </button>
            <button type="button" className="ddrow">
              Banana
            </button>
            <button type="button" className="ddrow">
              Avocado
            </button>
          </div>
        )}
      </Dropdown>,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Genre' }))
    return screen.getAllByRole('button', { name: /^(Apple|Banana|Avocado)$/ })
  }

  it('jumps to the next row starting with the pressed letter, cycling on repeat presses', () => {
    const rows = renderOpenLetterDropdown()
    const [apple, , avocado] = rows
    apple.focus()

    fireEvent.keyDown(apple, { key: 'a' })
    expect(avocado).toHaveFocus()

    fireEvent.keyDown(avocado, { key: 'a' })
    expect(apple).toHaveFocus()
  })

  it('ignores a letter key held with a modifier', () => {
    const rows = renderOpenLetterDropdown()
    const apple = rows[0]
    apple.focus()

    fireEvent.keyDown(apple, { key: 'a', ctrlKey: true })

    expect(apple).toHaveFocus()
  })
})

describe('Dropdown open/close focus management', () => {
  it('moves focus to the first row when the panel opens', () => {
    const rows = renderOpenDropdown()
    expect(rows[0]).toHaveFocus()
  })

  it('restores focus to the trigger button on Escape', () => {
    renderOpenDropdown()
    const trigger = screen.getByRole('button', { name: 'Sort' })

    fireEvent.keyDown(document, { key: 'Escape' })

    expect(trigger).toHaveFocus()
  })

  it('restores focus to the trigger button after selecting a row (the panel closing programmatically)', () => {
    render(
      <Dropdown label="Sort">
        {(close) => (
          <button type="button" className="ddrow" onClick={close}>
            Newest
          </button>
        )}
      </Dropdown>,
    )
    const trigger = screen.getByRole('button', { name: 'Sort' })
    fireEvent.click(trigger)

    fireEvent.click(screen.getByRole('button', { name: 'Newest' }))

    expect(trigger).toHaveFocus()
  })

  it('does not steal focus back to the trigger on an outside click', () => {
    render(
      <div>
        <Dropdown label="Sort">
          {() => (
            <button type="button" className="ddrow">
              Newest
            </button>
          )}
        </Dropdown>
        <button type="button">Elsewhere</button>
      </div>,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Sort' }))
    const elsewhere = screen.getByRole('button', { name: 'Elsewhere' })
    elsewhere.focus()

    fireEvent.mouseDown(elsewhere)

    expect(elsewhere).toHaveFocus()
  })
})
