import { useSyncExternalStore } from 'react'

import { TOAST_DURATION_MS } from '../config'

export interface Toast {
  id: number
  message: string
  /** Drives both the live-region urgency (`role`) and the color the stack
   *  renders it in — `'alert'` for a failure worth interrupting for,
   *  `'status'` for routine confirmation. */
  variant: 'status' | 'alert'
}

/* Module-scope, not component state: a toast can be raised from any event
 * handler, including ones with no toast-owning component anywhere in their
 * own tree (e.g. CopyLinkButton's clipboard-rejection catch). `<ToastStack>`
 * (mounted once in the app shell) is just the one subscriber that renders
 * this queue; `useSyncExternalStore` is what lets React tear-safely read a
 * store that lives outside its own state. */
let toasts: Toast[] = []
let nextId = 0
const listeners = new Set<() => void>()

function emitChange() {
  for (const listener of listeners) listener()
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function getSnapshot() {
  return toasts
}

/** Queues a toast; it removes itself after `durationMs`. Call this directly
 *  from anywhere — it needs no hook and no component context. */
export function showToast(message: string, variant: Toast['variant'] = 'status', durationMs = TOAST_DURATION_MS) {
  const id = nextId++
  toasts = [...toasts, { id, message, variant }]
  emitChange()
  window.setTimeout(() => dismissToast(id), durationMs)
}

/** Removes one toast immediately (the auto-dismiss timer above, or a reader
 *  clicking its dismiss button). A no-op if it's already gone — the timer
 *  and a manual dismiss can race. */
export function dismissToast(id: number) {
  const next = toasts.filter((t) => t.id !== id)
  if (next.length === toasts.length) return
  toasts = next
  emitChange()
}

/** The live queue, for `<ToastStack>` to render. */
export function useToasts(): Toast[] {
  return useSyncExternalStore(subscribe, getSnapshot)
}

/** Test-only. The queue is module-scope by design (see the note above), which
 *  means it otherwise survives across tests in the same file — including a
 *  toast raised by a test that never rendered `<ToastStack>` to observe it.
 *  Call from `beforeEach` wherever a test exercises `showToast`. Any
 *  already-scheduled dismiss timer from before the reset still fires
 *  harmlessly later: `dismissToast` no-ops once its id is gone. */
export function resetToastsForTests() {
  toasts = []
  emitChange()
}
