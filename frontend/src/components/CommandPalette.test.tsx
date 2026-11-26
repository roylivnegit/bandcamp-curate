import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { openCommandPalette } from '../lib/commandPalette'
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

function renderWithControls(
  list: CommandAction[],
  onOpen?: () => void,
  onSearch?: (query: string) => Promise<CommandAction[]>,
) {
  render(
    <div>
      <button type="button">Trigger</button>
      <CommandPalette actions={list} onOpen={onOpen} onSearch={onSearch} />
    </div>,
  )
}

/** A server result, as `App` maps one: a row the palette did not have locally. */
function remote(label: string, run = vi.fn()): CommandAction {
  return { id: `remote-${label}`, label, hint: 'owned', run }
}

describe('CommandPalette', () => {
  it('opens on Ctrl+K, focuses the search input, and lists every action', () => {
    const { list } = actions()
    renderWithControls(list)
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true })

    const dialog = screen.getByRole('dialog', { name: 'Command palette' })
    expect(dialog).toBeInTheDocument()
    const input = screen.getByRole('textbox', { name: 'Search' })
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

    const input = screen.getByRole('textbox', { name: 'Search' })
    fireEvent.change(input, { target: { value: 'ban' } })

    expect(screen.getAllByRole('option')).toHaveLength(1)
    expect(screen.getByRole('option', { name: 'Banana' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Alpha' })).not.toBeInTheDocument()
  })

  it('ranks a prefix match above a word-boundary match above a buried match', () => {
    const list: CommandAction[] = [
      { id: 'a', label: 'My Ambient Scan', run: vi.fn() }, // word-boundary ("Scan")
      { id: 'b', label: 'Vaporwave Deep Cuts', run: vi.fn() }, // no match at all
      { id: 'c', label: 'Scavenger Hunt', run: vi.fn() }, // prefix
    ]
    renderWithControls(list)
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true })

    fireEvent.change(screen.getByRole('textbox', { name: 'Search' }), { target: { value: 'sca' } })

    expect(screen.getAllByRole('option').map((el) => el.textContent)).toEqual([
      'Scavenger Hunt',
      'My Ambient Scan',
    ])
  })

  it('shows a "no matches" message instead of an empty list', () => {
    const { list } = actions()
    renderWithControls(list)
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true })

    fireEvent.change(screen.getByRole('textbox', { name: 'Search' }), {
      target: { value: 'zzz' },
    })

    expect(screen.queryAllByRole('option')).toHaveLength(0)
    expect(screen.getByText('No matches.')).toBeInTheDocument()
  })

  it('ArrowDown moves the highlight and Enter runs exactly that action', () => {
    const { list, runAlpha, runBravo, runBanana } = actions()
    renderWithControls(list)
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true })

    const input = screen.getByRole('textbox', { name: 'Search' })
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

    const input = screen.getByRole('textbox', { name: 'Search' })
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: 'ArrowDown' }) // already on Banana, stays put
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(runBanana).toHaveBeenCalledTimes(1)
  })

  it('End jumps to the last row and Home jumps back to the first', () => {
    const { list, runAlpha, runBanana } = actions()
    renderWithControls(list)
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true })

    const input = screen.getByRole('textbox', { name: 'Search' })
    fireEvent.keyDown(input, { key: 'End' })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(runBanana).toHaveBeenCalledTimes(1)

    fireEvent.keyDown(document, { key: 'k', ctrlKey: true }) // reopen, highlight resets to Alpha
    fireEvent.keyDown(screen.getByRole('textbox', { name: 'Search' }), { key: 'End' })
    fireEvent.keyDown(screen.getByRole('textbox', { name: 'Search' }), { key: 'Home' })
    fireEvent.keyDown(screen.getByRole('textbox', { name: 'Search' }), { key: 'Enter' })
    expect(runAlpha).toHaveBeenCalledTimes(1)
  })

  it('scrolls the highlighted row into view as ArrowDown moves it', () => {
    // jsdom doesn't implement scrollIntoView at all.
    const scrollIntoView = vi.fn()
    Element.prototype.scrollIntoView = scrollIntoView
    const { list } = actions()
    renderWithControls(list)
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true })
    scrollIntoView.mockClear() // drop the initial-open call for row 0

    const input = screen.getByRole('textbox', { name: 'Search' })
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
    fireEvent.change(screen.getByRole('textbox', { name: 'Search' }), {
      target: { value: 'ban' },
    })
    fireEvent.keyDown(document, { key: 'Escape' })

    fireEvent.keyDown(document, { key: 'k', ctrlKey: true })
    expect(screen.getByRole('textbox', { name: 'Search' })).toHaveValue('')
    expect(screen.getAllByRole('option')).toHaveLength(3)
  })

  it('opens when something outside it calls openCommandPalette', () => {
    const { list } = actions()
    renderWithControls(list)

    // `act`: this is a plain function call from outside React, not an event
    // the test library already wraps, so the state update it causes has to be
    // flushed explicitly.
    act(() => openCommandPalette())

    expect(screen.getByRole('dialog', { name: 'Command palette' })).toBeInTheDocument()
  })
})

