import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { EmptyState } from './EmptyState'

describe('EmptyState', () => {
  it('renders the filtered-empty variant when a filter is active', () => {
    const onClearFilters = vi.fn()
    render(<EmptyState anyActive coldStart={null} onClearFilters={onClearFilters} />)

    expect(screen.getByTestId('empty-filtered')).toBeInTheDocument()
    expect(screen.queryByTestId('empty-cold-start')).not.toBeInTheDocument()
    expect(screen.getByText('Nothing matches these filters — try clearing one.')).toBeInTheDocument()

    screen.getByRole('button', { name: 'Clear filters' }).click()
    expect(onClearFilters).toHaveBeenCalledOnce()
  })

  it('renders the cold-start variant when no filter is active, with no diagnostics yet', () => {
    render(<EmptyState anyActive={false} coldStart={null} onClearFilters={vi.fn()} />)

    expect(screen.getByTestId('empty-cold-start')).toBeInTheDocument()
    expect(screen.queryByTestId('empty-filtered')).not.toBeInTheDocument()
    expect(screen.getByText('No recommendations in this scan yet.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Clear filters' })).not.toBeInTheDocument()
  })

  it('renders the cold-start variant with ColdStartPanel diagnostics once loaded', () => {
    render(
      <EmptyState
        anyActive={false}
        coldStart={{
          neighbour_count: 5,
          candidates: 40,
          excluded_owned: 10,
          excluded_wishlisted: 5,
          excluded_followed: 20,
          excluded_blacklisted: 5,
        }}
        onClearFilters={vi.fn()}
      />,
    )

    expect(screen.getByTestId('empty-cold-start')).toBeInTheDocument()
    expect(screen.getByText('40')).toBeInTheDocument()
    expect(screen.getByText(/candidates/)).toBeInTheDocument()
  })

  it('passes requestsUsed/requestBudget through to ColdStartPanel', () => {
    render(
      <EmptyState
        anyActive={false}
        coldStart={{
          neighbour_count: 5,
          candidates: 40,
          excluded_owned: 10,
          excluded_wishlisted: 5,
          excluded_followed: 20,
          excluded_blacklisted: 5,
        }}
        requestsUsed={99}
        requestBudget={1000}
        onClearFilters={vi.fn()}
      />,
    )

    expect(screen.getByText('99')).toBeInTheDocument()
    expect(screen.getByText(/crawl requests used/)).toBeInTheDocument()
  })
})
