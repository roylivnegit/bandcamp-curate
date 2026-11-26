import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { configDefaults } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // The backend's CORS allow_origins defaults to this exact origin, so keep the
    // port fixed rather than letting Vite silently pick the next free one.
    strictPort: true,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    /* Tests talk to `mockFetch`, never to a server — but `api/client.ts` builds
     * every URL from `VITE_API_BASE_URL`, which Vite loads from a developer's
     * own gitignored `.env.local` here too. With a real API running at that
     * address, any request the mock doesn't match escapes to it, 401s on the
     * fake token, and signs the app out mid-test — a failure that looks like a
     * bug in whatever test happened to be slowest. Pinning it empty keeps the
     * suite the same for everyone. */
    env: { VITE_API_BASE_URL: '' },
    setupFiles: ['./src/test/setup.ts'],
    // Styling is mocked out everywhere (jsdom doesn't render it, and applying
    // real CSS to every test is pure overhead) — except `?raw` imports, which
    // ask for the literal file text on purpose. contrast.test.ts reads
    // tokens.css this way so it verifies the actual shipped token values,
    // not a hand-copied duplicate that could drift from them unnoticed.
    css: { include: [/\.css\?raw$/] },
    // e2e/*.spec.ts files import '@playwright/test', which is never a real
    // devDependency here (it's installed ad hoc, on demand, for a one-off
    // Playwright run, then removed) — vitest's default include glob would
    // otherwise try to run them as unit tests and fail to resolve that
    // import. They run only under `npx playwright test`, never `npm test`.
    exclude: [...configDefaults.exclude, 'e2e/**'],
  },
})
