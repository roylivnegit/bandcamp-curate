import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { NewScanForm } from './NewScanForm'

function renderForm(existingNames: string[] = []) {
  render(<NewScanForm onCreated={() => {}} onCancel={() => {}} existingNames={existingNames} />)
}

function addViaButton(url: string) {
  fireEvent.change(screen.getByLabelText('Seed releases'), { target: { value: url } })
  fireEvent.click(screen.getByRole('button', { name: 'Add' }))
}

function pasteInto(text: string) {
  fireEvent.paste(screen.getByLabelText('Seed releases'), {
    clipboardData: { getData: () => text },
  })
}

describe('NewScanForm seed URL validation', () => {
  it('rejects a non-Bandcamp string and shows an alert without adding it', () => {
    renderForm()
    addViaButton('not a url')

    expect(screen.getByRole('alert')).toHaveTextContent(/bandcamp album or track url/i)
    expect(screen.queryByRole('list')).not.toBeInTheDocument()
  })

  it('rejects a well-formed URL that is not an /album/ or /track/ path', () => {
    renderForm()
    addViaButton('https://artist.bandcamp.com/merch/hoodie')

    expect(screen.getByRole('alert')).toHaveTextContent(/bandcamp album or track url/i)
    expect(screen.queryByRole('list')).not.toBeInTheDocument()
  })

  it('accepts a valid album URL with no alert', () => {
    renderForm()
    addViaButton('https://artist.bandcamp.com/album/some-release')

    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByText('https://artist.bandcamp.com/album/some-release')).toBeInTheDocument()
  })

  it('accepts a valid track URL and clears an earlier error', () => {
    renderForm()
    addViaButton('nope')
    expect(screen.getByRole('alert')).toBeInTheDocument()

    addViaButton('https://artist.bandcamp.com/track/some-song')

    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByText('https://artist.bandcamp.com/track/some-song')).toBeInTheDocument()
  })

  it('shows an alert and keeps the list at one entry when re-adding the same URL', () => {
    renderForm()
    addViaButton('https://artist.bandcamp.com/album/some-release')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()

    addViaButton('https://artist.bandcamp.com/album/some-release')

    expect(screen.getByRole('alert')).toHaveTextContent('Already in your seed list.')
    expect(screen.getAllByRole('listitem')).toHaveLength(1)
  })

  it('rejects a cosmetically-different duplicate (trailing slash, different host case)', () => {
    renderForm()
    addViaButton('https://artist.bandcamp.com/album/some-release')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()

    addViaButton('https://Artist.BandCamp.com/album/some-release/')

    expect(screen.getByRole('alert')).toHaveTextContent('Already in your seed list.')
    expect(screen.getAllByRole('listitem')).toHaveLength(1)
    // the original, as typed, is what's kept — not silently rewritten
    expect(screen.getByText('https://artist.bandcamp.com/album/some-release')).toBeInTheDocument()
  })

  it('also rejects an invalid URL submitted via Enter', () => {
    renderForm()
    const input = screen.getByLabelText('Seed releases')
    fireEvent.change(input, { target: { value: 'ftp://not-bandcamp/album/x' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.queryByRole('list')).not.toBeInTheDocument()
  })
})

