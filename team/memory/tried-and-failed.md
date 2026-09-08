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

## 2026-09-04 — hourly routine, Option C caught a proposal that would have undone a real Roy decision

Product's first round (fed the current file inventory plus the rejected-ideas list) proposed
two things, both confirmed real gaps by direct grep before reaching Architect+QA:

- **"Wire up the already-built `recsToMarkdown` into a Copy-as-Markdown button."** `grep -rn
  "recsToMarkdown"` does show zero call sites outside its own test — genuinely dead code, exactly
  as Product described. But `git log -p -- frontend/src/lib/markdown.ts` and the commit that
  deleted its old caller (`2517b6f`, "remove dead toolbar buttons (#107)") tell the rest of the
  story: `CopyLinkButton`/`CopyMarkdownButton` were deleted **"per request"** — this was Roy
  explicitly asking for that UI to go, not an unfinished feature. `lib/markdown.ts` itself was
  simply left behind by that deletion (the commit only removed the button component + its test).
  Re-adding a button for it would have silently reintroduced something Roy asked removed one day
  earlier. **Do not propose resurrecting `recsToMarkdown`'s UI again** — if genuinely wanted, that
  is Roy's call to make explicitly, not a "found a gap" pickup. The dead file itself
  (`lib/markdown.ts` + its test) is fair game for an ordinary dead-code-deletion cleanup, same as
  the `COPY_LINK_FEEDBACK_MS` cleanup earlier — deleting unreachable code doesn't revive the
  feature, it just stops misleading later scans of the codebase into thinking it's an unfinished
  feature.
