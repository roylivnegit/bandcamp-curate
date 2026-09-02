import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { SCROLL_TOP_THRESHOLD_PX } from '../config'
import { ScrollTopButton } from './ScrollTopButton'

function setScrollY(y: number) {
  Object.defineProperty(window, 'scrollY', { value: y, configurable: true, writable: true })
}

describe('ScrollTopButton', () => {
  afterEach(() => {
    setScrollY(0)
  })

  it('is absent below the scroll threshold', () => {
    setScrollY(SCROLL_TOP_THRESHOLD_PX - 1)
    render(<ScrollTopButton onClick={vi.fn()} />)
    fireEvent.scroll(window)

    expect(screen.queryByRole('button', { name: 'Back to top' })).not.toBeInTheDocument()
  })

  it('appears once scrolled past the threshold', () => {
    render(<ScrollTopButton onClick={vi.fn()} />)
    setScrollY(SCROLL_TOP_THRESHOLD_PX + 1)
    fireEvent.scroll(window)

    expect(screen.getByRole('button', { name: 'Back to top' })).toBeInTheDocument()
  })

  it('disappears again once scrolled back above the threshold', () => {
    render(<ScrollTopButton onClick={vi.fn()} />)
    setScrollY(SCROLL_TOP_THRESHOLD_PX + 1)
    fireEvent.scroll(window)
    expect(screen.getByRole('button', { name: 'Back to top' })).toBeInTheDocument()

    setScrollY(0)
    fireEvent.scroll(window)
    expect(screen.queryByRole('button', { name: 'Back to top' })).not.toBeInTheDocument()
  })

  it('calls onClick when clicked', () => {
    const onClick = vi.fn()
    setScrollY(SCROLL_TOP_THRESHOLD_PX + 1)
    render(<ScrollTopButton onClick={onClick} />)
    fireEvent.scroll(window)

    fireEvent.click(screen.getByRole('button', { name: 'Back to top' }))
    expect(onClick).toHaveBeenCalledTimes(1)
  })
})
