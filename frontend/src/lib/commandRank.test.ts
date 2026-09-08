import { describe, expect, it } from 'vitest'

import { rankCommands } from './commandRank'

function items(labels: string[]) {
  return labels.map((label) => ({ label }))
}

describe('rankCommands', () => {
  it('ranks a prefix match above a word-boundary match above a buried match', () => {
    const result = rankCommands(
      items(['Vaporwave Deep Cuts', 'My Ambient Scan', 'Scavenger Hunt']),
      'sca',
    )
    expect(result.map((r) => r.label)).toEqual(['Scavenger Hunt', 'My Ambient Scan'])
  })

  it('excludes items that do not match at all', () => {
    const result = rankCommands(items(['Alpha', 'Bravo']), 'zzz')
    expect(result).toEqual([])
  })

  it('keeps original relative order within the same tier', () => {
    const result = rankCommands(items(['Scan B', 'Scan A', 'Scan C']), 'scan')
    expect(result.map((r) => r.label)).toEqual(['Scan B', 'Scan A', 'Scan C'])
  })

  it('is case-insensitive', () => {
    const result = rankCommands(items(['SCAVENGER HUNT']), 'sca')
    expect(result.map((r) => r.label)).toEqual(['SCAVENGER HUNT'])
  })

  it('returns items unchanged for a blank query', () => {
    const list = items(['Bravo', 'Alpha'])
    expect(rankCommands(list, '   ')).toEqual(list)
  })
})
