/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

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
  },
})
