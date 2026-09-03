import '@testing-library/jest-dom/vitest'

/* localStorage shim.
 *
 * Under Node 26 + jsdom 29 the test window has no `localStorage`: Node ships its
 * own experimental global (inert unless started with --localstorage-file) and
 * jsdom doesn't install one, so both the bare identifier and `window.localStorage`
 * come back undefined. The app legitimately depends on it for the bearer token,
 * so give the tests a real (in-memory) implementation rather than weakening the
 * app code to tolerate an absence that never happens in a browser. */
if (!globalThis.localStorage) {
  const store = new Map<string, string>()
  const shim: Storage = {
    get length() {
      return store.size
    },
    key: (i) => [...store.keys()][i] ?? null,
    getItem: (k) => store.get(k) ?? null,
    setItem: (k, v) => void store.set(k, String(v)),
    removeItem: (k) => void store.delete(k),
    clear: () => store.clear(),
  }
  const define = (target: object) =>
    Object.defineProperty(target, 'localStorage', {
      value: shim,
      configurable: true,
      writable: true,
    })
  define(globalThis)
  if (typeof window !== 'undefined') define(window)
}

/* IntersectionObserver shim — jsdom doesn't implement it at all (the bare
 * identifier is undefined), but the auto-load-more feed uses one for real.
 * A no-op observer is enough for most tests (nothing calls its callback, so
 * nothing auto-loads, matching every fixture's default `done: true`); tests
 * that need to simulate a sentinel actually scrolling into view do it
 * through `triggerIntersections` in `./intersectionObserver`, which reads
 * `instances` below. */
class MockIntersectionObserver implements IntersectionObserver {
  static instances: MockIntersectionObserver[] = []
  readonly root = null
  readonly rootMargin = ''
  readonly scrollMargin = ''
  readonly thresholds: ReadonlyArray<number> = []
  private readonly callback: IntersectionObserverCallback
  readonly observed = new Set<Element>()

  constructor(callback: IntersectionObserverCallback) {
    this.callback = callback
    MockIntersectionObserver.instances.push(this)
  }

  observe(el: Element) {
    this.observed.add(el)
  }

  unobserve(el: Element) {
    this.observed.delete(el)
  }

  disconnect() {
    this.observed.clear()
    MockIntersectionObserver.instances = MockIntersectionObserver.instances.filter((i) => i !== this)
  }

  takeRecords(): IntersectionObserverEntry[] {
    return []
  }

  /** Test-only: run this instance's callback as if every element it's
   *  currently observing just became (or stopped being) visible. */
  fire(isIntersecting: boolean) {
    const entries = [...this.observed].map(
      (target) => ({ isIntersecting, target }) as IntersectionObserverEntry,
    )
    if (entries.length) this.callback(entries, this)
  }
}

Object.defineProperty(globalThis, 'IntersectionObserver', {
  value: MockIntersectionObserver,
  configurable: true,
  writable: true,
})
if (typeof window !== 'undefined') {
  Object.defineProperty(window, 'IntersectionObserver', {
    value: MockIntersectionObserver,
    configurable: true,
    writable: true,
  })
}

export { MockIntersectionObserver }
