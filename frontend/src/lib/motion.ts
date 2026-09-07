// Covers imperative motion (e.g. window.scrollTo) that the global CSS
// `prefers-reduced-motion` block in base.css can't reach — that block only
// zeroes CSS transition/animation durations, not a native smooth-scroll.
export function prefersReducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}
