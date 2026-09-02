import { renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { useDocumentTitle } from './useDocumentTitle'

describe('useDocumentTitle', () => {
  afterEach(() => {
    document.title = ''
  })

  it('sets the document title with the app-name suffix', () => {
    renderHook(() => useDocumentTitle('Scans'))
    expect(document.title).toBe('Scans · crate digger')
  })

  it('updates the title when the argument changes', () => {
    const { rerender } = renderHook(({ title }) => useDocumentTitle(title), {
      initialProps: { title: 'Scans' },
    })
    expect(document.title).toBe('Scans · crate digger')

    rerender({ title: 'My collection' })
    expect(document.title).toBe('My collection · crate digger')
  })

  it('leaves the previous title alone while the argument is null', () => {
    const { rerender } = renderHook(({ title }: { title: string | null }) => useDocumentTitle(title), {
      initialProps: { title: 'Scans' as string | null },
    })
    expect(document.title).toBe('Scans · crate digger')

    rerender({ title: null })
    expect(document.title).toBe('Scans · crate digger')
  })
})
