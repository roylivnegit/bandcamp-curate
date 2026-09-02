import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { NewScanForm } from './NewScanForm'

function renderForm() {
  render(<NewScanForm onCreated={() => {}} onCancel={() => {}} />)
}

function addViaButton(url: string) {
  fireEvent.change(screen.getByLabelText('Seed releases'), { target: { value: url } })
  fireEvent.click(screen.getByRole('button', { name: 'Add' }))
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

  it('also rejects an invalid URL submitted via Enter', () => {
    renderForm()
    const input = screen.getByLabelText('Seed releases')
    fireEvent.change(input, { target: { value: 'ftp://not-bandcamp/album/x' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.queryByRole('list')).not.toBeInTheDocument()
  })
})
