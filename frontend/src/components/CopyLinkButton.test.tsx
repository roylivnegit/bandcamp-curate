import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { COPY_LINK_FEEDBACK_MS, TOAST_DURATION_MS } from '../config'
import { resetToastsForTests } from '../lib/toast'
import { CopyLinkButton } from './CopyLinkButton'
import { ToastStack } from './ToastStack'

function renderAt(path: string, { withToasts = false } = {}) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <CopyLinkButton />
      {withToasts && <ToastStack />}
    </MemoryRouter>,
  )
}

describe('CopyLinkButton', () => {
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

  it('copies the current URL, including the query string, to the clipboard', async () => {
    renderAt('/scans/7?item_type=album&tag=psy')
    fireEvent.click(screen.getByRole('button', { name: 'Copy link' }))

    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1))
    expect(writeText.mock.calls[0][0]).toBe(
      `${window.location.origin}/scans/7?item_type=album&tag=psy`,
    )
  })

  it('shows a "Copied" confirmation that reverts after the feedback window', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    renderAt('/scans/7')

    fireEvent.click(screen.getByRole('button', { name: 'Copy link' }))
    expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(COPY_LINK_FEEDBACK_MS)
    })
    expect(screen.getByRole('button', { name: 'Copy link' })).toBeInTheDocument()
  })

  it('leaves the button unchanged if the clipboard write is rejected', async () => {
    writeText.mockRejectedValueOnce(new Error('denied'))
    renderAt('/scans/7')

    fireEvent.click(screen.getByRole('button', { name: 'Copy link' }))

    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1))
    expect(screen.getByRole('button', { name: 'Copy link' })).toBeInTheDocument()
  })

  it('raises a toast when the clipboard write is rejected, instead of failing silently', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    writeText.mockRejectedValueOnce(new Error('denied'))
    renderAt('/scans/7', { withToasts: true })

    fireEvent.click(screen.getByRole('button', { name: 'Copy link' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not copy the link/i)

    // Drain the toast's own auto-dismiss timer so it doesn't leak into the
    // next test — the module-scope toast queue outlives this render.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(TOAST_DURATION_MS)
    })
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('raises a status toast on a successful copy, not just the button-text swap', async () => {
    // The "Copied" text swap alone reaches no screen reader — the failure
    // path already gets a proper toast, so the success path should too.
    vi.useFakeTimers({ shouldAdvanceTime: true })
    renderAt('/scans/7', { withToasts: true })

    fireEvent.click(screen.getByRole('button', { name: 'Copy link' }))

    expect(await screen.findByRole('status')).toHaveTextContent(/link copied/i)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(TOAST_DURATION_MS)
    })
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })
})
