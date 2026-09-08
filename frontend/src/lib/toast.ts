import { useSyncExternalStore } from 'react'

import { TOAST_DURATION_MS, TOAST_STACK_CAP } from '../config'

export interface Toast {
  id: number
  message: string
  /** Drives both the live-region urgency (`role`) and the color the stack
   *  renders it in — `'alert'` for a failure worth interrupting for,
   *  `'status'` for routine confirmation. */
  variant: 'status' | 'alert'
  /** An optional inline action button (e.g. "Retry" on a failed mutation).
   *  `<ToastStack>` dismisses the toast itself once `onClick` runs. */
  action?: { label: string; onClick: () => void }
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

/** One entry per toast with a live or paused dismiss timer. `pauseCount` is a
 *  reference count, not a boolean — a toast can be both hovered and
 *  keyboard-focused at once (ToastStack pauses on each independently), and
 *  the timer must only actually resume once every reason to pause has
 *  cleared. `remaining`/`startedAt` are only meaningful while paused
 *  (`timerId === null`): the ground truth while running is the `setTimeout`
 *  itself. */
interface ToastTimer {
  timerId: number | null
  remaining: number
  startedAt: number
  pauseCount: number
}
const timers = new Map<number, ToastTimer>()

function startTimer(id: number, ms: number) {
  const timerId = window.setTimeout(() => dismissToast(id), ms)
  timers.set(id, { timerId, remaining: ms, startedAt: Date.now(), pauseCount: 0 })
}

function clearTimer(id: number) {
  const state = timers.get(id)
  if (state?.timerId !== null && state?.timerId !== undefined) window.clearTimeout(state.timerId)
  timers.delete(id)
}

/** Freezes a toast's auto-dismiss countdown — e.g. the reader's pointer or
 *  keyboard focus is on it, so it shouldn't vanish out from under them mid
 *  reach for an action like Undo. Safe to call more than once for
 *  independent reasons (hover AND focus); `resumeToast` only actually
 *  restarts the timer once every `pauseToast` call has a matching resume. */
export function pauseToast(id: number) {
  const state = timers.get(id)
  if (!state) return
  const pauseCount = state.pauseCount + 1
  if (state.timerId === null) {
    timers.set(id, { ...state, pauseCount })
    return
  }
  window.clearTimeout(state.timerId)
  const remaining = Math.max(0, state.remaining - (Date.now() - state.startedAt))
  timers.set(id, { timerId: null, remaining, startedAt: state.startedAt, pauseCount })
}

/** Resumes a toast paused via `pauseToast`, for the remaining time it had
 *  left. No-ops until every `pauseToast` call has a matching `resumeToast`. */
export function resumeToast(id: number) {
  const state = timers.get(id)
  if (!state || state.timerId !== null) return
  const pauseCount = Math.max(0, state.pauseCount - 1)
  if (pauseCount > 0) {
    timers.set(id, { ...state, pauseCount })
    return
  }
  startTimer(id, state.remaining)
}

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
export function showToast(
  message: string,
  variant: Toast['variant'] = 'status',
  durationMs = TOAST_DURATION_MS,
  action?: Toast['action'],
) {
  const id = nextId++
  toasts = evictOverflow([...toasts, { id, message, variant, action }])
  emitChange()
  startTimer(id, durationMs)
}

/** Drops the oldest toast with no pending `action` until the queue is back
 *  at the cap — an action carries something the reader would lose silently
 *  (e.g. an Undo), so it's never the one evicted. If every current toast has
 *  one, the queue is left over cap rather than dropping any of them; that's
 *  an edge case rare enough not to need its own policy. */
function evictOverflow(list: Toast[]): Toast[] {
  let next = list
  while (next.length > TOAST_STACK_CAP) {
    const idx = next.findIndex((t) => !t.action)
    if (idx === -1) break
    clearTimer(next[idx].id)
    next = [...next.slice(0, idx), ...next.slice(idx + 1)]
  }
  return next
}

/** Removes one toast immediately (the auto-dismiss timer above, or a reader
 *  clicking its dismiss button). A no-op if it's already gone — the timer
 *  and a manual dismiss can race. */
export function dismissToast(id: number) {
  const next = toasts.filter((t) => t.id !== id)
  if (next.length === toasts.length) return
  toasts = next
  clearTimer(id)
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
  for (const id of Array.from(timers.keys())) clearTimer(id)
  emitChange()
}
