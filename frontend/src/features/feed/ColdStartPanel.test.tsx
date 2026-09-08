import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { ColdStart } from '../../api/types'
import { ColdStartPanel } from './ColdStartPanel'

const coldStart: ColdStart = {
  neighbour_count: 12,
  candidates: 340,
  excluded_owned: 210,
  excluded_wishlisted: 40,
  excluded_followed: 55,
  excluded_blacklisted: 3,
  excluded_liked: 7,
}

describe('ColdStartPanel', () => {
  it('renders the neighbour/candidate counts and every exclusion reason', () => {
    render(<ColdStartPanel coldStart={coldStart} />)

    expect(screen.getByText('12')).toBeInTheDocument()
    expect(screen.getByText(/taste-neighbour/)).toBeInTheDocument()
    expect(screen.getByText('340')).toBeInTheDocument()
    expect(screen.getByText(/candidates/)).toBeInTheDocument()
    expect(screen.getByText('210')).toBeInTheDocument()
    expect(screen.getByText(/owned/)).toBeInTheDocument()
    expect(screen.getByText('40')).toBeInTheDocument()
    expect(screen.getByText(/wishlisted/)).toBeInTheDocument()
    expect(screen.getByText('55')).toBeInTheDocument()
    expect(screen.getByText(/followed/)).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
    expect(screen.getByText(/blocked/)).toBeInTheDocument()
    expect(screen.getByText('7')).toBeInTheDocument()
    expect(screen.getByText(/liked/)).toBeInTheDocument()
  })

  it('explains a total absence of neighbours differently from an exclusion story', () => {
    render(<ColdStartPanel coldStart={{ ...coldStart, neighbour_count: 0, candidates: 0 }} />)

    expect(screen.getByText(/no taste-neighbours found yet/i)).toBeInTheDocument()
    expect(screen.queryByText(/candidates/)).not.toBeInTheDocument()
  })

  it('renders nothing when there is no cold-start data yet', () => {
    const { container } = render(<ColdStartPanel coldStart={null} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders nothing when cold-start data is undefined', () => {
    const { container } = render(<ColdStartPanel coldStart={undefined} />)
    expect(container).toBeEmptyDOMElement()
  })
})

describe('ColdStartPanel crawl-budget line', () => {
  it('shows requests used out of the budget when both are provided', () => {
    render(<ColdStartPanel coldStart={coldStart} requestsUsed={743} requestBudget={1000} />)

    expect(screen.getByText('743')).toBeInTheDocument()
    expect(screen.getByText('1,000')).toBeInTheDocument()
    expect(screen.getByText(/crawl requests used/)).toBeInTheDocument()
  })

  it('also shows it on the no-neighbours-yet branch', () => {
    render(
      <ColdStartPanel
        coldStart={{ ...coldStart, neighbour_count: 0, candidates: 0 }}
        requestsUsed={12}
        requestBudget={1000}
      />,
    )

    expect(screen.getByText(/no taste-neighbours found yet/i)).toBeInTheDocument()
    expect(screen.getByText(/crawl requests used/)).toBeInTheDocument()
  })

  it('renders no budget line when the values are absent', () => {
    render(<ColdStartPanel coldStart={coldStart} />)
    expect(screen.queryByText(/crawl requests used/)).not.toBeInTheDocument()
  })

  it('renders no budget line when the budget is zero', () => {
    render(<ColdStartPanel coldStart={coldStart} requestsUsed={0} requestBudget={0} />)
    expect(screen.queryByText(/crawl requests used/)).not.toBeInTheDocument()
  })
})
