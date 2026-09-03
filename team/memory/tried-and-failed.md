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

## 2026-09-03 — hourly routine, Option C round 3 also came up empty

Same failure mode as round 2 above, worse this time: two of the three proposals didn't just
duplicate existing code, they described features/controls that don't exist in this app at all.
Architect+QA (prompted with the ground truth pre-checked against the actual source, not left to
discover it) cut all three:

- **"Guard the Recompute button against double-clicks."** There is no manual
  "Recompute recommendations" button anywhere in the UI — recomputes are automatic and
  server-side, fired after each crawl slice (`crawl_curate_each_slice`). No component calls
  `api.recompute(...)`. This is the same "guard double-submit on Recompute" idea already logged
  as cut once before (see the "Keyboard shortcuts for like/block" entry earlier in the backlog) —
  Product re-proposed it from a summary without checking it had already been rejected.
- **"Fall back to a placeholder image when album art 404s."** `FeedCard.tsx` renders zero `<img>`
  elements today and `Recommendation`/`Facets` (`api/types.ts`) carry no art-URL field at all —
  there is no album art in this UI to begin with. Not a bug fix; would have meant inventing a new
  feature (backend field, fetch, markup, layout, a placeholder asset) from scratch, well outside
  "small" and arguably a visual-design call this routine shouldn't make unilaterally anyway.
- **"Shared `pluralize()` util for count copy."** `lib/format.ts`'s `plural(n, one, many?)`
  already exists and is already wired into every count call site (`ScanListPage`,
  `ScanFeedPage`, `ColdStartPanel`, `FeedCard`) — the third time this exact non-gap has been
  proposed (see the two earlier entries above).

Two same-day condensed-context prompts is not enough of a check on its own: Product should be
told explicitly to skim `frontend/CLAUDE.md`'s "Known conflicts and deferred items" and grep the
real component tree for the feature it's about to propose (an `<img>` tag, a button label, a
util name) *before* writing the proposal, not rely on Architect+QA to catch it after the fact —
QA catching it still burned two full `claude -p` calls on proposals that never had a chance.
Album art in particular is worth flagging separately: if Roy ever wants cover art on cards, that
touches the backend (Bandcamp album pages do carry art URLs the parser doesn't currently keep)
and is a real, if bigger, idea — just not a same-run, no-backend-change UI polish item.

## 2026-09-03 — hourly routine, second Option C round of this run: one shipped, one more caught pre-QA

First call (fed the real, current file inventory rather than a summary, specifically to route
around the failure mode above) found one genuinely new gap — CSV export of the feed — which
survived a self-check against `grep -i 'csv|createObjectURL|download='` (zero hits) and an
Architect+QA sanity call, then got built and opened as a PR this same task.

A second attempt later in the same run, prompted with an updated inventory including the just-
shipped CSV export, proposed one more idea: "announce new recommendations via an `aria-live`
region when a running scan's poll increases the count." Caught before spending an Architect+QA
call this time — `ScanFeedPage.tsx`'s `countline` paragraph already has `role="status"
aria-live="polite"` (added 2026-09-03, commit b781405 / PR #100, "announce the feed match count
to screen readers") and re-renders on every change to `total`, which already covers a poll-driven
increase during a running scan, not just a like/block decrement. No new evidence beyond what
b781405's own commit message already states — do not re-propose this without a concrete reason
the existing live region doesn't fire for the running-scan case specifically (e.g. a repro showing
`total` not updating during a live poll).

Net for the run: pre-checking Product's proposal against the actual source (not just a summary)
before spending the QA call caught this one for near-zero cost, same as the sort-order duplicate
caught earlier in the run. Two-for-two on self-caught duplicates today suggests the fully-mined
backlog is now past the point where a summary-fed Product call reliably finds real gaps — future
rounds may want to lead with a targeted grep for the proposed feature before invoking `claude -p`
at all, rather than after.

## 2026-09-03 — hourly routine, another run: two more self-caught duplicates, one real gap found

Product's first-round proposals, again fed a component/lib inventory rather than a bare summary:

- **"Free-text search across recommendations."** Already fully built as `lib/quickFilter.ts`'s
  `matchesQuery()` — a case-insensitive substring match against title/band name, wired into a
  search input in `FilterBar.tsx` with its own keyboard-shortcut focus ref
  (`ScanFeedPage.tsx`'s `quickFilterRef`). Do not re-propose without a concrete gap in that
  existing implementation (e.g. it doesn't search `reasons`/tags — say which field is missing).
- **"Snooze a recommendation" (time-boxed dismissal, auto-reappears later).** Already fully
  built as the `blacklist.expires_at` mechanism (the "Blacklist is all-or-nothing forever" item
  above): `POST /api/blacklist` takes an optional `expires_at`, `build_exclusions` filters to
  `expires_at IS NULL OR expires_at > now()`, so a temporary block auto-expires with no cleanup
  job. Functionally identical to "snooze" under a different name — do not re-propose this under
  any other name (snooze, mute, hide-for-now, temporary-dismiss) without checking this mechanism
  first.

Caught both before spending an Architect+QA call by reading the actual source
(`grep`/`Read` on `quickFilter.ts` and `blacklist.py`), not trusting the proposal's framing.

A second, more targeted Product round (fed the two rejections explicitly, asked to justify any
further idea against source) used its own Explore subagent and surfaced one genuine, previously
unproposed gap: `Blacklist.reason` was wired end-to-end in the backend and typed on the frontend
(`Blocked.reason`) but no UI ever set or displayed it — confirmed by grep before it reached
Architect+QA. Built this run — see "Block reason has no UI" above. The same round's other idea,
a pre-block confirm dialog on a single card, was correctly cut by Architect+QA: the existing 6s
Undo banner already covers the identical mis-click failure mode with less friction than a
confirm step would add to every correct block, so a confirm would be redundant safety rather
than a real improvement.

Also noticed in passing (not this run's task, just recorded so it isn't mistaken for a live
feature later): `FeedCard.tsx`'s doc comment and `config.ts`'s `BLOCK_DURATIONS` reference a
"block for… ▾" duration picker that no longer exists anywhere in the current JSX — `FeedCard`'s
block button just calls `onBlock(rec)` with no `expiresAt`, and `BulkActionBar` has no duration
UI either. Only `SidePanels.tsx`'s "renew ▾" dropdown (for a block already about to lapse) still
uses `BLOCK_DURATIONS`. Looks like stale documentation/dead code left over from a card-layout
cleanup pass, not a regression from this run's change — worth a future small "resurrect or
delete the duration-picker-at-block-time UI" cleanup item, but out of scope for today's task.
