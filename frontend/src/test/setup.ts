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
