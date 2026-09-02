/** WCAG 2.x relative luminance + contrast ratio, for verifying design tokens
 *  rather than eyeballing them. https://www.w3.org/TR/WCAG21/#dfn-relative-luminance */

function srgbToLinear(channel: number): number {
  const c = channel / 255
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
}

function relativeLuminance(hex: string): number {
  const clean = hex.replace('#', '')
  const r = parseInt(clean.slice(0, 2), 16)
  const g = parseInt(clean.slice(2, 4), 16)
  const b = parseInt(clean.slice(4, 6), 16)
  return 0.2126 * srgbToLinear(r) + 0.7152 * srgbToLinear(g) + 0.0722 * srgbToLinear(b)
}

/** Ratio of two `#rrggbb` colors, order-independent, 1 (identical) to 21
 *  (black on white). WCAG AA requires 4.5 for normal text, 3 for large text
 *  (18pt+, or 14pt+ bold) and non-text UI components. */
export function contrastRatio(hexA: string, hexB: string): number {
  const a = relativeLuminance(hexA)
  const b = relativeLuminance(hexB)
  const lighter = Math.max(a, b)
  const darker = Math.min(a, b)
  return (lighter + 0.05) / (darker + 0.05)
}