describe('NewScanForm multi-URL paste', () => {
  it('splits a multi-line paste into individual seeds, keeping only the valid lines', () => {
    renderForm()
    pasteInto(
      [
        'https://a.bandcamp.com/album/one',
        'not a url',
        'https://b.bandcamp.com/track/two',
        'https://c.bandcamp.com/album/three',
      ].join('\n'),
    )

    expect(screen.getAllByRole('listitem')).toHaveLength(3)
    expect(screen.getByText('https://a.bandcamp.com/album/one')).toBeInTheDocument()
    expect(screen.getByText('https://b.bandcamp.com/track/two')).toBeInTheDocument()
    expect(screen.getByText('https://c.bandcamp.com/album/three')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('shows an alert and adds nothing when every pasted line is invalid', () => {
    renderForm()
    pasteInto(['nope', 'also nope'].join('\n'))

    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.queryByRole('list')).not.toBeInTheDocument()
  })

  it('dedupes pasted lines against already-added seeds and against each other', () => {
    renderForm()
    addViaButton('https://a.bandcamp.com/album/one')
    pasteInto(
      [
        'https://a.bandcamp.com/album/one', // already added
        'https://b.bandcamp.com/album/two',
        'https://b.bandcamp.com/album/two', // duplicate within the same paste
      ].join('\n'),
    )

    expect(screen.getAllByRole('listitem')).toHaveLength(2)
  })

  it('dedupes a pasted line that is only cosmetically different from an existing/pasted seed', () => {
    renderForm()
    addViaButton('https://a.bandcamp.com/album/one')
    pasteInto(
      [
        'https://A.BandCamp.com/album/one/', // cosmetic dup of the already-added seed
        'https://b.bandcamp.com/album/two',
        'https://B.BandCamp.com/album/two/', // cosmetic dup within the same paste
      ].join('\n'),
    )

    expect(screen.getAllByRole('listitem')).toHaveLength(2)
    expect(screen.getByText('https://a.bandcamp.com/album/one')).toBeInTheDocument()
    expect(screen.getByText('https://b.bandcamp.com/album/two')).toBeInTheDocument()
  })

  it('leaves a single-line paste to the default paste behavior instead of auto-adding', () => {
    // Only a multi-line paste is special-cased; a single URL still requires
    // Enter/Add, same as typing one in — this proves that branch didn't grow
    // to swallow a plain single-URL paste too.
    renderForm()
    pasteInto('https://a.bandcamp.com/album/one')

    expect(screen.queryByRole('list')).not.toBeInTheDocument()
  })
})

describe('NewScanForm draft-loss warning', () => {
  function dispatchBeforeUnload() {
    const event = new Event('beforeunload', { cancelable: true }) as BeforeUnloadEvent
    const preventDefault = vi.spyOn(event, 'preventDefault')
    window.dispatchEvent(event)
    return { event, preventDefault }
  }

  it('warns before unload once a seed has been added', () => {
    renderForm()
    addViaButton('https://artist.bandcamp.com/album/some-release')

    const { event, preventDefault } = dispatchBeforeUnload()

    expect(preventDefault).toHaveBeenCalled()
    // jsdom's Event.returnValue coerces any assigned value to a boolean
    // (real browsers keep the assigned string) — assert it was set to a
    // falsy value rather than the exact string, so this doesn't pin jsdom's
    // implementation detail instead of the component's actual behavior.
    expect(event.returnValue).toBeFalsy()
  })

  it('does not warn before unload with an empty seed list', () => {
    renderForm()

    const { preventDefault } = dispatchBeforeUnload()

    expect(preventDefault).not.toHaveBeenCalled()
  })

  it('stops warning once the last seed is removed', () => {
    renderForm()
    addViaButton('https://artist.bandcamp.com/album/some-release')
    fireEvent.click(screen.getByRole('button', { name: /remove/i }))

    const { preventDefault } = dispatchBeforeUnload()

    expect(preventDefault).not.toHaveBeenCalled()
  })
})

describe('NewScanForm submission', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('trims leading/trailing whitespace from the name before submitting', async () => {
    const fetchMock = vi.fn(
      async (_input: string | URL | Request, _init?: RequestInit) =>
        new Response(JSON.stringify({ id: 1 }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
    )
    vi.stubGlobal('fetch', fetchMock)

    renderForm()
    fireEvent.change(screen.getByLabelText('Scan name'), { target: { value: '  My Scan  ' } })
    addViaButton('https://artist.bandcamp.com/album/some-release')

    fireEvent.click(screen.getByRole('button', { name: 'Create & queue' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    const [, init] = fetchMock.mock.calls[0]
    const body = JSON.parse(String((init as RequestInit).body))
    expect(body.name).toBe('My Scan')
  })
})

describe('NewScanForm duplicate name warning', () => {
  it('warns when the typed name matches an existing scan, case/whitespace-insensitively', () => {
    renderForm(['Deep house', 'Psy dig'])

    fireEvent.change(screen.getByLabelText('Scan name'), { target: { value: '  deep HOUSE  ' } })

    expect(screen.getByText(/already exists/i)).toBeInTheDocument()
  })

  it('does not warn for a name that does not collide, and never blocks submission', () => {
    renderForm(['Deep house'])

    fireEvent.change(screen.getByLabelText('Scan name'), { target: { value: 'Ambient dig' } })

    expect(screen.queryByText(/already exists/i)).not.toBeInTheDocument()
  })

  it('clears the warning once the name is edited away from the collision', () => {
    renderForm(['Deep house'])
    const input = screen.getByLabelText('Scan name')

    fireEvent.change(input, { target: { value: 'Deep house' } })
    expect(screen.getByText(/already exists/i)).toBeInTheDocument()

    fireEvent.change(input, { target: { value: 'Deep house 2' } })
    expect(screen.queryByText(/already exists/i)).not.toBeInTheDocument()
  })

  it('does not warn on an empty name, and the submit button stays gated on other fields', () => {
    renderForm(['Deep house'])

    expect(screen.queryByText(/already exists/i)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Create & queue' })).toBeDisabled()
  })
})
