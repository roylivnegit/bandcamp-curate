import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { CommandPalette, type CommandAction } from './CommandPalette'

function actions(overrides: Partial<Record<'alpha' | 'bravo' | 'banana', () => void>> = {}) {
  const runAlpha = overrides.alpha ?? vi.fn()
  const runBravo = overrides.bravo ?? vi.fn()
  const runBanana = overrides.banana ?? vi.fn()
  const list: CommandAction[] = [
    { id: 'alpha', label: 'Alpha', run: runAlpha },
    { id: 'bravo', label: 'Bravo', run: runBravo },
    { id: 'banana', label: 'Banana', run: runBanana },
  ]
  return { list, runAlpha, runBravo, runBanana }
}

function renderWithControls(list: CommandAction[], onOpen?: () => void) {
  render(
    <div>
      <button type="button">Trigger</button>
      <CommandPalette actions={list} onOpen={onOpen} />
    </div>,
  )
}

describe('CommandPalette', () => {
  it('opens on Ctrl+K, focuses the search input, and lists every action', () => {
    const { list } = actions()
    renderWithControls(list)
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true })

    const dialog = screen.getByRole('dialog', { name: 'Command palette' })
    expect(dialog).toBeInTheDocument()
    const input = screen.getByRole('textbox', { name: 'Jump to…' })
    expect(input).toHaveFocus()
    expect(screen.getByRole('option', { name: 'Alpha' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Bravo' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Banana' })).toBeInTheDocument()
  })

  it('also opens on Cmd+K (metaKey)', () => {
    const { list } = actions()
    renderWithControls(list)
    fireEvent.keyDown(document, { key: 'k', metaKey: true })

    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('calls onOpen each time it opens, so the caller can refresh what backs the actions', () => {
    const onOpen = vi.fn()
    const { list } = actions()
    renderWithControls(list, onOpen)

    fireEvent.keyDown(document, { key: 'k', ctrlKey: true })
    expect(onOpen).toHaveBeenCalledTimes(1)

    fireEvent.keyDown(document, { key: 'Escape' })
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true })
    expect(onOpen).toHaveBeenCalledTimes(2)
  })

  it('narrows the list to actions whose label matches the typed text', () => {
    const { list } = actions()
    renderWithControls(list)
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true })

    const input = screen.getByRole('textbox', { name: 'Jump to…' })
    fireEvent.change(input, { target: { value: 'ban' } })

    expect(screen.getAllByRole('option')).toHaveLength(1)
    expect(screen.getByRole('option', { name: 'Banana' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Alpha' })).not.toBeInTheDocument()
  })

  it('shows a "no matches" message instead of an empty list', () => {
    const { list } = actions()
    renderWithControls(list)
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true })

    fireEvent.change(screen.getByRole('textbox', { name: 'Jump to…' }), {
      target: { value: 'zzz' },
    })

    expect(screen.queryAllByRole('option')).toHaveLength(0)
    expect(screen.getByText('No matches.')).toBeInTheDocument()
  })

  it('ArrowDown moves the highlight and Enter runs exactly that action', () => {
    const { list, runAlpha, runBravo, runBanana } = actions()
    renderWithControls(list)
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true })

    const input = screen.getByRole('textbox', { name: 'Jump to…' })
    fireEvent.keyDown(input, { key: 'ArrowDown' }) // Alpha -> Bravo
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(runBravo).toHaveBeenCalledTimes(1)
    expect(runAlpha).not.toHaveBeenCalled()
    expect(runBanana).not.toHaveBeenCalled()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('ArrowDown does not move past the last row', () => {
    const { list, runBanana } = actions()
    renderWithControls(list)
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true })

    const input = screen.getByRole('textbox', { name: 'Jump to…' })
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: 'ArrowDown' }) // already on Banana, stays put
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(runBanana).toHaveBeenCalledTimes(1)
  })

  it('scrolls the highlighted row into view as ArrowDown moves it', () => {
    // jsdom doesn't implement scrollIntoView at all.
    const scrollIntoView = vi.fn()
    Element.prototype.scrollIntoView = scrollIntoView
    const { list } = actions()
    renderWithControls(list)
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true })
    scrollIntoView.mockClear() // drop the initial-open call for row 0

    const input = screen.getByRole('textbox', { name: 'Jump to…' })
    fireEvent.keyDown(input, { key: 'ArrowDown' })

    expect(scrollIntoView).toHaveBeenCalledWith({ block: 'nearest' })
  })

  it('a mouse click on a row runs its action and closes the palette', () => {
    const { list, runAlpha } = actions()
    renderWithControls(list)
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true })

    fireEvent.click(screen.getByRole('option', { name: 'Alpha' }))

    expect(runAlpha).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('closes on Escape and returns focus to the element that had it before opening', () => {
    const { list } = actions()
    renderWithControls(list)
    const trigger = screen.getByRole('button', { name: 'Trigger' })
    trigger.focus()

    fireEvent.keyDown(document, { key: 'k', ctrlKey: true })
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it('closes on an outside click, but not on a click inside the panel', () => {
    const { list } = actions()
    renderWithControls(list)
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true })
    const dialog = screen.getByRole('dialog')

    fireEvent.mouseDown(dialog)
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    fireEvent.mouseDown(document.body)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('toggles closed on a second Ctrl+K press', () => {
    const { list } = actions()
    renderWithControls(list)
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true })
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    fireEvent.keyDown(document, { key: 'k', ctrlKey: true })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('resets the query and highlight each time it reopens', () => {
    const { list } = actions()
    renderWithControls(list)
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true })
    fireEvent.change(screen.getByRole('textbox', { name: 'Jump to…' }), {
      target: { value: 'ban' },
    })
    fireEvent.keyDown(document, { key: 'Escape' })

    fireEvent.keyDown(document, { key: 'k', ctrlKey: true })
    expect(screen.getByRole('textbox', { name: 'Jump to…' })).toHaveValue('')
    expect(screen.getAllByRole('option')).toHaveLength(3)
  })
})
