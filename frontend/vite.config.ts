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
