/* Opening the palette from outside it.
 *
 * Ctrl/Cmd+K is the palette's own keyboard listener, which is enough for a
 * keyboard — and nothing at all on a phone, where there is no Ctrl and no way
 * to discover the feature either. The header's search button needs to open the
 * same single instance mounted in the app shell, from a component that is not
 * its parent.
 *
 * Same module-scope subscription shape as `lib/toast.ts`, and for the same
 * reason: the caller and the renderer are in different subtrees, so this is a
 * tiny event bus rather than props threaded through the shell. Unlike toast,
 * there is no queue to read — the only state is "someone asked", so plain
 * listeners are enough and no `useSyncExternalStore` is involved.
 */

const listeners = new Set<() => void>()

/** Opens the command palette. Safe to call from any handler; a no-op if the
 *  palette is not mounted (signed out). */
export function openCommandPalette(): void {
  for (const listener of listeners) listener()
}

/** Subscribed by `<CommandPalette>`. Returns the unsubscribe, so it can be
 *  returned straight from an effect. */
export function subscribeToCommandPalette(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}
