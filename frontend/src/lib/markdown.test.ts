import { describe, expect, it } from 'vitest'

import { fakeRec } from '../test/renderApp'
import { recsToMarkdown } from './markdown'

describe('recsToMarkdown', () => {
  it('renders a band + title row as a Markdown link', () => {
    const md = recsToMarkdown([
      fakeRec({
        band_name: 'Minds of Infinity',
        title: 'Eyes of Infinity',
        url: 'https://mindsofinfinity.bandcamp.com/album/eyes-of-infinity',
      }),
    ])
    expect(md).toBe(
      '- [Minds of Infinity – Eyes of Infinity](https://mindsofinfinity.bandcamp.com/album/eyes-of-infinity)',
    )
  })

  it('joins multiple rows with newlines, one bullet per row', () => {
    const md = recsToMarkdown([
      fakeRec({ band_name: 'A', title: 'One', url: 'https://a.bandcamp.com/album/one' }),
      fakeRec({ band_name: 'B', title: 'Two', url: 'https://b.bandcamp.com/album/two' }),
    ])
    expect(md.split('\n')).toEqual([
      '- [A – One](https://a.bandcamp.com/album/one)',
      '- [B – Two](https://b.bandcamp.com/album/two)',
    ])
  })

  it('omits the link entirely for a row with no url, rather than fabricating one', () => {
    const md = recsToMarkdown([fakeRec({ band_name: 'A', title: 'One', url: null })])
    expect(md).toBe('- A – One')
  })

  it('falls back to whichever of title/band_name is present', () => {
    expect(recsToMarkdown([fakeRec({ band_name: null, title: 'Solo Title', url: null })])).toBe(
      '- Solo Title',
    )
    expect(recsToMarkdown([fakeRec({ band_name: 'Solo Band', title: null, url: null })])).toBe(
      '- Solo Band',
    )
    expect(recsToMarkdown([fakeRec({ band_name: null, title: null, url: null })])).toBe(
      '- Untitled',
    )
  })

  it('escapes [ and ] in the label so the row still parses as a valid link', () => {
    const md = recsToMarkdown([
      fakeRec({
        band_name: '[Unknown]',
        title: 'Track [Remix]',
        url: 'https://x.bandcamp.com/track/t',
      }),
    ])
    expect(md).toBe('- [\\[Unknown\\] – Track \\[Remix\\]](https://x.bandcamp.com/track/t)')
  })

  it('returns an empty string for an empty list', () => {
    expect(recsToMarkdown([])).toBe('')
  })
})