describe('CommandPalette searching the server', () => {
  it('searches once the query is long enough, and lists the results under the local ones', async () => {
    const onSearch = vi.fn(async () => [remote('Drukqs — Aphex Twin')])
    const { list } = actions()
    renderWithControls(list, undefined, onSearch)
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true })

    fireEvent.change(screen.getByRole('textbox', { name: 'Search' }), {
      target: { value: 'alpha' },
    })

    expect(await screen.findByRole('option', { name: 'Drukqs — Aphex Twin' })).toBeInTheDocument()
    expect(onSearch).toHaveBeenCalledWith('alpha')
    // Local match first, server result after it — and both in one list, so the
    // arrow keys run straight through.
    expect(screen.getAllByRole('option').map((el) => el.textContent)).toEqual([
      'Alpha',
      'Drukqs — Aphex Twinowned',
    ])
  })

  it('does not ask the server for a query shorter than two characters', async () => {
    const onSearch = vi.fn(async () => [remote('Nope')])
    const { list } = actions()
    renderWithControls(list, undefined, onSearch)
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true })

    fireEvent.change(screen.getByRole('textbox', { name: 'Search' }), { target: { value: 'a' } })

    // The three local actions all contain an "a" and still filter locally —
    // what must not happen is a request, which at one character would be a
    // `%a%` scan of the whole collection for a list nobody can read anyway.
    await waitFor(() => expect(screen.getAllByRole('option')).toHaveLength(3))
    expect(onSearch).not.toHaveBeenCalled()
  })

  it('discards a slow answer that lands after the query moved on', async () => {
    /* The bug this prevents: type "aph", pause, keep typing to "aphex". The
     * first request is slower, so without a ticket its rows replace the ones
     * for the query actually in the box. */
    let releaseFirst: (rows: CommandAction[]) => void = () => {}
    const onSearch = vi.fn((q: string) =>
      q === 'alph'
        ? new Promise<CommandAction[]>((resolve) => {
            releaseFirst = resolve
          })
        : Promise.resolve([remote('Right answer')]),
    )
    const { list } = actions()
    renderWithControls(list, undefined, onSearch)
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true })
    const input = screen.getByRole('textbox', { name: 'Search' })

    fireEvent.change(input, { target: { value: 'alph' } })
    await waitFor(() => expect(onSearch).toHaveBeenCalledWith('alph'))
    fireEvent.change(input, { target: { value: 'alpha' } })
    expect(await screen.findByRole('option', { name: 'Right answer' })).toBeInTheDocument()

    releaseFirst([remote('Stale answer')])

    await waitFor(() =>
      expect(screen.queryByRole('option', { name: 'Stale answer' })).not.toBeInTheDocument(),
    )
    expect(screen.getByRole('option', { name: 'Right answer' })).toBeInTheDocument()
  })

  it('says it is searching rather than showing "No matches." while the answer is in flight', async () => {
    const onSearch = vi.fn(() => new Promise<CommandAction[]>(() => {}))
    const list: CommandAction[] = [] // nothing local, so the list is the search
    renderWithControls(list, undefined, onSearch)
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true })

    fireEvent.change(screen.getByRole('textbox', { name: 'Search' }), {
      target: { value: 'aphex' },
    })

    expect(await screen.findByText('Searching…')).toBeInTheDocument()
    expect(screen.queryByText('No matches.')).not.toBeInTheDocument()
  })

  it('announces a failed search instead of reporting no matches', async () => {
    const onSearch = vi.fn(async () => {
      throw new Error('offline')
    })
    renderWithControls([], undefined, onSearch)
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true })

    fireEvent.change(screen.getByRole('textbox', { name: 'Search' }), {
      target: { value: 'aphex' },
    })

    const note = await screen.findByRole('alert')
    expect(note).toHaveTextContent("Couldn't search right now.")
    expect(screen.queryByText('No matches.')).not.toBeInTheDocument()
  })

  it('Enter runs a server result, not just a local action', async () => {
    const run = vi.fn()
    const onSearch = vi.fn(async () => [remote('Drukqs', run)])
    renderWithControls([], undefined, onSearch)
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true })
    const input = screen.getByRole('textbox', { name: 'Search' })

    fireEvent.change(input, { target: { value: 'drukqs' } })
    await screen.findByRole('option', { name: 'Drukqs' })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(run).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('drops the previous results when the palette is reopened', async () => {
    const onSearch = vi.fn(async () => [remote('Drukqs')])
    renderWithControls([], undefined, onSearch)
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true })
    fireEvent.change(screen.getByRole('textbox', { name: 'Search' }), {
      target: { value: 'drukqs' },
    })
    await screen.findByRole('option', { name: 'Drukqs' })

    fireEvent.keyDown(document, { key: 'Escape' })
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true })

    expect(screen.queryByRole('option', { name: 'Drukqs' })).not.toBeInTheDocument()
    expect(screen.getByText('No matches.')).toBeInTheDocument()
  })
})
