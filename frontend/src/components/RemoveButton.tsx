/** Shared "×" remove control for the three call sites that already share this
 *  exact pattern (a genre/contains filter pill, the artist-filter pill, and a
 *  seed-list row) — `aria-label` is required, not optional, so a call site
 *  that forgets one fails `tsc`, not just an a11y audit. */
export function RemoveButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button type="button" className="rm" aria-label={label} onClick={onClick}>
      ×
    </button>
  )
}
