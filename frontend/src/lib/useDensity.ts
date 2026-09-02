import { useCallback, useState } from 'react'

import { type Density, getDensity, setDensity } from './density'

/** `useState(() => getDensity())` per rule 12 in frontend/CLAUDE.md — reading
 *  localStorage is real work, so the lazy-init function form earns its keep
 *  here (unlike a cheap literal default). */
export function useDensity(): [Density, () => void] {
  const [density, setDensityState] = useState<Density>(() => getDensity())

  const toggleDensity = useCallback(() => {
    setDensityState((prev) => {
      const next: Density = prev === 'compact' ? 'comfortable' : 'compact'
      setDensity(next)
      return next
    })
  }, [])

  return [density, toggleDensity]
}