- **"Commit a typed block-reason on blur, not just Enter."** No such history — `Blacklist.reason`
  UI only shipped a few hours earlier in the same day (#131) with Enter-only commit, a plausible
  incremental gap rather than a deliberate omission. Built this run (see backlog.md).

Lesson for future rounds: before building on a "this is dead/unwired code" finding, check *why*
it's dead — `git log -p`/`git blame` on the file, not just a same-session grep. A deliberate
removal and an unfinished feature look identical to a grep for call sites; only the history tells
them apart, and building the wrong one means undoing a decision Roy already made on purpose.

## 2026-09-04 — hourly routine, another Option C round: one built, one caught before the QA call

Product's round (fed the real component/lib file inventory, not a summary) proposed two ideas:

- **"Show the co-ownership count (`reasons.co_owners`) on each `FeedCard`."** Framed as "the
  strongest ranking signal is invisible in the feed." Checked against source before spending a QA
  call: `FeedCard.tsx` has no score/co-owner display of any kind today, and `git log -S'"score"'
  -- frontend/src/features/feed/FeedCard.tsx` finds why — commit `8507764` ("card/header cleanup —
  drop seen+score… (#122)", merged the day before this run, Roy co-authored, "verified in a real
  browser") explicitly hid the score badge on purpose: *"The score itself still drives sorting and
  CSV export server-side and client-side — only the visual badge is gone."* An existing test
  (`feed.test.tsx`: `'renders a recommendation with its artist, but no visible score or co-owner
  chip'`) locks this in. Adding a co-owner count line would have silently reintroduced the exact
  numeric badge Roy asked removed one day earlier — same failure mode as the `recsToMarkdown`
  catch above (check *why* something is absent, not just that it's absent). **Do not re-propose a
  visible score/co-owner-count badge on `FeedCard` without Roy asking for it explicitly** — CSV
  export and the (currently unrendered) `scan.seeds` data are fine, this specific badge is not.
- **"Seed resolution status panel."** Genuinely new and verified sound: `GET /api/scans/{id}`
  (`ScanDetailOut.seeds`) has returned `{url, seed_type, resolved_album_id, resolved_track_id}` per
  seed since the multi-seed scan feature shipped, fully typed on the frontend (`ScanSeed` in
  `api/types.ts`) and fetched on every scan-detail load — but `grep -rn 'scan.seeds\|resolved_album_id'
  --include='*.tsx'` outside `api/types.ts` and test files came back empty. No history of a removed
  seeds UI (checked `git log --all --diff-filter=D --summary | grep -i seed`, nothing). Built this
  run — see backlog.md.

Net: leading Product with the real file inventory plus an explicit "check git history before
trusting a gap" instruction caught a real regression risk (resurrecting a deliberately-hidden
score badge) for the cost of one grep + one `git log -S`, before it ever reached the QA call.

Also self-checked (not fed to Product) while looking for a second task the same run: `reasons.
seed_tags` (the "via <tags>" genre-provenance explanation CLAUDE.md's M4 notes describe as "shown
as 'via …' in the UI") is typed on the frontend, computed server-side by
`_seed_tag_provenance()`, and rendered... nowhere. A `.via` CSS rule even still exists in
`feed.css` with nothing left that uses it. Looks exactly like the seed-resolution-panel gap this
run just built. It is not: `git log -S'.via' -- frontend/src/features/feed/feed.css` finds
`640b5eb` ("drop 3 unwanted card elements (#103)", same day as the score removal, Roy
co-authored) — its own commit message says plainly *"Removed three things the product owner
doesn't want on the card: … the 'via <tags>' line under a card's reasons …"*. **Do not propose
resurrecting the "via <tags>" line — same rule as the score badge: this is Roy's call to reverse
explicitly, not a gap to fill.** The orphaned `.via` CSS rule itself is fair game for a future
dead-code cleanup (delete the rule, not resurrect a user of it), same category as the
`COPY_LINK_FEEDBACK_MS` cleanup — but that's cosmetic housekeeping, not a product fix.

Lesson reinforced: on this codebase specifically, an "I found data the API returns that nothing
renders" grep hit needs a `git log -S` check on the *specific missing UI element* (not just the
data field) before it's trusted as a real gap — #103 and #122, both from the same day, deliberately
stripped down what the card shows, so several plausible "add this back" ideas are actually the
one thing this codebase is *not* short on: things Roy removed on purpose.

## 2026-09-04 — hourly routine, Option C round self-caught all three proposals pre-QA, picked up flagged cleanup instead

Product's round (fed the real frontend file inventory plus an explicit list of ~30 already-shipped
items and the two known deliberate-removal traps) proposed three ideas, all cut by checking source
directly rather than spending an Architect+QA call:

- **"Light/dark theme toggle with persisted preference."** `frontend/CLAUDE.md`'s "Already
  satisfied — don't 'fix' these" section states plainly: *"Single-theme dark is a stated choice, not
  a missing light mode."* Building this would reverse a documented deliberate decision — the exact
  same failure mode as the score-badge and "via <tags>" catches logged above, just for a design
  decision recorded in a CLAUDE.md rather than discovered via `git log -S`. **Do not re-propose a
  theme toggle without Roy asking for one explicitly.**
- **"Sort control for the feed (Newest / Band A–Z)."** Already exists: `FilterBar.tsx` has a
  `Dropdown label={\`Sort · ${SORTS[filters.sort]} ▾\`}` backed by a typed `SortKey`/`SORTS` map,
  confirmed by grep. A straight duplicate proposal.
- **"Debounce the quick-filter search input."** `ScanFeedPage.tsx`'s `visibleRows` is a `useMemo`
  filtering `rows` (the currently-loaded page, not the full ~1,600-item feed) — this is not the
  thousands-of-facet-tags case `frontend/CLAUDE.md` rule 8's `useDeferredValue` guidance is about.
  No measured perf problem; would have been premature optimization of an already-cheap operation.

Picked up instead of a fourth Product round: two items already flagged in this file's own
2026-09-04 entries above as "fair game for a future dead-code cleanup" — `lib/markdown.ts`'s
`recsToMarkdown` (dead since the button that called it was deliberately removed) and the orphaned
`.via` CSS rule in `feed.css`. Both re-confirmed dead via grep (zero other references) immediately
before deleting. Built and merged this run — see backlog.md.

Lesson: this file's own "fair game for a future cleanup" notes are a legitimate task source when a
fresh Product round comes up empty — they've already been vetted (grep-confirmed dead, history-
checked as not a resurrection candidate), so re-verifying and executing them costs less than another
`claude -p` round that risks yet another duplicate proposal against an already heavily-mined
backlog.

## 2026-09-08 — hourly routine: backlog.md's own "Done" prose is stale for several items; a bigger resurrection-trap class than previously logged

While picking up a stray in-flight PR and then running an Option C round, grepped the actual source
tree for several features `backlog.md` describes as built-and-merged, expecting to reuse their code
as a pattern. They're gone: `CopyLinkButton`/`CopyMarkdownButton` (the "Copy link"/"Copy as Markdown"
items), `lib/density.ts` (the density toggle), and `lib/visited.ts` (the "seen" marker) have zero
references anywhere in the current frontend tree — not just unused, entirely absent as files. This
is the same class of thing the score-badge/"via tags" catches above already warned about (Roy removes
UI he doesn't want, and this repo's own history around those two commits (#103/#122) shows it happens
in batches), but the scale is bigger than one or two isolated items: `backlog.md`'s prose was never
retroactively corrected for any of these later removals the way the tried-and-failed.md entries above
document for the two known cases. **Practical upshot: `backlog.md`'s "[x] Done: …" writeup describes
what was true the day it was written, not necessarily what's in the tree today.** Do not trust it as
a live index of what exists — grep the actual `frontend/src` tree before reusing "already-built"
code as a reference pattern, and before assuming a described component is available to import.
(One data point on *why* the git history can't just be consulted instead: this sandbox's clone was
shallow — `--depth 50` — for most of this session, which made `git log -S` over the full project
history silently incomplete until `git fetch --unshallow` was run. If a `git log -S` search for a
removal commit comes back empty, confirm the clone isn't shallow before trusting that as "no removal
happened.")

Concretely for future Product/Option-C rounds: a "copy the current filtered view's link" proposal is
a resurrection trap exactly like the score badge and "via tags" ones — `COPY_LINK_FEEDBACK_MS` was
explicitly deleted as dead code in a real past commit (#135), which only makes sense if the button
using it was already gone by then. **Do not re-propose a copy-link/copy-as-markdown button, a density
toggle, or a "seen" marker on visited cards without Roy asking for one explicitly** — same standing
rule as the theme toggle and score badge above.

Also cut this round, for a different (non-resurrection) reason: a **"recently added" sort** proposal
was technically unsound as specified, caught by the Architect+QA call rather than self-caught —
`Recommendation` has `computed_at`, not `created_at`, and recommendations are wholesale cleared and
reinserted on every recompute inside one transaction, so every row from one recompute gets
essentially the same timestamp. "Recent" would degenerate into "last recompute's insert order," not
a real recency signal — building it properly needs a `first_seen_at` that survives clear+insert
(schema + curation-logic change), not a one-hour sort-key add. Don't re-propose the naive version;
a `first_seen_at`-backed version would be a legitimately different, larger proposal.

## 2026-09-08 — hourly routine: `Like.uq_like_item`/`Recommendation.uq_recommendation_item` share
the same NULL-pattern bug `FanItem.uq_fan_item` had, left unfixed on purpose

While fixing `FanItem.uq_fan_item` (a `UniqueConstraint` on `(fan_id, item_type, album_id,
track_id)` that never actually enforced anything for album/track rows, since one of `album_id`/
`track_id` is always NULL and standard SQL treats NULL as distinct from NULL even inside a unique
constraint — see `backlog.md`'s 2026-09-08 entry for the full writeup and the fix, two partial
unique indexes instead of one flat constraint), a grep for the same shape
(`UniqueConstraint(..., "item_type", "album_id", "track_id")`) turned up two more instances with
the identical structural bug:

- `Like.uq_like_item` on `(user_id, item_type, album_id, track_id)`
- `Recommendation.uq_recommendation_item` on `(scan_id, item_type, album_id, track_id)`

Both are genuinely broken in the same way — a duplicate `Like`/`Recommendation` row for the same
album or track could insert without error. **Left unfixed this round, deliberately, not an
oversight:** the practical exposure is much lower than `FanItem`'s.
`Recommendation` rows are wholesale cleared and reinserted by `curate()`/`compute_recommendations`
inside one single-writer transaction (see `curation/generation.py`/`engine.py`) — there's no
concurrent-worker race analogous to two crawl workers hitting the same fan's collection pages, so a
duplicate here would need a bug in the curation loop itself (e.g. computing the same candidate
twice in one pass), not an external race. `Like` rows are created by one user's own API click
(`POST /api/likes`), not a fan-out crawl — the realistic failure mode is a double-submit from a fast
double-click, which is a much narrower, lower-frequency case than "two crawl workers processing
overlapping collection pages," which the `FanItem` mapper code's own comments call "the common
case, not the exotic one."
**This is fair game for a future task**, following the exact pattern the `FanItem` fix just
established: two partial unique indexes per table (`Like`: `uq_like_item_album`/
`uq_like_item_track`, keyed on `(user_id, album_id)`/`(user_id, track_id)` with the NULL-column
`WHERE`; `Recommendation`: same shape keyed on `scan_id`), plus a guarded Alembic migration
following `0018_fan_item_partial_unique`'s `_find_unique`/`_drop_unique` structure. Verify the same
way: a direct duplicate-insert test bypassing the application-level check, asserting `IntegrityError`
now fires. Do them as one item each (or together) rather than reopening `FanItem`'s migration.
