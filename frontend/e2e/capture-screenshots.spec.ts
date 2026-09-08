import { test } from '@playwright/test'
import { mkdirSync } from 'node:fs'

// Not a QA gate — a visual-grounding step for the agent team (team/tools/ui-screenshot.sh).
// Before a UI/UX cycle designs or builds anything, the Architect/frontend-dev roles Read these
// PNGs so they're working from what the app actually looks like today, not a guess. Runs
// against the same sandbox + seed data as full-flow.spec.ts (E0-4), via the pre-seeded
// `e2e-tester` user so there's always something real on screen (2 recommendation cards).
//
// Kept out of team/tools/e2e.sh's QA run on purpose (see that script and this one's sibling)
// so adding screenshots here never changes what the QA gate exercises or how long it takes.

const OUT_DIR = '../team/artifacts/screenshots'

test('capture current UI screenshots for the team to review', async ({ page }) => {
  mkdirSync(OUT_DIR, { recursive: true })

  // ── Sign-in page (logged out) ───────────────────────────────────────────────────────
  await page.goto('/signin')
  await page.getByLabel('Username').waitFor()
  await page.screenshot({ path: `${OUT_DIR}/signin.png`, fullPage: true })

  // ── Log in as the pre-seeded user with real recommendations ────────────────────────
  await page.getByLabel('Username').fill('e2e-tester')
  await page.getByLabel('Password').fill('e2e-sandbox-pw')
  await page.getByRole('button', { name: 'Sign in' }).click()

  await page.getByRole('heading', { name: 'Your scans' }).waitFor()
  await page.screenshot({ path: `${OUT_DIR}/scans.png`, fullPage: true })

  // ── Feed, with real cards on screen ─────────────────────────────────────────────────
  await page.getByText('My collection').click()
  await page.locator('.countline').waitFor()
  await page.screenshot({ path: `${OUT_DIR}/feed.png`, fullPage: true })
})
