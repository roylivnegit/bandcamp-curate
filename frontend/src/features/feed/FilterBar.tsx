import { useDeferredValue, useMemo, useState } from 'react'
import type { RefObject } from 'react'

import type { Facet, Recommendation, SortKey } from '../../api/types'
import { CopyLinkButton } from '../../components/CopyLinkButton'
import { CopyMarkdownButton } from '../../components/CopyMarkdownButton'
import { Dropdown } from '../../components/Dropdown'
import { RemoveButton } from '../../components/RemoveButton'
import type { Density } from '../../lib/density'
import { count } from '../../lib/format'
import type { FeedFilters } from './useFeedFilters'

const SORTS: Record<SortKey, string> = {
  score: 'Top score',
  neighbours: 'Most owners',
  affinity: 'Genre match',
}

const TYPES: Array<{ value: '' | 'album' | 'track'; label: string }> = [
  { value: '', label: 'All' },
  { value: 'album', label: 'Albums' },
  { value: 'track', label: 'Tracks' },
]

export function FilterBar({
  filters,
  facetTags,
  rows,
  likedCount,
  blockedCount,
  panel,
  onTogglePanel,
  density,
  onToggleDensity,
  quickQuery,
  onQuickQueryChange,
  quickFilterRef,
}: {
  filters: FeedFilters
  facetTags: Facet[]
  rows: Recommendation[]
  likedCount: number
  blockedCount: number
  panel: 'liked' | 'blocked' | null
  onTogglePanel: (p: 'liked' | 'blocked') => void
  density: Density
  onToggleDensity: () => void
  quickQuery: string
  onQuickQueryChange: (q: string) => void
  quickFilterRef: RefObject<HTMLInputElement | null>
}) {
  return (
    <div className="filterbar">
      <div className="controls">
        <div className="seg" role="group" aria-label="Item type">
          {TYPES.map((t) => (
            <button
              key={t.value || 'all'}
              type="button"
              className={filters.itemType === t.value ? 'on' : ''}
              aria-pressed={filters.itemType === t.value}
              onClick={() => filters.setItemType(t.value)}
            >
              {t.label}
            </button>
          ))}
        </div>

        <input
          ref={quickFilterRef}
          className="input quickfilter"
          aria-label="Filter loaded cards"
          placeholder="Filter loaded cards (/)"
          value={quickQuery}
          onChange={(e) => onQuickQueryChange(e.target.value)}
        />

        <Dropdown label={`Sort · ${SORTS[filters.sort]} ▾`} width={210}>
          {(close) => (
            <div>
              {(Object.keys(SORTS) as SortKey[]).map((k) => (
                <button
                  key={k}
                  type="button"
                  className={`ddrow${filters.sort === k ? ' sel' : ''}`}
                  onClick={() => {
                    filters.setSort(k)
                    close()
                  }}
                >
                  <span className="tick">✓</span>
                  <span className="nm">{SORTS[k]}</span>
                </button>
              ))}
            </div>
          )}
        </Dropdown>

        <GenreDropdown filters={filters} facetTags={facetTags} />
        <ContainsDropdown filters={filters} />

        <div className="spacer" />

        <button
          type="button"
          className={`btn ghost${density === 'compact' ? ' on' : ''}`}
          aria-pressed={density === 'compact'}
          onClick={onToggleDensity}
        >
          {density === 'compact' ? '☰ Compact' : '☰ Comfortable'}
        </button>
        <CopyLinkButton />
        <CopyMarkdownButton rows={rows} />
        <button
          type="button"
          className={`btn ghost${panel === 'liked' ? ' on' : ''}`}
          onClick={() => onTogglePanel('liked')}
        >
          ♥ Liked <span className="num">({likedCount})</span>
        </button>
        <button
          type="button"
          className={`btn ghost${panel === 'blocked' ? ' on' : ''}`}
          onClick={() => onTogglePanel('blocked')}
        >
          Blocked <span className="num">({blockedCount})</span>
        </button>
      </div>

      <ActivePills filters={filters} />
    </div>
  )
}

