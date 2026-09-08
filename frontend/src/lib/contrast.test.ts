import { describe, expect, it } from 'vitest'

import tokensCss from '../styles/tokens.css?raw'
import { contrastRatio } from './contrast'

/** Reads a token's value straight out of tokens.css, rather than duplicating
 *  the hex here — so this test fails the moment the token drifts back out of
 *  compliance, instead of only catching a color chosen by a fresh calculation. */
function token(name: string): string {
  const match = tokensCss.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`))
  if (!match) throw new Error(`token --${name} not found in tokens.css`)
  return match[1]
}

describe('contrastRatio', () => {
  it('matches known WCAG reference values', () => {
    expect(contrastRatio('#000000', '#ffffff')).toBeCloseTo(21, 0)
    expect(contrastRatio('#777777', '#777777')).toBeCloseTo(1, 5)
    // Order doesn't matter.
    expect(contrastRatio('#000000', '#ffffff')).toBeCloseTo(contrastRatio('#ffffff', '#000000'), 5)
  })
})

describe('--faint token contrast', () => {
  // `--faint` carries real text, not just decoration: `.via`'s seed-tag
  // provenance, `.field-hint`, `.eyebrow`/`.label`, and input placeholders.
  // All of those sizes (9-13px) are far under WCAG's "large text" threshold
  // (18.66px, or 14px bold), so the applicable minimum is 4.5:1 — not the
  // 3:1 that would apply to large text or non-text UI components like icon
  // glyphs.
  const faint = token('faint')

  it('clears WCAG AA (4.5:1) against every surface it sits on as text', () => {
    // --surface2 hosts `.input::placeholder`, and is the lightest background
    // `--faint` text renders against — the binding case.
    expect(contrastRatio(faint, token('surface-2'))).toBeGreaterThanOrEqual(4.5)
    // --surface hosts `.via`, `.field-hint`, and `.scan-meta .sep`.
    expect(contrastRatio(faint, token('surface'))).toBeGreaterThanOrEqual(4.5)
    // --bg hosts `.eyebrow` / `.label` page-level headings and form labels.
    expect(contrastRatio(faint, token('bg'))).toBeGreaterThanOrEqual(4.5)
  })

  it('stays visually subordinate to --muted', () => {
    // The whole point of a separate "faint" tier is that it reads as lower
    // emphasis than "muted" — fixing the contrast failure must not invert
    // that hierarchy.
    const muted = token('muted')
    const bg = token('surface')
    expect(contrastRatio(faint, bg)).toBeLessThan(contrastRatio(muted, bg))
  })
})
