import { MockIntersectionObserver } from './setup'

/** Simulates every currently-observed sentinel becoming visible (or not) —
 *  the mock's `observe`/`disconnect` calls are real, only the browser's own
 *  "did it actually scroll into view" computation is unavailable in jsdom. */
export function triggerIntersections(isIntersecting = true): void {
  for (const instance of MockIntersectionObserver.instances) {
    instance.fire(isIntersecting)
  }
}
