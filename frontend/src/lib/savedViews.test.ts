import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { SAVED_VIEWS_CAP } from '../config'
import { deleteView, listViews, saveView } from './savedViews'

describe('savedViews storage', () => {
  beforeEach(() => localStorage.clear())

  it('has nothing saved for a scan with no views', () => {
    expect(listViews(1)).toEqual([])
  })

  it('saves a view and lists it back', () => {
    saveView(1, 'House only', '?tag=house')
    const views = listViews(1)
    expect(views).toHaveLength(1)
    expect(views[0]).toMatchObject({ name: 'House only', search: '?tag=house' })
  })

  it('keeps different scans on separate keys', () => {
    saveView(1, 'View A', '?tag=a')
    saveView(2, 'View B', '?tag=b')
    expect(listViews(1).map((v) => v.name)).toEqual(['View A'])
    expect(listViews(2).map((v) => v.name)).toEqual(['View B'])
  })

  it('deletes a view by id, leaving the rest untouched', () => {
    saveView(1, 'Keep me', '?tag=keep')
    const [toDelete] = saveView(1, 'Delete me', '?tag=delete').filter((v) => v.name === 'Delete me')
    const after = deleteView(1, toDelete.id)
    expect(after.map((v) => v.name)).toEqual(['Keep me'])
    expect(listViews(1).map((v) => v.name)).toEqual(['Keep me'])
  })

  it('deleting an id that is not present is a no-op', () => {
    saveView(1, 'Only view', '?tag=x')
    const after = deleteView(1, 'not-a-real-id')
    expect(after.map((v) => v.name)).toEqual(['Only view'])
  })

  it('evicts the oldest view once the cap is exceeded', () => {
    for (let i = 0; i < SAVED_VIEWS_CAP + 3; i++) saveView(1, `View ${i}`, `?tag=${i}`)
    const views = listViews(1)
    expect(views).toHaveLength(SAVED_VIEWS_CAP)
    // The first 3 were evicted; the most recent SAVED_VIEWS_CAP remain, oldest-first.
    expect(views.map((v) => v.name)).toEqual(
      Array.from({ length: SAVED_VIEWS_CAP }, (_, i) => `View ${i + 3}`),
    )
  })

  it('falls back to an empty list on a corrupted stored value', () => {
    localStorage.setItem('crate-digger.savedViews:1', 'not-json')
    expect(listViews(1)).toEqual([])
  })

  it('falls back to an empty list when the stored value is not an array of views', () => {
    localStorage.setItem('crate-digger.savedViews:1', JSON.stringify([{ oops: true }, 42, 'x']))
    expect(listViews(1)).toEqual([])
  })

  describe('when localStorage throws (private mode / storage disabled)', () => {
    afterEach(() => vi.restoreAllMocks())

    it('listViews falls back to an empty list instead of throwing', () => {
      vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
        throw new Error('storage disabled')
      })
      expect(listViews(1)).toEqual([])
    })

    it('saveView is a silent no-op instead of throwing', () => {
      vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
        throw new Error('storage disabled')
      })
      expect(() => saveView(1, 'x', '?y=1')).not.toThrow()
    })
  })
})
