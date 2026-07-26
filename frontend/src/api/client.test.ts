import { describe, expect, it } from 'vitest'

import { filterQuery } from './client'

/** The filter contract is the fiddliest part of the API surface: the backend
 *  reads repeated keys (tag=a&tag=b), and include/exclude are *different* keys
 *  rather than a value. Getting this wrong silently returns the wrong feed. */
describe('filterQuery', () => {
  it('sends repeated keys rather than a joined list', () => {
    const q = filterQuery({ tags: { rock: 'by', jazz: 'by' } })
    expect(q.getAll('tag')).toEqual(['rock', 'jazz'])
    expect(q.toString()).not.toContain('rock%2Cjazz')
  })

  it('routes include vs exclude to their own parameters', () => {
    const q = filterQuery({ tags: { rock: 'by', metal: 'out' } })
    expect(q.getAll('tag')).toEqual(['rock'])
    expect(q.getAll('exclude_tag')).toEqual(['metal'])
  })

  it('keeps substring filters on the *_contains parameters', () => {
    const q = filterQuery({ tagContains: { psy: 'by', live: 'out' } })
    expect(q.getAll('tag_contains')).toEqual(['psy'])
    expect(q.getAll('exclude_tag_contains')).toEqual(['live'])
    expect(q.getAll('tag')).toEqual([])
  })

  it('includes scan and label ids, and omits empty filters entirely', () => {
    const q = filterQuery({ scanId: 7, labelId: 42, itemType: 'album' })
    expect(q.get('scan_id')).toBe('7')
    expect(q.get('label_id')).toBe('42')
    expect(q.get('item_type')).toBe('album')

    const empty = filterQuery({ scanId: null, itemType: '', labelId: null })
    expect(empty.toString()).toBe('')
  })

  it('treats scan 0 as a real id, not as absent', () => {
    // Guards the `!= null` check against a truthiness regression.
    expect(filterQuery({ scanId: 0 }).get('scan_id')).toBe('0')
  })
})
