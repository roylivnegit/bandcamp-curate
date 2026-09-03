# Tried and failed

Read this at every standup. Do not re-propose something listed here without new evidence —
and when you do, say what changed.

The retro appends to this at the end of each cycle. Nothing is ever deleted. If a finding
stops being true, add a new entry saying so and why, rather than editing the old one.

<!-- cycles append below this line -->

## 2026-09-03 — hourly routine, Option C round 2 came up empty

After ~55 shipped UI/UX items, a fresh Product/Architect+QA round (working from a condensed
summary, not the code) proposed two ideas that Architect+QA rejected outright once checked
against the actual repo — both were already fully built:

- **"Keyboard shortcuts help overlay."** Already exists: `components/ShortcutsHelp.tsx`, a
  `?`-triggered `role="dialog"` modal with a focus trap, driven by its own `SHORTCUTS`
  array — which already *is* the "registry" the proposal asked to extract.
- **"Respect `prefers-reduced-motion`."** Already exists: a global
  `@media (prefers-reduced-motion: reduce)` block in `styles/base.css` zeroing
  animation/transition duration app-wide, documented in `frontend/CLAUDE.md` as
  already-satisfied and relied on by several already-shipped features (skeleton shimmer,
  `ShortcutsHelp`'s own fade-in).

Do not re-propose either without new evidence — e.g. a genuinely new caller that needs a
`usePrefersReducedMotion()` JS hook (none exists today, and none of the current UI does
JS-driven motion that would need one), or a real reuse case for a standalone shortcuts registry
module beyond `ShortcutsHelp`'s own array. The backlog's UI/UX section is now thin enough that
Product proposals from a summary (rather than a fresh read of `frontend/CLAUDE.md`'s "Known
conflicts and deferred items" + the actual component tree) are increasingly likely to describe
something that's already there — a future round should have Product skim the real file list
before proposing, not just a prose summary of past cycles.
