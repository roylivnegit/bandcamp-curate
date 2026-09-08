import { describe, expect, it } from 'vitest'

import { matchesPanelQuery } from './panelFilter'

describe('matchesPanelQuery', () => {
  it('matches a substring in any field, case-insensitively', () => {
    expect(matchesPanelQuery(['Eyes of Infinity', 'Minds of Infinity'], 'infinity')).toBe(true)
    expect(matchesPanelQuery(['Eyes of Infinity', 'Minds of Infinity'], 'MINDS')).toBe(true)
  })

  it('is false when no field matches', () => {
    expect(matchesPanelQuery(['Eyes of Infinity', 'Minds of Infinity'], 'psybient')).toBe(false)
  })

  it('an empty or whitespace-only query matches everything', () => {
    expect(matchesPanelQuery(['Eyes of Infinity'], '')).toBe(true)
    expect(matchesPanelQuery(['Eyes of Infinity'], '   ')).toBe(true)
    expect(matchesPanelQuery([], '')).toBe(true)
  })

  it('tolerates null/undefined fields without matching or throwing', () => {
    expect(matchesPanelQuery([null, undefined, 'Minds of Infinity'], 'minds')).toBe(true)
    expect(() => matchesPanelQuery([null, undefined], 'minds')).not.toThrow()
    expect(matchesPanelQuery([null, undefined], 'minds')).toBe(false)
  })
})
