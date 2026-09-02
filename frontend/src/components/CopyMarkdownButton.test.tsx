import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { COPY_LINK_FEEDBACK_MS, TOAST_DURATION_MS } from '../config'
import { resetToastsForTests } from '../lib/toast'
import { fakeRec } from '../test/renderApp'
import { CopyMarkdownButton } from './CopyMarkdownButton'
import { ToastStack } from './ToastStack'

function renderWith(rows: Parameters<typeof CopyMarkdownButton>[0]['rows'], { withToasts = false } = {}) {
  render(
    <>
      <CopyMarkdownButton rows={rows} />
      {withToasts && <ToastStack />}
    </>,
  )
}

describe('CopyMarkdownButton', () => {
  let writeText: ReturnType<typeof vi.fn>

  beforeEach(() => {
    writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    })
    resetToastsForTests()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('copies the current rows as a Markdown list to the clipboard', async () => {
    renderWith([
      fakeRec({ band_name: 'A', title: 'One', url: 'https://a.bandcamp.com/album/one' }),
      fakeRec({ band_name: 'B', title: 'Two', url: 'https://b.bandcamp.com/album/two' }),
    ])
    fireEvent.click(screen.getByRole('button', { name: 'Copy as Markdown' }))

    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1))
    expect(writeText.mock.calls[0][0]).toBe(
      '- [A – One](https://a.bandcamp.com/album/one)\n- [B – Two](https://b.bandcamp.com/album/two)',
    )
  })

  it('is disabled when there are no rows to export', () => {
    renderWith([])
    expect(screen.getByRole('button', { name: 'Copy as Markdown' })).toBeDisabled()
  })

  it('shows a "Copied" confirmation that reverts after the feedback window', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    renderWith([fakeRec()])

    fireEvent.click(screen.getByRole('button', { name: 'Copy as Markdown' }))
    expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(COPY_LINK_FEEDBACK_MS)
    })
    expect(screen.getByRole('button', { name: 'Copy as Markdown' })).toBeInTheDocument()
  })

  it('raises a toast and leaves the button unchanged when the clipboard write is rejected', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    writeText.mockRejectedValueOnce(new Error('denied'))
    renderWith([fakeRec()], { withToasts: true })

    fireEvent.click(screen.getByRole('button', { name: 'Copy as Markdown' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not copy the feed/i)
    expect(screen.getByRole('button', { name: 'Copy as Markdown' })).toBeInTheDocument()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(TOAST_DURATION_MS)
    })
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('raises a status toast on a successful copy, not just the button-text swap', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    renderWith([fakeRec()], { withToasts: true })

    fireEvent.click(screen.getByRole('button', { name: 'Copy as Markdown' }))

    expect(await screen.findByRole('status')).toHaveTextContent(/copied as markdown/i)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(TOAST_DURATION_MS)
    })
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })
})