function GenreDropdown({ filters, facetTags }: { filters: FeedFilters; facetTags: Facet[] }) {
  const [query, setQuery] = useState('')
  const [pending, setPending] = useState<Set<string>>(new Set())

  const selectedCount = Object.keys(filters.tags).length

  /* A well-crawled account has thousands of genre tags. Two things keep typing
   * here smooth: the search key is lowercased once per facet list rather than
   * once per tag per keystroke, and the filtering reads a deferred query, so the
   * input paints immediately and the list catches up. */
  const searchable = useMemo(
    () => facetTags.map((t) => ({ tag: t, key: t.label.toLowerCase() })),
    [facetTags],
  )
  const deferredQuery = useDeferredValue(query)
  const rows = useMemo(() => {
    const q = deferredQuery.trim().toLowerCase()
    if (!q) return facetTags
    const out: Facet[] = []
    for (const { tag, key } of searchable) if (key.includes(q)) out.push(tag)
    return out
  }, [searchable, facetTags, deferredQuery])

  return (
    <Dropdown
      label={selectedCount ? `Genres (${selectedCount}) ▾` : '＋ Genre filter'}
      active={selectedCount > 0}
      onOpen={() => {
        setPending(new Set(Object.keys(filters.tags)))
        setQuery('')
      }}
    >
      {(close) => (
        <div>
          <input
            className="ddsearch input"
            placeholder="Search genres…"
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="ddlist">
            {facetTags.length === 0 ? (
              <p className="ddempty">
                No genre tags yet — they arrive as album pages get crawled.
              </p>
            ) : rows.length === 0 ? (
              // deferredQuery, not query: the message has to describe the list
              // that's actually on screen.
              <p className="ddempty">No genres match “{deferredQuery}”.</p>
            ) : (
              rows.map((t) => {
                const sel = pending.has(t.value)
                return (
                  <button
                    key={t.value}
                    type="button"
                    className={`ddrow${sel ? ' sel' : ''}`}
                    onClick={() => {
                      const next = new Set(pending)
                      if (sel) next.delete(t.value)
                      else next.add(t.value)
                      setPending(next)
                    }}
                  >
                    <span className="box">✓</span>
                    <span className="nm">{t.label}</span>
                    <span className="cnt">{count(t.count)}</span>
                  </button>
                )
              })
            )}
          </div>
          <div className="ddfoot">
            <button type="button" className="btn ghost" onClick={() => setPending(new Set())}>
              Clear
            </button>
            <button
              type="button"
              className="btn"
              onClick={() => {
                filters.commitTags(pending)
                close()
              }}
            >
              {pending.size ? `Apply (${pending.size})` : 'Apply'}
            </button>
          </div>
        </div>
      )}
    </Dropdown>
  )
}

function ContainsDropdown({ filters }: { filters: FeedFilters }) {
  const [text, setText] = useState('')
  const n = Object.keys(filters.tagContains).length

  return (
    <Dropdown
      label={n ? `Contains (${n}) ▾` : '＋ Tag contains'}
      active={n > 0}
      width={280}
      onOpen={() => setText('')}
    >
      {() => (
        <div>
          <input
            className="ddsearch input"
            placeholder="e.g. psy — press Enter to add"
            autoFocus
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                filters.addContains(text)
                setText('')
              }
            }}
          />
          <p className="ddempty">
            Matches any genre tag containing this text — “psy” catches psybient and psytrance.
            Toggle the pill below to include or exclude.
          </p>
        </div>
      )}
    </Dropdown>
  )
}

function ActivePills({ filters }: { filters: FeedFilters }) {
  const tagCount = Object.keys(filters.tags).length
  const containsCount = Object.keys(filters.tagContains).length
  // Facets, not individual pills — three genre tags plus an artist is still
  // two things to clear, not four, so "Clear all" shows up exactly when
  // there's more than one group a reader would otherwise remove one pill at
  // a time.
  const facetCount = (tagCount > 0 ? 1 : 0) + (containsCount > 0 ? 1 : 0) + (filters.label ? 1 : 0)

  if (facetCount === 0) return null

  return (
    <div className="active">
      {Object.entries(filters.tags).map(([tag, mode]) => (
        <Pill
          key={`t-${tag}`}
          mode={mode}
          body={tag}
          onToggle={() => filters.toggleTagMode(tag)}
          onRemove={() => filters.removeTag(tag)}
        />
      ))}
      {Object.entries(filters.tagContains).map(([text, mode]) => (
        <Pill
          key={`c-${text}`}
          mode={mode}
          body={`~${text}`}
          onToggle={() => filters.toggleContainsMode(text)}
          onRemove={() => filters.removeContains(text)}
        />
      ))}
      {filters.label && (
        <span className="fpill">
          <span className="tog static">
            artist: <b>{filters.label.name}</b>
          </span>
          <RemoveButton label="Clear artist filter" onClick={() => filters.setLabel(null)} />
        </span>
      )}
      {facetCount >= 2 && (
        <button type="button" className="clearall" onClick={filters.reset}>
          Clear all filters
        </button>
      )}
    </div>
  )
}

function Pill({
  mode,
  body,
  onToggle,
  onRemove,
}: {
  mode: 'by' | 'out'
  body: string
  onToggle: () => void
  onRemove: () => void
}) {
  const out = mode === 'out'
  return (
    <span className={`fpill${out ? ' out' : ''}`}>
      <button
        type="button"
        className="tog"
        title="Switch between include and exclude"
        onClick={onToggle}
      >
        {out ? '⊘ exclude' : '✓ include'}: <b>{body}</b>
      </button>
      <RemoveButton label={`Remove ${body}`} onClick={onRemove} />
    </span>
  )
}
