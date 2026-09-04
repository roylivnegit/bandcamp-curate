# Backlog

Ranked. The Head of Product owns the order; the Tech Lead picks from the top of it.

Anything the team defers during grooming comes back here **with its reason**. Anything
discovered mid-build goes here rather than into the current diff.

Status: `[ ]` open · `[~]` parked mid-cycle · `[x]` done · `[-]` dropped (say why)

---

## Sprint 0 — build our own working environment

This comes first, in order. The team has no sandbox, no CI and no browser test harness yet,
so QA cannot honestly gate anything: it will mark most checks `skipped` until these land.
That is the point — the gaps are the first work.

- [x] **E0-1 · Sandbox database.** `team/tools/sandbox-db.sh` with `up` and `down`. Brings up
  Postgres under its own docker compose project name and its own port (55432, per
  `team/.env.team`) so it can never collide with Roy's dev stack on 5432. Runs
  `alembic upgrade head`, then loads `team/fixtures/seed.sql`. Refuses to run if
  `DATABASE_URL` is not local.
  *Why first:* the repo's `.env` points `DATABASE_URL` at Neon, and the uncommitted
  `docker-compose.yml` change points the worker there too. Without this, anything the team
  runs touches production.

- [x] **E0-2 · Seed fixtures.** `team/fixtures/seed.sql` — a small synthetic corpus: a
  handful of fans, bands, albums, tracks, tags, fan_items and album_supporters, wired so
  curation actually produces recommendations and so the exclusion paths (owned, wishlisted,
  followed-by-host, liked, blacklisted) each have at least one case.
  Build it from `backend/tests/fixtures/`, never from Neon. No real user data leaves that
  database.

- [x] **E0-3 · CI.** `.github/workflows/ci.yml` running on every PR: `pytest -q`,
  `ruff check`, `npm test`, `npm run lint`, `tsc -b`. Cache pip and npm.
  *Why:* there is no CI at all today. "Auto-merge when green" has nothing producing green.
  Landed 2026-09-01 (#19), after Roy granted the `workflow` scope
  (`gh auth refresh -h github.com -s workflow`). First real run caught a genuine bug on its
  own first pass — `scripts.co_owner_stats` only imported under `python -m pytest`, not bare
  `pytest` — fixed in #20 before #19 could go green.

- [x] **E0-4 · E2E harness.** `frontend/e2e/` on Playwright, headless Chromium. Boots the API
  and the Vite dev server against the E0-1 sandbox on the ports in `team/.env.team`, then
  walks the real path: sign up → log in → feed renders → filter by tag → like → block →
  reload and confirm it stuck. Screenshot and trace on failure.
  Must run with nobody watching. It never depends on Roy's Chrome being open.

- [x] **E0-5 · Branch protection.** Requires `backend` + `frontend` (the E0-3 checks) on
  `main`, auto-merge enabled, force-push and branch deletion blocked.
  *Why:* this is what makes the gate real rather than self-reported.
  Landed 2026-09-01. The real blocker was never admin — `roylivnegit` already had it, verified
  directly (`GET .../collaborators/roylivnegit/permission` → `"permission":"admin"`).
  Branch protection is a GitHub Pro/Team/public-repo feature; this repo was private on the
  free plan. Roy made it public rather than upgrade — confirmed the Nimble key was never
  committed anywhere in history before doing so.

- [x] **E0-6 · Cycle dashboard.** `team/tools/report.py` — reads `team/memory/metrics.md`,
  the transcripts and the ADRs, and produces one page: what shipped, what it cost, the
  product numbers over time, and an index of decisions. Without it Roy has to read five
  transcripts a day to know what happened.

- [ ] **E0-7 · Self-check.** One full dry-run cycle end to end on a deliberately trivial
  item, proving all seven phases, TOML validation, the worktree, the sandbox and both gates
  work together. **Autonomous building stays off until this passes.**

---

## Product backlog — after Sprint 0

Ordered by the Head of Product. These are starting points, not instructions; propose better
ones.

**Current focus (set 2026-09-02): UI/UX modernization.** Roy wants crate-digger to feel like a
modern web app — better UI elements, tighter flow, fewer rough edges. Prefer picking or proposing
frontend/ items over backend ones here, as long as they stay small and have a testable definition
of done. The hourly routine has no browser or screenshots, so a change whose only "done" signal is
visual taste ("looks nicer") is out of scope for it — save those for a session with Roy watching.
Stay inside `frontend/CLAUDE.md`'s existing design system and conventions rather than inventing new
visual direction, and leave the icon-glyphs-vs-SVG-icons question alone — that file flags it as a
deliberate, unresolved call for Roy, not something to resolve unilaterally.

- [x] **Skeleton loading states.** Feed/scan pages show plain text `Loading…`; replace with
  skeleton placeholders shaped like the real cards. Also fixes the layout shift when the first
  page lands. `frontend/CLAUDE.md` "Known conflicts and deferred items" flags this as cosmetic
  and unclaimed.
  Done: `FeedCard.tsx` exports `FeedCardSkeleton` (mirrors a real card's score box, title, band
  line and one chip) and `ScanListPage.tsx` gets a matching `ScanCardSkeleton`. `ScanFeedPage`
  shows 5 of them, wrapped in `role="status" aria-label="Loading recommendations…"`, only for the
  first page (`loading && rows.length === 0`) — `loadMore`'s `loading` shares the flag but already
  has real rows on screen, so it's excluded. `ScanListPage` shows 3 in place of the old "Loading
  scans…" text, same `role="status"` pattern. Shimmer is a shared `.sk` class in `base.css`
  (`background-position` keyframe, no library); the global `prefers-reduced-motion` block already
  zeroes `animation-duration`, freezing it to a static placeholder rather than a spinning one.
  Individual skeleton cards are `aria-hidden` since the wrapper's `role="status"` carries the
  announcement. Verified behaviorally, not visually: two new tests hold the relevant fetch behind
  an unresolved promise and assert the skeleton (`getByLabelText`) is present while it's pending
  and gone once real content lands — `shows skeleton scan cards while the list loads, then the
  real ones` and `shows skeleton recommendation cards while the first page loads`. 27/27 frontend
  tests pass, tsc/lint/build clean (chunk split intact). PR: see git history.

- [x] **Feed filters belong in the URL.** `useFeedFilters` lives in `useState`, so a filtered
  view can't be shared or bookmarked, and browser-back silently drops it. Move it onto
  `useSearchParams`. Same source in `frontend/CLAUDE.md`.
  Done: `useFeedFilters.ts` rewritten on `useSearchParams` instead of five separate `useState`s.
  Reuses the exact query param names `filterQuery` (`api/client.ts`) already sends to the API
  (`item_type`, `tag`/`exclude_tag`, `tag_contains`/`exclude_tag_contains`, `label_id`), plus a
  UI-only `label_name` so the artist-filter pill doesn't need an extra fetch to render after a
  fresh page load. Every setter uses `setSearchParams`'s functional-updater form against `prev`
  (never the memoized `tags`/`label`/etc.), so none needs those as a `useCallback` dependency —
  the same "derive during render, update functionally" shape as everywhere else in this file, now
  against the URL instead of local state. All writes pass `{ replace: true }`, so toggling several
  filters leaves one history entry to land back on, not one per click. **Zero changes needed** in
  `FilterBar.tsx`/`ScanFeedPage.tsx`/`FeedCard.tsx` — the hook's public shape (`itemType`,
  `setItemType`, `tags`, `includeTag`, …) is unchanged, only its backing store moved.
  `test/renderApp.tsx` gained a `LocationWatcher` + `currentLocation()` so tests can assert on the
  URL a filter click actually produced (MemoryRouter's history isn't otherwise reachable from
  outside the tree). New/extended tests: clicking a genre chip or an artist name lands the
  matching `tag=`/`label_id=`/`label_name=` in the URL; opening `/scans/1?item_type=album&tag=…`
  directly restores that exact filtered view (the "shared/bookmarked link" case) instead of
  starting blank; and a second, unrelated filter change leaves the first one's param in place
  (the "browser-back still finds it" case) rather than clobbering it. 27/27 frontend tests pass,
  tsc/lint/build clean. PR: see git history.

- [x] **Verify contrast on hint text.** `--faint: #667085` on `--surface: #141823` is the
  likeliest AA failure in the palette and nobody has measured it. Compute the real ratio; if it
  fails, adjust the token once, everywhere. Same source.
  Done: it failed. `--faint` on `--surface`/`--surface-2` (the two backgrounds it renders text
  against — `.via`, `.field-hint`, `.score span`, `.eyebrow`/`.label`, input placeholders, all
  9-13px so none qualify for WCAG's "large text" 3:1 exception) measured 3.56:1 / 3.23:1, below
  the 4.5:1 AA minimum for normal text. Retuned the token to `#7e889c` (same hue, lightened) —
  now 4.97:1 / 4.51:1 against those two, 5.49:1 against `--bg`, and still clearly darker than
  `--muted` so the two-tier hierarchy holds. Added `lib/contrast.ts` (a small WCAG relative-
  luminance/contrast-ratio helper — no new dependency) and `lib/contrast.test.ts`, which reads
  `tokens.css` itself via a Vite `?raw` import rather than a hand-copied hex, so the test fails
  the moment the token drifts back below 4.5:1 rather than only catching a value computed once by
  hand. Required a narrow `vite.config.ts` tweak: `test.css` was `false` (mocks out all CSS
  content in tests, for speed), changed to `{ include: [/\.css\?raw$/] }` so an explicit `?raw`
  import still gets the real file text while ordinary side-effect CSS imports stay mocked
  everywhere else. 28/28 frontend tests pass, tsc/lint/build clean. PR: see git history.

- [~] **Make the order mean something, not the length.** Roy wants a long list kept — do not
  cut the feed down. The actual problem is ranking, not volume: work out whether the ranking
  is too flat, the co-ownership signal too weak, or ties too common, then sort by relevancy
  so the *best* matches are reliably at the top even with ~1,600 items sitting underneath.
  Measure: does the top of the list hold up — does Roy find something worth clicking near
  the top, not just somewhere in a long scroll.
  One concrete piece landed: `curate.engine.compute_recommendations` sorted only by
  `score`, and Python's stable sort then left same-score items in whatever order the
  underlying SQL query happened to return rows in — which Postgres does not guarantee
  without an `ORDER BY`. "One co-owner, no tag data" is the single most common score in the
  feed (bare `W_CO_OWNER`, zero tag term), so this was exactly the score band Roy actually
  scrolls through, and it could silently reshuffle between recomputes. Added an explicit,
  deterministic tie-break: more co-owners, then more tag affinity (the two raw signals the
  score is built from), then album-before-track, then a stable id — so equal-score items are
  still ordered by whatever relevance signal is available, and any true remainder is
  reproducible run to run instead of accidental. Covered by
  `test_tied_scores_break_ties_deterministically`.
  **Left open:** this doesn't touch whether the ranking is *too flat overall* (the
  co-ownership signal too weak, most items landing in that one tied score band to begin
  with) — that needs the same "run against a real crawl" measurement the mega-supporters
  item below is blocked on, no sandbox DB here to produce it.

- [x] **Tag coverage caps tag-affinity.** Tags live on album *pages*, which the crawl mostly
  does not fetch, so the genre signal is sparse and the "via …" explanations are thin.
  Options: enrich top recs only, derive from `band_tags`, or find a cheaper source of genre.
  See `CLAUDE.md` (M4 Curation).
  Done (option 2, `derive from band_tags`): `curation.engine._effective_album_tags()` falls
  back to a band's aggregated `band_tags` for any album with zero page-level `album_tags` —
  used both for scoring a candidate's `tag_affinity`/`matched_tags` and for building the
  viewer's own genre profile (`_my_tag_profile`, which previously went silent on an owned
  album with no page tags). An album that DOES carry its own page tags is untouched — no
  blending.
  **Extended to tracks (2026-09-02, Roy: "no technical diff between album and track, treat
  them the same"):** track candidates previously got zero tag-affinity scoring at all — only
  albums did — and `_my_tag_profile` only ever counted owned albums, never owned tracks.
  Added `_effective_track_tags()` (identical logic to the album version) and mirrored the
  album scoring block for tracks. See `CLAUDE.md` M4 Curation for the standing rule this adds.
  `_seed_tag_provenance` (the "via …" reason text) is still NOT touched — same sparsity
  problem, left for a follow-up since it needs a different query shape (joins on the seed
  item's own tags, not a per-item fallback) and applies equally to albums and tracks there
  too. PR: see git history.

- [~] **Mega-supporters flatten the signal.** A collector who owns 8,000 records co-owns
  everything with everyone. Score their overlap lower than a collector with 200 records and a
  40% overlap with Roy. Worth measuring before building.
  Measurement landed, the fix hasn't: `curation.engine.neighbour_size_report()` +
  `scripts/mega_supporter_stats.py` bucket a scan's neighbours by recorded collection size and
  report each bucket's share of neighbours vs. its share of raw candidate votes vs. its share of
  the ADR-0003 weighted score. Needs a real crawl to run against (no sandbox DB in this
  environment), but the fixture test spells out the shape of the problem it's built to catch:
  a 4-item collector can cast 3x a 2-item collector's raw votes while both get an even split of
  the weighted score, because ADR-0003 weights by overlap-with-me, not by the neighbour's own
  collection size — so if real data shows `vote_share` badly outrunning `neighbour_share` while
  `weighted_share` tracks it fine, the raw `co_owners`/`min_co_owners` floor is the one place
  still exposed to this, not the score. Left open rather than building a fix blind.

- [x] **Explanations Roy can trust.** A rec with a reason he believes gets clicked; a bare
  score does not. `reasons.seed_tags` already exists — build on it.
  Done (first slice): `curation.engine._seed_tag_provenance()` used to read a seed album/track's
  genres via a direct `AlbumTag`/`TrackTag` join, so a seed that hadn't been tag-crawled yet
  produced zero "via …" reasons for everything it surfaced — the exact sparsity
  `_effective_album_tags`/`_effective_track_tags` already fixed for scoring, but this query
  bypassed by joining the tag tables directly instead of going through those helpers. Now it
  computes each seed's *effective* tags first (page tags, falling back to `band_tags`) and
  attributes provenance from that — so a seed album/track with no page tags of its own still
  explains what it recommended. Covered by
  `test_seed_tag_provenance_falls_back_to_band_tags`. PR: see git history.

- [x] **"Copy link" for the current filtered feed.** *(proposed by the hourly routine,
  2026-09-02)* Filters live in the URL now (`useFeedFilters`/`useSearchParams`), so a filtered
  view is shareable/bookmarkable in principle, but nothing in the UI tells a reader that or
  gives them an easy way to do it — a polished app surfaces this instead of relying on someone
  noticing the address bar. Architect+QA: sound, testable by mocking `navigator.clipboard.
  writeText` and asserting the button's accessible label toggles to "Copied" and back (fake
  timers), small.
  Done: new `components/CopyLinkButton.tsx` — reads the current route via `useLocation()`
  (not `window.location.href`, which a `MemoryRouter`-backed test never updates; the real app's
  `BrowserRouter` does, but building the URL from `location.pathname`/`location.search` +
  `window.location.origin` works identically in both and is what makes this testable without a
  browser) and calls `navigator.clipboard.writeText`. Shows "Copied" for
  `COPY_LINK_FEEDBACK_MS` (2000ms, new in `config.ts`) on success; on a rejected write (denied
  permission, insecure context) it silently no-ops rather than claiming a copy that didn't
  happen. Wired into `FilterBar.tsx` next to the Liked/Blocked buttons. Covered by three new
  tests in `CopyLinkButton.test.tsx` (standalone RTL render, no api/store mocking needed): the
  written string is the full URL including the query string; the "Copied" confirmation reverts
  to "Copy link" after the feedback window (`vi.useFakeTimers({ shouldAdvanceTime: true })` +
  `advanceTimersByTimeAsync`, the same pattern the Undo-banner tests use); a rejected clipboard
  write leaves the button reading "Copy link". 55/55 frontend tests pass, tsc/lint/build clean
  (chunk split intact). PR: see git history.

- [x] **"?" keyboard-shortcuts help panel.** *(proposed by the hourly routine, 2026-09-02,
  Architect+QA-approved)* The `l`/`b` like/block shortcuts and the Dropdown arrow-key
  navigation both shipped but are invisible — nothing told a user they exist.
  Done: new `components/ShortcutsHelp.tsx`, mounted once in `ScanFeedPage.tsx` (the page the
  shortcuts it documents actually apply to). A document-level `keydown` listener (always
  attached, not just while open, so `?` can open it from anywhere on the page) toggles the
  panel — guarded against firing while the target is an `<input>`/`<textarea>`/
  contenteditable element, so typing a literal `?` into the genre-search or tag-contains
  fields doesn't hijack it. While open, `role="dialog" aria-modal aria-labelledby` plus the
  same outside-click/Escape-close pattern `Dropdown.tsx` already uses (a `document`
  `mousedown` listener checking `panelRef.contains`, effect-scoped to `[open]`); closing —
  by Escape, outside click, or the panel's own Close button — restores focus to whatever
  had it before the panel opened, via the same effect's cleanup. `ShortcutsHelp.css` adds a
  centered, dimmed overlay; its one animation (a 150ms fade-in) needs no explicit
  reduced-motion guard since `base.css`'s existing global block already zeroes all
  `animation-duration`. Covered by five new tests in `ShortcutsHelp.test.tsx` (standalone RTL
  render, no router/api mocking needed): `?` opens the panel and lists both shortcuts; `?`
  while a text field is focused does nothing; Escape closes it and returns focus to the
  previously-focused control; a click on the panel itself doesn't close it but a click
  outside does; a second `?` press toggles it back closed. 60/60 frontend tests pass,
  tsc/lint/build clean (chunk split intact — the new CSS/JS lands inside the `ScanFeedPage`
  chunk, since that's its only importer). PR: see git history.

- [x] **Roving-tabindex arrow-key navigation across feed cards.** *(proposed by the hourly
  routine, 2026-09-02, Architect+QA-approved)* The shortcuts help panel documents `l`/`b` and
  the Dropdown arrow-key nav, but there was no keyboard way to move *between* feed cards —
  reaching the next one meant Tabbing through every focusable element inside the current one.
  Done: `ScanFeedPage` keeps `activeIndex` state (an index into `rows`, reset to 0 whenever
  `loadFirstPage` lands a fresh set, and clamped at render time so a like/block removing the
  active row never leaves it pointing past the end) — every `FeedCard`'s `active` prop is one
  `i === activeCardIndex` comparison in the existing `rows.map`, not a per-card scan, per the
  Architect/QA scoping note. Rows are wrapped in a new `.cardlist` div carrying one
  `onKeyDown`; `FeedCard`'s `<article>` gets `id={cardId}` and `tabIndex={active ? 0 : -1}`.
  ArrowDown/ArrowUp move to the next/previous card and clamp at the ends (no wrap, unlike
  `Dropdown`'s menu nav — a feed list has a definite start/end, not a cycling menu);
  Home/End jump to the first/last. Scoped to fire only when the event target itself carries
  the `card` class (mirrors `Dropdown.tsx`'s `.ddrow` scoping), so it can't hijack arrow keys
  typed into a filter field elsewhere on the page. `ShortcutsHelp`'s existing ↑/↓ and Home/End
  rows were reworded to cover both contexts (menus and the card list) rather than adding
  duplicate rows. Covered by two new tests in `feed.test.tsx` with three distinct cards: only
  the first card is a tab stop initially and ArrowDown moves both the DOM focus and the
  `tabindex` attributes to the next card; ArrowUp/ArrowDown don't move past the first/last
  card, and Home/End jump straight to them. `FeedCard.test.tsx` updated for the two new
  required props. 68/68 frontend tests pass, tsc/lint/build clean (chunk split intact). PR:
  see git history.

- [x] **Resume feed scroll position across route changes.** *(proposed by the hourly routine,
  2026-09-02)* Clicking away from the feed (or navigating between scans) and back dropped the
  reader at the top of a long list, losing their place.
  Two other Product proposals from this round were cut before reaching Architect+QA — both
  turned out to already be implemented: an in-flight guard against duplicate rapid like/block
  calls (`ScanFeedPage.tsx`'s `inFlight` ref already does this) and a pluralization util for
  feed counts (`lib/format.ts`'s `plural()` already does this, already used everywhere counts
  render).
  Done: new `useResumeScroll(storageKey, ready)` hook (`features/feed/useResumeScroll.ts`).
  `storageKey` is `crate-digger.feedScroll:<scanId><location.search>` — the filter query
  string is already the live filter state (`useFeedFilters`/`useSearchParams`), so a different
  filter set is simply a different `sessionStorage` key; nothing has to detect "filters
  changed" and explicitly clear anything. A passive `scroll` listener writes
  `window.scrollY` under that key on every scroll; a separate effect, gated on `ready`
  (`showFeed && rows.length > 0`, not just `showFeed`, so it never fires against an empty
  page) and guarded by a `restoredFor` ref so it applies at most once per key, reads the
  stored value back and calls `window.scrollTo(0, y)`. Wired into `ScanFeedPage` via one
  `useLocation()` call and one hook call. Covered by two new tests in `feed.test.tsx`:
  scrolling, unmounting (JSDOM's stand-in for "the page goes away and comes back"), and
  remounting the same `/scans/1` route calls `scrollTo(0, 400)`; scrolling under
  `/scans/1?tag=psybient` and then remounting plain `/scans/1` does NOT restore — a different
  filter key finds nothing under it, confirming no stale cross-filter restore. 70/70 frontend
  tests pass, tsc/lint/build clean (chunk split intact). PR: see git history.

- [ ] **Second source: research first.** Beatport, SoundCloud, Discogs, Resident Advisor.
  Which of these exposes, without login and without paying: an artist's related artists, a
  release's buyers or likers, or a genre chart? Writes findings to `memory/research/`. Do not
  start building a provider before that note exists.
  **Real Nimble usage now authorized for this item specifically** (2026-09-01), POC only,
  capped at 100 requests total — see `team/memory/research/nimble-usage.md` for the running
  count, kept up to date every time this key is spent. Stop and ask Roy (email or in-session)
  before going over 100; do not keep going past the cap on your own judgment. This is the
  ONLY backlog item this key may be used for.

- [x] **Cold-start feeds give no reason, just emptiness.** *(proposed by the hourly routine,
  2026-09-02)* Done: `curation.engine.cold_start_diagnostics(session, scan, user)` is a new,
  genuinely separate read-only query (not instrumentation of `compute_recommendations`'s
  existing post-exclusion `candidates` stat) — it recomputes the taste-neighbour set, the
  distinct pre-exclusion candidate items they own, and tallies why each is excluded
  (owned/wishlisted/followed/blacklisted; a candidate can count under more than one reason).
  Wired into `GET /api/stats` as a new `cold_start` object (`neighbour_count`, `candidates`,
  `excluded_owned`, `excluded_wishlisted`, `excluded_followed`, `excluded_blacklisted`), null
  when the caller has no scan yet. Covered by
  `test_cold_start_diagnostics_counts_neighbours_candidates_and_reasons`,
  `test_cold_start_diagnostics_everything_excluded_by_follows` (asserts
  `excluded_by_reason.followed` is nonzero and accounts for every candidate),
  `test_cold_start_diagnostics_no_neighbours`, and an API-level assertion in `test_stats`.
  235/235 backend tests pass, ruff clean. PR: see git history.
  **Frontend follow-up landed (2026-09-02):** new `features/feed/ColdStartPanel.tsx` — a
  pure presentational component (`{neighbour_count, candidates, excluded_*}` in, prose out,
  matching the actual `ColdStartOut` shape exactly rather than an invented `reason` enum a
  previous Architect+QA round had rejected) — renders under `ScanFeedPage`'s existing "No
  recommendations in this scan yet." message (only in that branch, not the "nothing matches
  your filters" one — a narrow filter isn't a cold-start problem). `Stats`/`ColdStart` added
  to `api/types.ts`, mirroring `StatsOut`/`ColdStartOut` field-for-field. `ScanFeedPage` fetches
  `/api/stats` only when `total === 0` — deliberately keyed on `total`, not `rows.length`,
  since a like/block animates a row out of `rows` locally without moving `total`, so a
  transient one-row gap during that animation never triggers an extra fetch. Covered by 4 new
  tests in `ColdStartPanel.test.tsx` (standalone RTL render: renders every count and exclusion
  reason; a distinct message when there are no neighbours at all rather than an exclusion
  story; renders nothing for `null`/`undefined`) and 2 new integration tests in
  `feed.test.tsx` (a `count: 0` scan shows the diagnostics with the right numbers; a scan with
  rows never fetches `/api/stats` at all). 61/61 frontend tests pass, tsc/lint/build clean
  (chunk split intact). PR: see git history.

- [x] **The feed can silently reflow under a user who's mid-scroll.** *(proposed by the hourly
  routine, 2026-09-02)* Done: `scans.recompute_generation` (migration `0013`, guarded), bumped
  by `curation.engine.store_recommendations` on every call — the one place every re-curate path
  (mid-crawl slices, finalize, the API, the CLI) already goes through. Persisted, not an
  in-process int, per the architect note (slices re-curate from ARQ worker processes distinct
  from the API process). Returned in `GET /api/scans/{id}` (`ScanOut.recompute_generation`,
  what `ScanFeedPage` actually polls), `GET /api/stats`, and `GET /api/recommendations` (every
  row in one response carries the scan's generation at fetch time — they're all from the same
  transaction). `ScanFeedPage`'s page-0 reload effect now re-arms on `scan.recompute_generation`
  instead of `stats.recommendations`: strictly more often, since a swap (one item in, one out)
  bumps the generation without moving the total, which the old count-only signal missed
  entirely. A genuine reflow (the generation changed after the reader already had a page loaded,
  not the scan's first-ever observed generation) also sets a dismissible "list updated" notice
  (`.banner.reflow`) so the silent reset the old code already did for `recCount` changes doesn't
  stay silent for this one. Covered by `test_curate_bumps_recompute_generation_every_call`,
  `test_recommendations_carry_recompute_generation` (backend — the persisted counter and the
  per-response stable snapshot), and two vitest cases in `feed.test.tsx` ("feed reflow notice":
  a poll landing a new generation resets to page 0 and shows/dismisses the notice; a poll
  landing the same generation does neither) using `vi.useFakeTimers` to drive the real 4s poll
  deterministically. 237/237 backend tests pass, ruff clean; 25/25 frontend tests pass (stable
  across repeated runs), lint/tsc/build clean. PR: see git history.

- [x] **Blacklist is all-or-nothing forever.** *(proposed by the hourly routine, 2026-09-02)*
  Merged same run: PR #33 (`auto/blacklist-expiry`), squash-merged into main, CI green
  (232/232 backend tests, ruff clean).
  A user annoyed by one artist's recs today has no way to say "not now" without permanently
  blocking them — `POST /api/blacklist` has no expiry, so temporary fatigue turns into a
  manual unblock chore later (or the artist is just gone for good). Add optional
  `expires_at` on `blacklist` (nullable, migration), and have `build_exclusions` filter to
  rows where `expires_at IS NULL OR expires_at > now()`. Smallest and most bounded of the
  three proposals this cycle — one nullable column plus a `WHERE` clause tweak. Verify:
  frozen/injected `now` in pytest — a blacklist row with `expires_at` in the past is excluded
  from `build_exclusions`'s active set (band reappears in recs), one in the future still
  suppresses it; API test confirms `POST /api/blacklist` accepts an optional `expires_at` and
  round-trips it.

- [x] **Per-user crawl budgets.** `crawl_max_requests` and `provider_usage` are global, so one
  user's deep scan starves everyone else's. From `CLAUDE.md` "Immediate next steps".
  Done (first slice): `provider_usage.scan_id` (migration `0011`, nullable FK to `scans`)
  attributes each page-render fetch to the scan it was spent on. `runner.user_requests_used`
  sums a user's spend across all their own scans (join on `Scan.user_id`); `runner.
  user_budget_exhausted` + new `Settings.crawl_max_requests_per_user` (default `None` =
  unbounded, unchanged behavior) enforce it inside `run_until_empty` alongside the existing
  global `crawl_max_requests`, so one user hitting their own cap stops only their own scans.
  Threaded `ScanPlan.user_id` → `advance_scan`/`run_scan` → the ARQ worker's `run_scan` job.
  **Follow-up landed (2026-09-02):** `nimble_transport.post_json_via_nimble` now takes a
  `scan_id` kwarg folded into the `FetchRequest`; `CollectionApiClient`/`FollowsApiClient`/
  `SupportersApiClient` thread it from `fetch_page`/`iter_supporters` through to the transport,
  and `crawl_fan_collection`'s collection/wishlist/follows pagination plus `crawl_album`/
  `crawl_track`'s supporters pagination now pass their `scan_id`. The cap no longer undercounts
  collection-heavy scans. See `CLAUDE.md` "Immediate next steps" #2. PR: see git history.
  **Superseded (2026-09-02, Roy's own request):** both this per-user cap and the original global
  `crawl_max_requests` are gone, replaced by a single per-scan budget
  (`crawl_max_requests_per_scan`, default 1000) — simpler, and it's what Roy actually wanted:
  every scan starts at zero and never inherits spend from another scan or user. Also dropped
  level-3 crawling (`crawl_max_depth` default 3→2) in the same change, spending the freed budget
  on more rounds of level-2 paging instead. See `CLAUDE.md`'s crawl depth/budget bullet.

- [x] **A secondary budget cap** — max total frontier size, or max fetches per run, on top of
  the depth bound. Depth 3 on a popular album still fans out very wide. Same source.
  Done: `Settings.crawl_max_frontier_size` (default `None` = unbounded, unchanged behavior) caps
  each scan's TOTAL frontier rows (any status) in `frontier.enqueue`, the single choke point every
  fan-out path (live crawl, cross-scan replay) already goes through — no threading needed
  elsewhere. PR: see git history.

- [x] **Retire the legacy operator crawl chain.** `seed_crawl` / `crawl_next` /
  `scripts/crawl.py` still key off the single global `BANDCAMP_FAN_URL`. Documented as
  operator-only, which is a comment, not a guard rail. Same source.
  Done (relabel, not delete — the chain is still the manual/dev-smoke-test path,
  just no longer usable by accident): new `Settings.enable_operator_crawl` (default
  `False`). `app.worker.seed_crawl` raises `RuntimeError` and `scripts/crawl.py`'s
  `seed`/`run` commands print a refusal and exit 2 unless it's set. `crawl_next` and
  `run_scan` (the per-user path) are untouched — only the two entry points that seed
  from the global `BANDCAMP_FAN_URL` are gated. Documented in `.env.example`. PR: see
  git history.

- [x] **"Clear all filters" when several are stacked.** *(proposed by the hourly routine,
  2026-09-02)* `useFeedFilters.reset()` already exists and clears every filter, but nothing in
  the UI calls it — `ActivePills` (`FilterBar.tsx`) only offers removing genre/contains/artist
  pills one at a time, so backing out of a few stacked filters means clicking several `×`
  buttons. Add a "Clear all" button in `ActivePills`, shown once 2+ filter facets are active,
  wired to the existing `filters.reset()`. Verify: a component test with tags + contains + a
  label all set clicks "Clear all" and asserts the URL/filter state comes back empty — no
  visual check needed. Architect/QA: sound, testable, smallest of the three — do this one
  first.
  Done same run: `ActivePills` counts *facets* (a genre-tag group, a contains group, the artist
  filter), not individual pills, so three tags plus an artist is 2 facets, not 4 — the button
  shows once that count reaches 2. Calls the existing `filters.reset()` directly, so it also
  clears item type/sort along with the pills — that's `reset()`'s documented job, not a new
  behavior. Covered by a new test: tags + contains + a label all set, "Clear all filters"
  clicked, asserts every pill is gone and the item-type segment reads "All" again. PR: see git
  history.

- [x] **Undo affordance after like/block.** *(proposed by the hourly routine, 2026-09-02)*
  Like/block are one click and instant, and the feed is dense (`content-visibility: auto`
  cards), so a mis-click means digging into the Liked/Blocked panel to reverse it rather than
  just undoing.
  Done: `ScanFeedPage.tsx`'s `retire()` now captures the row's index in `rows` at the moment it's
  removed (inside the `setRows` updater, so it's never stale) and hands it to a new `armUndo()`,
  which puts up one `{ rec, kind, index }` in `undo` state and a `UNDO_WINDOW_MS` (6s, new in
  `config.ts`) timer that clears it. A new `.banner.undo` (♥/⊘ icon, message, an "Undo" `.btn
  ghost`) renders whenever `undo` is set — one at a time, a second like/block replaces whatever
  was already up. Its handler, `undoRetire()`, calls `api.unlike`/`api.unblock` directly (never
  the panel's `unlike`/`unblock`, which call `loadFirstPage()`) and splices the retired `rec`
  back into local `rows` at its captured index — per the Architect/QA scoping note, refetching
  page 1 to bring back one card would have reset pagination/scroll for every other row already on
  screen. The undo banner is dropped (and its timer cleared) on every `scanId` change, since it'd
  otherwise point at a different scan's card once the reader navigates to another scan through
  the same `/scans/:scanId` route element. Covered by three new tests in `feed.test.tsx`: undo
  after a like restores the card with zero extra `/api/recommendations` fetches and confirms
  `/api/likes/unlike` was called; undo after a block; the banner auto-dismisses once
  `UNDO_WINDOW_MS` elapses with nothing clicked. 38/38 frontend tests pass, tsc/lint/build clean
  (route chunk split intact). PR: see git history.

- [x] **Focus moves to the page heading on route change.** *(proposed by the hourly routine,
  2026-09-02)* `frontend/CLAUDE.md` already flags this gap ("Absent... revisit if nav grows") and
  nav has grown since (auth → scans list → feed → in-page panels) — a keyboard/screen-reader user
  navigating between them keeps focus wherever it was, often on an element that's no longer in
  the DOM.
  Done: both page headings (`ScanListPage`'s `.eyebrow` "Your scans" and `ScanFeedPage`'s
  `.scantitle`) got `tabIndex={-1}` plus a ref, and a `useEffect` that calls `.focus()` on it —
  mount-only for the list page (it's the same component instance for the whole route), keyed on
  `scanId` for the feed page since `/scans/:scanId` is one route element that React Router does
  NOT remount when navigating between two different scans' feeds. `:focus-visible` (not `:focus`)
  is the only outline rule in `base.css`, so the programmatic focus stays invisible for a
  mouse-driven route change and visible for a keyboard one — no new CSS needed. Covered by a new
  `focus on route change` test in `feed.test.tsx`: lands on `/scans`, asserts the list heading has
  focus, clicks into a scan (asserts the feed heading gets focus), clicks "← Scans" back (asserts
  the list heading gets focus again) — a real `MemoryRouter` navigation each way, not just two
  independent mounts. 35/35 frontend tests pass, tsc/lint/build clean (chunk split intact). PR:
  see git history.

- [x] **Keyboard shortcuts for like/block on a focused card.** *(proposed by the hourly routine,
  2026-09-02)* Triaging recommendations is mouse-only right now, which is slow and doesn't match
  the "focus moves to heading" accessibility work already landed.
  Done: `FeedCard.tsx` gets a single `onKeyDown` listener on the `<article>` — any focused element
  inside the card (a tag chip, the band button, the action buttons themselves) already bubbles
  its keydown up there, so no extra `tabIndex`/focus wiring was needed. `l` likes, `b` blocks
  (only when `rec.band_id !== null`, matching the block button's own existence check); a held
  modifier key (ctrl/meta/alt) is left alone so OS/browser shortcuts aren't hijacked, and `busy`
  gates it the same way it already disables the click handlers. `aria-keyshortcuts="l"`/`"b"` on
  the two action buttons for discoverability. Covered by five new tests in the new
  `FeedCard.test.tsx` (a standalone RTL render, no full-app/API mocking needed since `FeedCard`
  has no router/api dependency of its own): `l` calls `onLike` with the card's rec regardless of
  which element inside the card has focus; same for `b`/`onBlock`; busy suppresses it; a held
  modifier key suppresses it; a card with no band offers no block shortcut and swallows `b`.
  43/43 frontend tests pass, tsc/lint/build clean (chunk split intact).
  Two other Product proposals from this round were cut before building: a "guard double-submit on
  Recompute" idea (there's no manual Recompute button in the UI to guard — recomputes are
  automatic, server-side, after each crawl slice) and an "explicit empty state for zero-match
  filters" idea (already implemented verbatim in `ScanFeedPage.tsx`'s `<p className="empty">`
  block). PR: see git history.

- [x] **Keyboard-navigable dropdown menus.** *(proposed by the hourly routine, 2026-09-02)*
  `Dropdown.tsx` (used for Sort/Genre/Contains in `FilterBar.tsx`) opens on click but once open,
  arrow keys did nothing — Tab-through-every-row or the mouse were the only ways to move, which
  reads as dated next to any modern `<select>`/combobox.
  Done: `Dropdown.tsx` gets one `onKeyDown` on the `.ddpanel` div (the WAI-ARIA menu-button
  pattern's core behavior) — ArrowDown/ArrowUp move focus to the next/previous `.ddrow` button and
  wrap at the ends, Home/End jump to the first/last row. Scoped to fire only when the event
  target already has the `.ddrow` class (checked before anything else): the Genre/Contains panels
  also hold a text input, and hijacking Home/End there would have broken normal cursor movement
  inside it. No changes needed in `FilterBar.tsx` — generic behavior at the `Dropdown` level,
  since every panel already renders its selectable rows with that class. Covered by four new
  tests in the new `Dropdown.test.tsx` (a standalone RTL render, `Dropdown` has no router/api
  dependency): ArrowDown steps through three rows and wraps past the last; ArrowUp steps backward
  and wraps past the first; Home/End jump to the first/last row; a focused search input inside
  the panel is left alone by ArrowDown/Home (the input keeps focus, no row hijack). 47/47 frontend
  tests pass, tsc/lint/build clean (chunk split intact). One Architect+QA-approved companion
  proposal from the same Product round was NOT built this task (routine hit its per-run task cap)
  and is queued below: validating seed URLs before they're added to a new scan.

- [x] **Validate seed URLs before they're added.** *(proposed by the hourly routine, 2026-09-02,
  Architect+QA-approved)* `NewScanForm.addSeed()` accepted any non-empty string — typos or
  non-Bandcamp links sat silently in the seed list until the backend rejected the whole scan on
  submit.
  Done: added `SEED_URL_RE` in `NewScanForm.tsx`, deliberately mirroring the backend's own
  acceptance shape — `app.crawl.scan_service._SEED_RE`
  (`^(https?://[^/]+/(album|track)/[^/?#]+)`, any host, no bandcamp.com check) — rather than a
  stricter, invented pattern, per the QA caveat. `addSeed()` now rejects anything that doesn't
  match, showing the existing `role="alert"` error styling instead of adding it to the seed list;
  a subsequent valid add clears the error. Covered by five new tests in
  `NewScanForm.test.tsx` (a standalone RTL render, no router/api mocking needed since
  `addSeed()`/validation has no dependency on either): a non-URL string is rejected with an
  alert and nothing added; a well-formed but non-album/track path (`/merch/...`) is rejected the
  same way; a valid `/album/...` URL is added with no alert; a valid `/track/...` URL is added
  and clears an earlier error; an invalid URL submitted via Enter (not the Add button) is
  rejected too. 52/52 frontend tests pass, tsc/lint/build clean (chunk split intact). PR: see git
  history.

- [x] **"Clear filters" button inside the zero-result empty state.** *(proposed by the hourly
  routine, 2026-09-02, Architect+QA-approved)* When active filters return zero rows, the empty
  state (`ScanFeedPage.tsx`, around the "Nothing matches these filters" message) is just text —
  no button. The existing "Clear all filters" control in `ActivePills` (`FilterBar.tsx`) only
  renders once 2+ filter facets are active, so a single active filter has no clear-action
  anywhere on screen.
  Done: added a `btn ghost` "Clear filters" button next to the empty-state message, shown only
  when `filters.anyActive` (mirroring the existing cold-start-panel branch's condition) and
  wired to the existing `filters.reset()` — no new state or styling. Covered by a new test in
  `feed.test.tsx`: opening `/scans/1?tag=psybient` against a mock returning zero recommendations
  shows the empty-filtered message and the button; clicking it clears `tag=` from the URL. 71/71
  frontend tests pass, tsc/lint/build clean (chunk split intact). PR: see git history.

- [x] **`useDocumentTitle` hook.** *(proposed by the hourly routine, 2026-09-02,
  Architect+QA-approved)* `document.title` is hardcoded to "crate digger" in `index.html` and
  never updated, so every route/scan looks identical in the tab bar and browser history.
  Done: new `lib/useDocumentTitle.ts` — a single effect that sets `document.title` to
  `<title> · crate digger` (new `APP_NAME` constant in `config.ts`) whenever its `title` argument
  is truthy, and leaves the previous title alone while it's `null`/`undefined` (a page's real
  title, like a scan's name, is often only known after a fetch resolves — this avoids a flash of
  bare "crate digger" in between). Wired into `ScanListPage` (`useDocumentTitle('Scans')`) and
  `ScanFeedPage` (`useDocumentTitle(scan?.name)`). Covered by three standalone hook tests in
  `useDocumentTitle.test.ts` (`renderHook`: sets the suffixed title; updates on a changed
  argument; holds the previous title while the argument is null) and one integration test in
  `feed.test.tsx` ("document title" describe block, mirroring the existing "focus on route
  change" test's `combinedRoutes`/navigation shape): landing on `/scans` shows "Scans · crate
  digger", clicking into a scan shows "My collection · crate digger", navigating back updates it
  again. 74/74 frontend tests pass, tsc/lint/build clean (chunk split intact — the hook lands in
  its own small shared chunk between the two lazy routes). PR: see git history.

- [x] **Toast/notification primitive.** *(proposed by the hourly routine, 2026-09-02,
  Architect+QA: sound but flagged as two sittings' worth)* There was no shared toast/notification
  primitive anywhere in the frontend — every screen invented its own inline `role="alert"`, and
  `CopyLinkButton.tsx`'s clipboard-rejection catch block swallowed failure with no user feedback
  at all (a denied-permission click looked like nothing happened).
  Done, built as one item rather than QA's suggested (a)/(b) split: a primitive with no caller
  wired in would have been a half-finished component sitting unused in the tree, and the wiring
  turned out to be a two-line addition once the primitive existed, so splitting it would only
  have deferred that trivial half to a second task for no real risk reduction.
  `lib/toast.ts` — a module-scope `{id, message, variant}` queue behind `useSyncExternalStore`
  (not `useState` mirroring, per QA's leakage caveat: a toast can be raised from any event
  handler, not just one with a toast-owning component in its own render tree). `showToast(message,
  variant?, durationMs?)` is the imperative entry point (no hook, callable from anywhere);
  `dismissToast(id)` removes one and no-ops if it's already gone (an auto-dismiss timer and a
  manual dismiss can race). New `components/ToastStack.tsx`, mounted once in `App.tsx` next to
  `AppHeader` (signed-in shell only — the only current caller, `CopyLinkButton`, only renders
  there), subscribes via `useToasts()` and renders each queued toast with `role={variant}`
  (`'alert'` vs `'status'`, so a failure interrupts a screen reader the way `.err` elements
  already do elsewhere, per `frontend/CLAUDE.md`'s "errors get `role=alert`" rule) plus a dismiss
  button. New `TOAST_DURATION_MS` (4000) in `config.ts`. `CopyLinkButton.tsx`'s clipboard-rejection
  catch now calls `showToast(..., 'alert')` instead of a bare silent return.
  Testing hit one real cross-test leak worth recording: the queue's module scope means a toast
  raised by a test that never even rendered `<ToastStack>` still sits in it afterward, and a
  test that triggers one under real timers (no `vi.useFakeTimers()`) leaves a *real* pending
  dismiss timeout that a later fake-timer test's `advanceTimersByTimeAsync` cannot touch — exactly
  the kind of leakage QA flagged, just across tests rather than across mounts. Fixed with an
  exported test-only `resetToastsForTests()`, called from `beforeEach` in every test file that
  exercises `showToast`. Covered by `ToastStack.test.tsx` (renders nothing on an empty queue;
  shows a status toast and auto-dismisses it after `TOAST_DURATION_MS`; an alert-variant toast
  gets `role="alert"` instead of `"status"`; two toasts stack and dismiss independently) and a
  new `CopyLinkButton.test.tsx` case (a rejected clipboard write now raises an `alert`-role toast
  with the failure message, which itself auto-dismisses). 76/76 frontend tests pass (stable
  across repeated runs), tsc/lint/build clean (the new files land in the eagerly-loaded shared
  chunk via `App.tsx`, not a lazy route chunk — expected, since `ToastStack` must be mounted
  before either route is). PR: see git history.

- [x] **Live-updating relative timestamps.** *(proposed by the hourly routine, 2026-09-02,
  Architect+QA-approved)* Scan cards show `ago(scan.last_run_at)` ("3m ago"), but the text only
  updates when something else forces a re-render — `ScanListPage`'s poll stops once every scan is
  `done`, so a tab left open on a finished scan list silently goes stale.
  Done: new `components/RelativeTime.tsx` — owns its own `window.setInterval`
  (`RELATIVE_TIME_REFRESH_MS`, 30s, new in `config.ts`), effect-scoped per rule 7 in
  `frontend/CLAUDE.md` (closure `id`, not a ref, so StrictMode's double-invoke can't leak the
  first timer). Renders `ago(iso)`; no timer at all for a `null` iso, since there's nothing to
  advance. Swapped in for the one call site, `ScanListPage.tsx`'s `{ago(scan.last_run_at)}` →
  `<RelativeTime iso={scan.last_run_at} />`. Covered by four new tests in
  `RelativeTime.test.tsx` (standalone RTL render, no router/api mocking needed): text advances
  from "just now" to "1m ago" after `RELATIVE_TIME_REFRESH_MS` of fake-timer advance with no prop
  change or remount; a `null` iso starts no interval and renders nothing; unmount clears the
  interval; the boundary crossing lands exactly on `RELATIVE_TIME_REFRESH_MS`, not some other
  cadence. 84/84 frontend tests pass, tsc/lint/build clean (chunk split intact — the component
  lands inside the `ScanListPage` chunk, its only importer). PR: see git history.

- [x] **Pending-state microcopy on like/block.** *(proposed by the hourly routine, 2026-09-02,
  Architect+QA-approved with one caveat)* `FeedCard`'s like/block buttons went `disabled` while
  busy but kept the same label ("♥ like"), so a click read as unresponsive for roughly
  `CARD_EXIT_MS` before the card animated out.
  Done, addressing QA's caveat first: `ScanFeedPage.tsx`'s `busyKeys: Set<string>` (a single
  boolean per card) became `busy: Record<string, 'like' | 'block'>`, mirroring the existing
  `exiting` state's per-key/per-action shape — `markBusy(key, action)` now takes the action
  (`'like' | 'block' | null`) instead of a boolean, so a card can distinguish which button is
  in flight. `FeedCard`'s `busy: boolean` prop became `busyAction: 'like' | 'block' | null`;
  both buttons still disable on any in-flight action (`busy = busyAction !== null`), but only
  the acting one swaps its label — like button reads "Liking…" only when `busyAction === 'like'`,
  block reads "Blocking…" only when `busyAction === 'block'`, so a like in flight doesn't also
  relabel the (still-disabled) block button. Covered by four new tests in
  `FeedCard.test.tsx`'s "pending-state microcopy" block: plain labels when nothing is busy; only
  the like button relabels (and the block label is untouched) while a like is in flight, and
  vice versa; both buttons are disabled while either action is in flight. 88/88 frontend tests
  pass, tsc/lint/build clean (chunk split intact). PR: see git history.

- [x] **"Back to top" affordance for long feeds.** *(proposed by the hourly routine, 2026-09-02,
  Architect+QA-approved)* The feed grows to hundreds of rows via "load more," but there's no fast
  way back to the filter bar/top once scrolled deep.
  Done: new `components/ScrollTopButton.tsx` — a `useState` initialized from `window.scrollY`
  (so a mount deep in an already-scrolled page shows correctly, not just after the next scroll
  event) plus a passive `scroll` listener toggling visibility past `SCROLL_TOP_THRESHOLD_PX`
  (600, new in `config.ts`). Renders `null` below the threshold rather than hiding via CSS, so
  it's never a focusable-but-invisible control. Icon-only (`↑`, `aria-hidden`) with an
  `aria-label="Back to top"` per the icon-only-controls rule in `frontend/CLAUDE.md`'s UI/UX
  section. Wired into `ScanFeedPage.tsx` next to `ShortcutsHelp`; its `onClick` is a new
  `scrollToTop` callback that calls `window.scrollTo({top:0, behavior:'smooth'})` then
  `headingRef.current?.focus()` — the same heading ref the existing focus-on-route-change effect
  already uses, so clicking it reads as the same kind of navigation. Covered by four standalone
  tests in `ScrollTopButton.test.tsx` (absent below threshold, appears above it, disappears again
  on scrolling back up, calls `onClick`) and one integration test in `feed.test.tsx`
  ("scroll-to-top button" describe block): scrolling a real rendered feed past the threshold,
  clicking the button, and asserting both the `scrollTo` call and that the page heading receives
  focus. 85/85 frontend tests pass, tsc/lint/build clean (chunk split intact — the component
  lands inside the `ScanFeedPage` chunk, its only importer). PR: see git history.

- [x] **Conditional GET (ETag) on `/api/recommendations` and `/api/facets`.** *(proposed by the
  hourly routine, 2026-09-02, Architect+QA-approved with a correction)* Every feed poll re-transfers
  the full payload even when nothing changed.
  Done: `ETag: "gen-{scan_id}-{generation}"` (quoted per the HTTP ETag grammar; `{scan_id}` is the
  literal string `none` for a brand-new user with no scan yet) on both responses, computed by a new
  `_scan_generation()`/`_generation_etag()` pair in `app/api/feed.py` that reuses
  `scans.recompute_generation` — no new state, per QA's correction that generation is per-scan, not
  global. A matching `If-None-Match` short-circuits to a real `304` with an empty body (returning a
  raw `Response(status_code=304, ...)`, which FastAPI passes through unvalidated even though the
  route declares a `response_model` — returning `[]`/`{}` instead would have serialized to a
  non-empty JSON body, which a `304` must not carry). For `/recommendations` specifically, the
  generation is computed *before* the filtered/joined main query runs, so a cache hit skips that
  query entirely rather than only skipping re-serialization — the actual point of the
  optimization. `/facets`'s `seed_tags` facet (the caller's own album tags) isn't strictly tied to
  `recompute_generation` and could in theory go stale without a recompute — noted in a comment,
  accepted as the same scope this scan's other read endpoints already share, not worth a second
  cache key for. Covered by `test_recommendations_etag_conditional_get` and
  `test_facets_etag_conditional_get`: first GET returns a non-empty ETag; replaying it via
  `If-None-Match` gets `304` with `r.content == b""`; a recompute in between changes the ETag and
  makes the stale `If-None-Match` return a fresh `200` instead. 241/241 backend tests pass (239 +
  2 new), ruff clean. PR: see git history.

- [x] **`POST /api/blacklist` silently no-ops on a past `expires_at`.** *(found by the hourly
  routine, 2026-09-02, Product read the actual endpoint code rather than brainstorming —
  Architect+QA-approved)* `BlockIn.expires_at` had no lower-bound check. A past `expires_at` (a
  date-picker typo, a client bug) created a row and returned a normal-looking `200`, but both
  `list_blocked` and the curation exclusion query filter on `expires_at > now()` — so the band was
  never actually excluded from recs and never showed up as blocked either. The caller believes
  they blocked something; nothing happened, no error anywhere.
  Done: `BlockIn` gets a `model_validator(mode="after")` (matching `LikeIn`'s existing pattern in
  `likes.py`) rejecting a non-null `expires_at` that isn't strictly in the future — a naive
  datetime (no tzinfo) is treated as UTC before comparing, so a bare `"2020-01-01T00:00:00"` is
  still caught, not silently accepted as some other timezone's future. Pydantic turns the
  `ValueError` into FastAPI's standard `422`, same as `LikeIn`'s existing one-of-album/track
  validator. Covered by `test_block_rejects_past_expires_at`: posting a 2020 `expires_at` returns
  `422` and confirms no row appears in `GET /api/blacklist` afterward — the existing
  `test_block_with_expiry_round_trips` (a real future date) is untouched and still passes.
  242/242 backend tests pass (241 + 1 new), ruff clean. PR: see git history.

- [x] **`POST /api/scans` seed list has no size cap.** *(proposed by the hourly routine,
  2026-09-02, Architect+QA-approved)* `scan_service.create_scan` takes `urls: list[str]` and
  inserts one `ScanSeed` row per de-duped URL with no upper bound — the same class of problem
  `Settings.crawl_max_frontier_size` was added to solve for frontier growth *during* a crawl (see
  CLAUDE.md "Immediate next steps" #1), but that cap doesn't cover the initial seed batch, which
  lands straight in `ScanSeed` before crawling even starts. Add `Settings.max_scan_seeds` (default
  e.g. 500), checked in `create_scan`, raising `ValueError` → the existing 400 handler in
  `scans.py`. Verify: `pytest` — posting 501 seed URLs to `POST /api/scans` returns `400`; posting
  500 still succeeds.
  Done: `Settings.max_scan_seeds` (default 500). `create_scan` gained a keyword-only `max_seeds`
  param, defaulting to `get_settings().max_scan_seeds` when omitted — same "default param falls
  back to settings, tests override explicitly" shape as `frontier.enqueue`'s
  `max_frontier_size`. The check runs after de-duplication (a scan with 501 URLs where one repeats
  should still pass at 500 distinct seeds), raising `ValueError` which the existing `scans.py`
  handler already turns into `400`. Covered by `test_create_scan_seed_cap`: 501 distinct seed URLs
  → `400` with "too many seed" in the detail message; the same list trimmed to exactly 500 → `201`
  with `seed_count == 500`. 243/243 backend tests pass (242 + 1 new), ruff clean. PR: see git
  history.

- [x] **Per-user rate limit on `POST /api/recommendations/recompute`.** *(proposed by the hourly
  routine, 2026-09-02, Architect+QA-approved)* `app/api/feed.py`'s recompute endpoint does a full
  unowned-catalog scoring pass with zero throttling today — confirmed live gap, not speculative.
  No UI button calls it yet (recomputes are automatic, server-side, after each crawl slice), so
  this guards scripted/direct callers, not a user-facing bug.
  Done: new `Settings.recompute_cooldown_seconds` (default `0` = disabled, unchanged behavior —
  same "off by default, an operator opts in via env" convention as
  `crawl_max_requests_per_user`/`crawl_max_frontier_size` above). Chose default-off deliberately
  after finding several existing tests call recompute twice in the same test with no delay between
  calls (e.g. `test_like_removes_and_excludes_then_unlike`'s like → recompute → unlike → recompute
  round trip) — a nonzero default would have broken them, and weakening those tests to work around
  a new feature would be backwards. When enabled, `app/api/feed.py` tracks `_last_recompute_at`
  per user id (a module-scope in-memory dict — this is scripted-caller hardening, not something
  that needs to survive a restart) and rejects a call inside the cooldown window with `429` + a
  `Retry-After` header
  (seconds remaining, rounded up). The timestamp is recorded *before* `curate()` runs, so two
  rapid calls can't both slip past the check while the first is still in flight. Time comes from a
  small `_now()` helper (not an inline `datetime.now(UTC)`) specifically so tests can monkeypatch
  it. Covered by `test_recompute_no_cooldown_by_default` (two back-to-back calls both succeed,
  documenting the default) and `test_recompute_rate_limited_when_cooldown_enabled` (overrides
  `get_settings` to `recompute_cooldown_seconds=30`, monkeypatches `_now`: first call 200, an
  immediate second call 429 with a positive `Retry-After`, then advancing the mocked clock past
  the window makes a third call succeed again). A `_reset_recompute_cooldown_for_tests()` helper
  clears the module-scope dict — needed because pytest's fresh-sqlite-per-test fixture reassigns
  user id 1 in nearly every test, so a leftover timestamp from an earlier test could otherwise leak
  into this one, the same class of cross-test leakage the frontend toast primitive hit earlier this
  cycle. 239/239 backend tests pass (237 + 2 new), ruff clean. PR: see git history.

- [x] **"Copy feed as Markdown" export.** *(proposed by the hourly routine, 2026-09-02,
  Architect+QA-approved — confirmed `Recommendation.url` exists end-to-end so no link needs
  deriving, with the caveat that a `null` url must not fabricate one)* Users who want to share or
  paste their current filtered feed (e.g. into Discord/notes) had no way out except manually
  retyping band/track names.
  Done: new `lib/markdown.ts` — `recsToMarkdown(recs)`, a pure formatter: `- [Band – Title](url)`
  per row, falling back to whichever of `title`/`band_name` is present (`'Untitled'` if neither),
  and — the QA caveat — a row with a `null` `url` (the discover-by-id convention) renders as plain
  `- label` text rather than a fabricated link. `[`/`]` in a label are backslash-escaped so an
  in-title bracket can't break the Markdown link syntax. New `components/CopyMarkdownButton.tsx`
  mirrors `CopyLinkButton`'s clipboard-write + toast-on-failure pattern exactly (same
  `COPY_LINK_FEEDBACK_MS` "Copied" reversion, same `showToast(..., 'alert')` on a rejected write)
  and is `disabled` when there are no rows to export. Wired into `FilterBar.tsx` next to
  `CopyLinkButton`, which needed a new `rows: Recommendation[]` prop threaded from
  `ScanFeedPage.tsx`'s existing `rows` state (the currently loaded/filtered page, not a re-fetch of
  the full feed). Covered by 6 new tests in `markdown.test.ts` (band+title link, multi-row
  newline-joining, null-url omits the link, title-only/band-only/neither fallback, bracket
  escaping, empty list) and 4 in `CopyMarkdownButton.test.tsx` (copies the formatted text; disabled
  on an empty row list; "Copied" reverts after the feedback window; a rejected write raises a toast
  and leaves the button unchanged). 106/106 frontend tests pass, tsc/lint/build clean (chunk split
  intact — lands inside the `ScanFeedPage` chunk, its only importer). PR: see git history.

- [x] **Unlike/unblock from the side panels have no re-entry guard or error handling.**
  *(found by the hourly routine, 2026-09-02, Option C round 4 — Architect+QA-approved)* Every
  other mutation in `ScanFeedPage.tsx` (`like`, `block`, `undoRetire`) uses an `inFlight` ref
  guard and a try/catch → `setError(...)` on failure — this round's pending-state-microcopy item
  even added visible busy labels for `like`/`block`. `unlike`/`unblock` (called from the
  Liked/Blocked side panels) were bare `async function`s with neither: a fast double-click could
  fire the request twice, and a failed request was a silently swallowed unhandled rejection with
  zero user feedback.
  Done: `unlike`/`unblock` now follow the exact same shape as `like`/`block` — an `inFlight.
  current.has(key)` guard, `setError(...)` in a catch block, and a new `panelBusy: Record<string,
  true>` state (kept separate from `busy`, since a panel row's identity — a liked item's id, a
  blocked band's id — isn't a feed-card key; new `likedKeyOf`/`blockedKeyOf` module-scope
  helpers). Per QA's scope-trap warning, the side panels (`SidePanels.tsx`) hold no state of
  their own — `LikedPanel`/`BlockedPanel` gained a `busy: (item) => boolean` prop that's a pure
  lookup into `ScanFeedPage`'s single source of truth, so a busy row disables its button and
  swaps the label to "Unliking…"/"Unblocking…" without inventing a second local busy-tracking
  mechanism. Covered by three new tests in `feed.test.tsx`'s "unlike/unblock from the side
  panels" block: the busy label appears and disables the row while an unlike is held behind an
  unresolved promise, then clears once it resolves; a rejected unblock surfaces a `role="alert"`
  error and leaves the row usable again (not stuck busy); two rapid clicks on the same row call
  the API exactly once. 91/91 frontend tests pass, tsc/lint/build clean. PR: see git history.

- [x] **Optimistic like/block, with rollback on failure.** *(proposed by the hourly routine,
  2026-09-02, Architect+QA-approved with a scoping caveat)* Like/block already awaited the
  network round trip *before* even starting the card's exit animation (`CARD_EXIT_MS`, 800ms),
  so every click felt laggy compared to a modern app — the wait was pure dead time, since the
  card was going to leave either way once the request succeeded.
  Done, scoped per QA's caveat (row removal/re-insertion only, facets/liked/blocked untouched on
  failure — those are only ever loaded after a *successful* call, so there's nothing on that side
  to roll back): `retire(rec, kind)` — previously called only after `await api.like/block()`
  resolved — is now called immediately on click, before that await, so the exit animation starts
  in the same tick as the click. `retire`'s exit-timer id is now tracked in a new `retireTimers`
  ref (keyed by card key), and the index a card was actually spliced out of `rows` at is recorded
  in a new `retiredIndex` ref once that timer fires (not read from `undo` state, which can be
  stale in a closure captured before `armUndo` ran). A new `cancelRetire(rec)`, called from
  `like`/`block`'s catch block, undoes the optimistic `retire()`: if the exit timer hasn't fired
  yet, it just clears the timer and the `exiting` CSS class — the row was never actually removed
  from `rows`; if the timer already fired (the row is gone and "Undo" may already be armed for
  it), it splices the row back in at its recorded index and drops that now-meaningless undo offer
  — the failure already reverted it, so there's nothing left to undo. Covered by three new tests
  in `feed.test.tsx`'s "optimistic like/block" block: a held-promise gate on the like request
  proves the exit animation's CSS class is applied synchronously on click, before the request
  resolves; a like that fails before `CARD_EXIT_MS` elapses restores the card and shows the
  error, and advancing past `CARD_EXIT_MS` afterward doesn't belatedly remove it (the timer was
  cancelled, not outrun); a block whose failure is deliberately held until *after* the exit timer
  already fired and armed Undo restores the card, shows the error, and clears the now-stale Undo
  button. 109/109 frontend tests pass, tsc/lint/build clean (chunk split intact). PR: see git
  history.

- [x] **Focus trap for the shortcuts-help panel.** *(proposed by the hourly routine, 2026-09-02,
  Architect+QA-approved)* `ShortcutsHelp.tsx` is a real `role="dialog" aria-modal` overlay that
  already restores focus to its trigger on close, but nothing stopped Tab/Shift+Tab from leaving
  the open dialog and landing on the page behind it — a keyboard user could tab straight out of a
  modal that's supposed to own focus while open.
  Done: the panel's existing `keydown` effect (already handling Escape) now also traps `Tab` —
  queries `panelRef`'s focusable descendants fresh on every press (a `FOCUSABLE_SELECTOR` constant,
  hoisted to module scope per rule 9) rather than caching the list once, per QA's note that the
  panel has exactly one focusable element today (the Close button) but a hardcoded version would
  silently stop working if a future row added a link or button. Tab from the last element (or from
  outside the tracked list, which covers the initial state where the panel div itself holds focus)
  wraps to the first; Shift+Tab from the first wraps to the last — today's single-button case
  degenerates to "Tab keeps focus on Close," which is the correct trap behavior for that case, not
  a bug. Covered by two new tests in `ShortcutsHelp.test.tsx`: Tab from the initially-focused panel
  lands on the Close button and a second Tab keeps it there; Shift+Tab does the same in reverse.
  111/111 frontend tests pass, tsc/lint/build clean (chunk split intact). PR: see git history.

- [x] **Skip-to-content link.** *(proposed by the hourly routine, 2026-09-02, Architect+QA-approved)*
  A keyboard/screen-reader user landing on any page had to tab through the whole header before
  reaching the actual content, every single page load. `frontend/CLAUDE.md`'s "Known conflicts and
  deferred items" flagged this as an acknowledged, deliberately-deferred gap ("revisit if nav
  grows") — the nav has grown since (shortcuts panel, roving tabindex, several keyboard-only
  affordances), so it was worth picking up.
  Done, per QA's scoping notes: one shared signed-in shell (`App.tsx`, wrapping `AppHeader` + the
  routed pages), so the skip link and its target landmark live there once, not per page.
  `App.tsx` now wraps `<Suspense><Routes>…</Routes></Suspense>` in `<main id="main-content">`, with
  a `<a className="sr-only" href="#main-content">Skip to content</a>` as the very first element in
  the signed-in tree, ahead of `<AppHeader />`. `ScanFeedPage`'s own inner `<main>` (which only ever
  mounted inside `{showFeed && …}`, so it couldn't have been the skip target on its own) is now a
  plain `<div>` — two nested `<main>` landmarks would have been invalid and confused assistive tech;
  `ScanListPage`'s `<div className="wrap">` was never a `<main>` to begin with, so it needed no
  change. New `.sr-only` utility in `base.css` (clip-based, not `display:none`, so it's still
  reachable in the tab order) that reveals itself — fixed position, padded, `var(--surface)`
  background — on `:focus`, reusable for future visually-hidden-until-focused content, not just this
  link. Covered by a new `skip to content` describe block in `feed.test.tsx`, mounting the real
  signed-in shell (same pattern as "focus on route change"/"document title"): the link renders with
  `href="#main-content"`, an element with that id exists and is a real `<main>`, and the link
  precedes the header (`role="banner"`) in DOM order — the third assertion is what actually proves
  it's reachable by a single Tab from page load, not merely present somewhere on the page. 110/110
  frontend tests pass, tsc/lint/build clean (chunk split intact). PR: see git history.

- [x] **Density toggle (comfortable/compact), persisted.** *(proposed by the hourly routine,
  2026-09-02, Architect+QA-approved — "smallest of the three, sound, trivially testable")* The feed
  is one fixed row height regardless of list length — someone with a big crawl scanning hundreds of
  recs has no way to see more per screen, a normal control in every "grown-up" list app (Gmail,
  Linear, Notion) whose absence made this feel unfinished by comparison. A sibling Product proposal
  from the same round, shared `Button`/`Badge` primitives to de-duplicate 8 hand-rolled `className=
  "btn ..."` call sites, was cut by Architect+QA on size (1.5-2 sittings, not one) — left unqueued
  since it wasn't concrete enough to pick up later without re-scoping.
  Done: `lib/density.ts` — pure `getDensity()`/`setDensity()` against a `crate-digger.density`
  localStorage key, `try`-wrapped the same way `api/client.ts`'s token storage is (private mode /
  storage-disabled browsers fall back to the `'comfortable'` default instead of throwing). New
  `lib/useDensity.ts` hook (`useState(() => getDensity())`, a real-work lazy init per rule 12 in
  `frontend/CLAUDE.md`) lives in `ScanFeedPage` — the one place that owns both the `.cardlist` wrapper
  the attribute lands on and the `FilterBar` the toggle button lives in, so no context/prop-drilling
  scheme was needed beyond passing `density`/`onToggleDensity` down one level. `FilterBar.tsx` gets a
  `btn ghost` toggle (`☰ Compact` / `☰ Comfortable`, `aria-pressed`) next to the Copy Link/Markdown
  buttons; `ScanFeedPage.tsx` sets `data-density={density}` on the `.cardlist` div. `feed.css` adds
  `[data-density='compact'] .card`/`.score` rules (tighter padding/margin/gap, a smaller score box) —
  pure CSS, no dependency, composes with the existing `content-visibility: auto` rule per rule 6 in
  the UI/UX guidelines. Covered by 4 new tests in `lib/density.test.ts` (defaults to comfortable when
  unset; round-trips a written value; falls back to comfortable on a corrupted stored value; both
  functions degrade to a silent no-op/default rather than throwing when `localStorage` itself throws,
  simulated via a `Storage.prototype` spy) and 2 new integration tests in `feed.test.tsx`'s "density
  toggle" block (clicking the toggle flips its own label/`aria-pressed`, the `.cardlist`'s
  `data-density` attribute, and the persisted `localStorage` value in the same assertion; a page load
  with `'compact'` already persisted starts in that state). 119/119 frontend tests pass, tsc/lint/build
  clean (chunk split intact — the new files land inside the `ScanFeedPage` chunk, their only
  importer). PR: see git history.

- [x] **Command palette (Cmd/Ctrl+K).** *(proposed by the hourly routine, 2026-09-02,
  Architect+QA-approved — "sound, testable entirely in jsdom/RTL, scope is contained because it
  explicitly reuses `ShortcutsHelp`'s existing focus-trap rather than building one")* Getting to
  Feed / Scans / Blacklist or triggering "New scan" / "Recompute" takes multiple clicks through nav —
  there's no fast path for the one person actually using this daily.
  **Scoped down on build**, from what QA sanity-checked: `NewScanForm` isn't a route (it's an
  inline toggle on `ScanListPage`) and there is no manual "Recompute" control anywhere in the UI
  (a previous round already confirmed recomputes are automatic, server-side) — so "navigate +
  the two mutating actions" turned out to describe actions that don't exist as standalone
  commands. Built as **navigation only**: jump straight to the scans list or to any scan by name,
  which is the real, currently-missing fast path (today that's several clicks through the list
  page every time).
  Done: `components/CommandPalette.tsx` is generic and prop-driven — `actions: CommandAction[]`
  (`{id, label, hint?, run}`) plus an `onOpen?` callback the caller uses to refresh whatever backs
  those actions — so the component itself needs no router/API mocking to test at all, only a
  callback spy. Reuses `ShortcutsHelp`'s exact focus-trap/restore-focus effect shape (the same
  module-scoped `FOCUSABLE_SELECTOR`, Escape/outside-click/Tab-trap logic) but not its "?"
  text-entry guard — Ctrl/Cmd+K isn't something anyone types into a field, so that guard doesn't
  apply here. Filtering is a substring match on `label` (case-insensitive); the highlighted row is
  an `activeIndex` moved by ArrowUp/Down (clamped, no wrap) rather than real DOM focus per row —
  standard command-palette UX (type continuously, arrow to pick) rather than `Dropdown`'s
  focus-per-row menu pattern. `App.tsx` wires it in next to `ToastStack` (only in the signed-in
  shell): a `useState<Scan[]>([])` + `useCallback`'d `loadScansForPalette` (stable identity is load-
  bearing — `onOpen` is a real effect dependency in `CommandPalette`, documented on the component
  — an inline arrow there would reset the search on every unrelated App re-render) fetches
  `api.listScans()` each time the palette opens; `paletteActions` is `[{Go to Scans}, ...scans
  mapped to per-scan jump actions]`.
  Caught one real accessibility bug before it shipped: the hint text (`"scan"`/`"your
  collection"`) rendered as a sibling `<span>` with no separator, so an option's accessible name
  concatenated straight into it — `"Psy digscan"` — because accessible-name computation ignores
  flex-layout spacing between text nodes. Fixed by marking the hint `aria-hidden`; the label alone
  is the option's name, matching how the rest of this app treats decorative/secondary text.
  Covered by 12 new tests in `CommandPalette.test.tsx` (a standalone RTL render, no router/api
  mocking needed): opens on Ctrl+K and Cmd+K, focuses the input, lists every action; calls
  `onOpen` on each open (not just the first); filters to matching labels and shows a "no matches"
  message for none; ArrowDown+Enter runs exactly the highlighted action (spy assertions) and
  ArrowDown doesn't run past the last row; a mouse click runs and closes; Escape closes and
  restores focus; outside-click closes, inside-click doesn't; a second Ctrl+K toggles closed;
  reopening resets the query/highlight. Plus 3 integration tests in `feed.test.tsx`'s new
  "command palette" block, mounting the real signed-in shell: Ctrl+K from the scans list shows
  "Go to Scans" and every real scan; typing narrows to one match and Enter navigates there
  (asserted via `currentLocation()`); a mouse click on a scan option navigates the same way.
  134/134 frontend tests pass, tsc/lint/build clean (lands in the eagerly-loaded shared chunk via
  `App.tsx`, same as `ToastStack` — not a lazy route chunk, which is correct since it must be
  mounted before either route is). PR: see git history.

- [x] **Successful clipboard copies are silent for screen-reader users.** *(proposed by the
  hourly routine, 2026-09-02, Architect+QA-approved — "1-line addition, testable in jsdom, trivially
  under an hour")* Clicking "Copy link" or "Copy as Markdown" only swapped the button's own text to
  "Copied" — a screen-reader user got no confirmation, while a *failed* copy already raised a proper
  `showToast(..., 'alert')`. The failure path was announced; the success path wasn't.
  Done: `CopyLinkButton.tsx`/`CopyMarkdownButton.tsx` now call `showToast('Link copied to
  clipboard.', 'status')` / `showToast('Feed copied as Markdown.', 'status')` right after
  `setCopied(true)` — the exact same toast infra the failure branch already used, just the other
  variant. Covered by one new test per component (`CopyLinkButton.test.tsx`,
  `CopyMarkdownButton.test.tsx`), mirroring the existing failure-toast test's shape: click the
  button, `findByRole('status')` has the expected text, advance past `TOAST_DURATION_MS` and
  confirm it's gone (so it doesn't leak into the next test via the module-scope toast queue).
  136/136 frontend tests pass, tsc/lint/build clean, chunk split intact. PR: see git history.

- [x] **Paste several seed URLs into a new scan at once.** *(proposed by the hourly routine,
  2026-09-02, Architect+QA-approved — "sound, `fireEvent.paste` testable in jsdom, small, one
  function")* `NewScanForm`'s seed field accepted one URL per Enter press, so seeding a scan from
  5-10 album/track links already copied meant paste-Enter, paste-Enter, repeated — a "tighter flow"
  gap when queuing a scan from a batch of open tabs.
  Done: `NewScanForm.tsx` gets an `onPaste` handler on the seed-url input. A single-line paste is
  left alone (`e.clipboardData.getData('text')` has no `\r`/`\n` → the handler returns without
  calling `preventDefault`, so it falls through to today's unchanged behavior — still requires
  Enter/Add, same as typing one in). A multi-line paste is `preventDefault()`'d, split into lines,
  each validated against the existing `SEED_URL_RE`, and added in one `setSeeds` call that dedupes
  against both the already-added seeds and duplicate lines within the same paste. A paste with zero
  valid lines shows the same `role="alert"` rejection message the single-URL path already uses,
  rather than silently doing nothing. Covered by 4 new tests in a new `NewScanForm multi-URL paste`
  block in `NewScanForm.test.tsx`: 3 valid lines + 1 garbage line yields exactly 3 seed-list items
  and no alert; an all-garbage paste shows the alert and adds nothing; a paste that repeats an
  already-added seed and repeats a line within itself still lands exactly 2 new distinct items; a
  single-line paste adds nothing on its own (proving the multi-line branch didn't grow to swallow
  the single-URL case too). 140/140 frontend tests pass, tsc/lint/build clean, chunk split intact.
  PR: see git history.

- [x] **`RemoveButton({ label, onClick })` — dedupe the `×` "remove" pattern.** *(proposed by the
  hourly routine, 2026-09-02, Architect+QA-approved — "mechanical dedup, not a new-behavior change;
  testable via `tsc` + one render test")* The smaller slice of an earlier-rejected "shared
  Button/Badge primitives" proposal (that one needed migrating 8 call sites and a visual pass — cut
  as too large for one sitting), scoped down to just the 3 sites that already share one exact
  pattern: `Pill`'s `.rm` button (`FilterBar.tsx`), `NewScanForm`'s seed-list `.rm` button, and the
  "Clear artist filter" `.rm` button (also `FilterBar.tsx`) — all three already pass an `aria-label`
  today, so this is a mechanical dedup, not new behavior. (`ToastStack`'s dismiss `×` is a distinct
  semantic — not in scope.) Idea: one `components/RemoveButton.tsx` with `aria-label` as a
  **required** prop (not optional), so a call site that forgets one fails `tsc`, not just an a11y
  audit; the three sites above switch to it. Verify: `tsc -b` refuses to compile a call site missing
  `aria-label` (a deliberate compile-error check, or at minimum confirm the type signature makes it
  impossible to omit); one render test per usage confirming the accessible name comes through
  unchanged. Not built this round — left queued behind the paste-multiple-URLs proposal above.
  Done: new `components/RemoveButton.tsx` — `{ label, onClick }`, `label` required (not optional),
  so a call site missing it fails `tsc` rather than only an a11y audit. Swapped in at all 3 sites:
  `FilterBar.tsx`'s `Pill` "remove filter" button, `FilterBar.tsx`'s "Clear artist filter" button,
  and `NewScanForm.tsx`'s seed-list remove button. No CSS changes needed — `.rm` styling in
  `base.css` is scoped by ancestor selector (`.fpill .rm`, `.seed .rm`), not the component itself.
  `ToastStack`'s dismiss `×` stayed untouched, per the proposal's own scoping (a distinct semantic).
  Covered by a new `RemoveButton.test.tsx` (accessible name renders, `onClick` fires); the existing
  per-site tests (`FilterBar`/`NewScanForm` coverage in `feed.test.tsx`/`NewScanForm.test.tsx`)
  already assert the same buttons by accessible name and needed no changes, confirming the swap was
  behavior-preserving. 141/141 frontend tests pass (140 + 1 new), tsc/lint/build clean — the shared
  component lands in its own small chunk (used by both lazy routes), route chunk split intact. PR:
  see git history.

- [x] **Quick filter over loaded cards.** *(proposed by the hourly routine, 2026-09-02,
  Architect+QA-approved)* Once you've paged in a few hundred recs, there's no way to jump straight
  to "that one album" — genre/contains filters narrow by tag, not by name, so finding a specific
  title or artist means scrolling. Add a text input to `FilterBar` that narrows the already-fetched
  `rows` client-side (title/`band_name` substring match, case-insensitive) — no API call, purely a
  view filter — with `/` focusing it, matching the existing `l`/`b`/Ctrl+K shortcut pattern. Verify:
  unit-test the pure `matchesQuery(rec, query)` helper (title match, band match, empty-query
  passthrough, case-insensitivity); RTL test that typing reduces the rendered `.card` count and that
  `/` moves `document.activeElement` to the input.
  Done same run (Option C step 5, built immediately after proposing): new `lib/quickFilter.ts` —
  pure `matchesQuery(rec, query)`, case-insensitive substring match against `title`/`band_name`, an
  empty/whitespace query matching everything. `ScanFeedPage.tsx` derives `visibleRows =
  useMemo(() => quickQuery.trim() ? rows.filter(...) : rows, [rows, quickQuery])` and renders that
  instead of `rows` for the card list — the roving-tabindex handler (ArrowUp/Down/Home/End) and
  `activeCardIndex` clamp now move over `visibleRows` too, since that's what's actually on screen;
  `rows` itself (and `total`, pagination, "Load more") is untouched, so the quick filter never
  touches the server-side result set. The input lives in `FilterBar.tsx` (`quickQuery`/
  `onQuickQueryChange`/`quickFilterRef` props, same "controlled value + parent-owned state" shape as
  `density`), with a new `.quickfilter` sizing rule in `feed.css` (the shared `.input` class is
  `width:100%`, so a fixed width was needed inside the flex `.controls` row). A document-level `/`
  listener in `ScanFeedPage` (mirroring `ShortcutsHelp`'s always-listening + `isTextEntryTarget`
  guard, duplicated locally per the codebase's existing convention — `CommandPalette`/
  `ShortcutsHelp` each already carry their own copy rather than a shared helper) focuses the input;
  `ShortcutsHelp`'s own list gained a `/` row. Query resets to empty on every `scanId` change, same
  as the `undo` banner, so it can't silently carry over to a different scan's feed. A distinct empty
  message (`No loaded cards match "…"`) covers the filtered-to-zero case, kept separate from the
  real "no recommendations"/"nothing matches these filters" states, which are about the server-side
  result set. Covered by 5 new tests in `quickFilter.test.ts` (title match, band match, no match,
  empty/whitespace query passthrough, null title/band tolerance) and 3 new integration tests in
  `feed.test.tsx`'s roving-tabindex block (reusing its existing three-card fixture): typing narrows
  the rendered `.card`/`article` count and shows the matching card; a query matching nothing shows
  the distinct empty message, not the real one; `/` moves `document.activeElement` to the input.
  149/149 frontend tests pass (141 + 8 new), tsc/lint/build clean, chunk split intact. PR: see git
  history.

- [x] **Bulk select + bulk block.** *(proposed by the hourly routine, 2026-09-02,
  Architect+QA-approved)* Clearing a run of obviously-irrelevant recs (a whole genre you don't want)
  means clicking "block" one card at a time, which feels tedious for something that's conceptually
  one action. Add a per-card checkbox (shown once "select mode" is toggled from the filter bar) and
  a floating bar — "N selected — Block / Cancel" — that calls the existing block handler once per
  selected key, reusing current optimistic-update/undo plumbing. QA confirmed the real `block(rec)`
  handler exists at `ScanFeedPage.tsx:710`. Verify: RTL test — check two cards, click "Block
  selected", assert the block handler/mock API was called exactly twice with the right ids and
  selection state clears after; a second test asserts the bulk bar renders nothing when the
  selection set is empty.
  Done: `FilterBar.tsx` gets a "☑ Select" / "✕ Cancel select" toggle (`selectMode`, same
  `aria-pressed` shape as the density toggle) next to it. `ScanFeedPage.tsx` owns `selected: Set<
  string>` (card keys, same namespace as `keyOf`) and `bulkBusy`; `FeedCard.tsx` renders a checkbox
  (only for a row with a band — mirrors the existing per-card block button's own band-id gate)
  when `selectMode` is on, controlled by a new `selected`/`onToggleSelect` prop pair. New
  `components/BulkActionBar.tsx` — a pure `{count, busy, onBlock, onCancel}` presentational
  component, renders nothing at `count === 0` — shows "N selected", "Cancel", "Block selected".
  `bulkBlock()` calls the exact existing `block(rec)` handler once per selected row (`Promise.all`)
  — same optimistic retire/undo/error handling as a single click — then clears the selection and
  exits select mode once every call has settled, regardless of individual outcome (`block` itself
  already reports a failure via `setError`). Selection resets on `scanId` change, same reasoning as
  the quick-filter query and undo banner.
  **Test-infra fix along the way:** `test/renderApp.tsx`'s `mockFetch` helper's inner `vi.fn` only
  declared an `input` param, so TypeScript inferred `fetchMock.mock.calls` as 1-tuples — any test
  needing to assert on a POST's method/body (this one needed to confirm exactly two distinct
  `band_id`s were blocked) had to cast. Added an unused `_init?: RequestInit` second param so the
  inferred call-tuple type is a real 2-tuple everywhere `mockFetch` is used, no cast needed.
  **RTL gotcha hit and worked around:** `getByText` matches an element's own direct text-node
  children only, not nested elements' text — so `<span><b>{count}</b> selected</span>` can't be
  matched by the combined string `"N selected"` (the `<b>`'s text is invisible to the span's own
  node-text). Assertions query the count and the literal word "selected" as two separate exact
  matches instead.
  Covered by 3 new tests in `BulkActionBar.test.tsx` (renders nothing at zero; shows the count and
  wires `onBlock`/`onCancel` to their buttons; busy disables both buttons and relabels Block), 4 new
  in `FeedCard.test.tsx`'s "bulk select" block (no checkbox outside select mode; an unchecked box in
  select mode for a card with a band; no box for a card with no band; the `selected` prop and
  `onToggleSelect` call), and 3 new integration tests in `feed.test.tsx` (no checkboxes/bar before
  select mode is on; selecting two of three cards and clicking "Block selected" posts exactly two
  `/api/blacklist` calls with the two selected `band_id`s and clears the selection/select mode after;
  "Cancel" clears the selection and confirms no block request was ever sent). 159/159 frontend tests
  pass (149 + 10 new), tsc/lint/build clean, chunk split intact. PR: see git history.

- [x] **"Seen" marker for opened Bandcamp links.** *(proposed by the hourly routine, 2026-09-02,
  Architect+QA-approved — same Product/Architect+QA round as the quick-filter and bulk-select
  proposals above)* Scrolling back through a long feed, you can't tell which recs you already
  clicked through to Bandcamp to check out, so you re-open ones you've already mentally dismissed.
  Record the card's key in `localStorage` (capped set, same try/catch pattern as the existing token
  storage in `api/client.ts`) when "Bandcamp ↗" is clicked; `FeedCard` reads that set and renders
  `data-visited="true"` + a small "seen" label when present.
  Done: new `lib/visited.ts` — `isVisited(key)`/`markVisited(key)` against a
  `crate-digger.visited` JSON array, `try`-wrapped the same way `lib/density.ts` is (private mode /
  storage-disabled browsers just see "nothing is seen" rather than throwing). Capped at a new
  `VISITED_CAP` (500, in `config.ts`) — the oldest key is evicted first once exceeded, so a
  long-lived account's entry can't grow without bound. `FeedCard.tsx` uses its existing `cardId`
  prop (already a stable per-item key, see `ScanFeedPage`'s `cardIdOf`) as the storage key directly
  — nothing extra to compute. A local `useState(() => isVisited(cardId))` (not a prop — only this
  one card's own click changes what it knows) drives both `data-visited` on the `<article>` and a
  new `.seen-tag` span next to the "Bandcamp ↗" link; the link's `onClick` calls `markVisited` and
  flips the state in the same handler, so the marker appears immediately, no reload needed. Reuses
  the already-AA-audited `--faint` token (see the earlier contrast-fix item) for the label's color
  since it renders against the same `--surface` card background that token was measured against.
  Covered by 4 new tests in `FeedCard.test.tsx`'s "seen marker" block (no marker for a
  never-opened card; clicking the link marks it immediately; a card id already in storage starts
  pre-marked; an unrelated stored id doesn't bleed onto a different card) and 7 in the new
  `visited.test.ts` (mark then read back; unrelated keys unaffected; marking twice doesn't
  duplicate; cap eviction drops the oldest; a corrupted stored value falls back to "not visited";
  both functions degrade silently rather than throwing when `localStorage` itself throws — 2 tests).
  Rebased onto main after the quick-filter/bulk-select/delete-scan items landed ahead of it; test
  counts below are against that base, not the original 152/152 noted when this was first built.
  Frontend suite passes in full post-rebase, tsc/lint/build clean, chunk split intact. PR: see git
  history.

- [x] **No way to delete a scan from the UI.** *(found by the hourly routine, 2026-09-02, via direct
  code audit — `api.deleteScan`/`DELETE /api/scans/{id}` already existed and worked, but nothing in
  the frontend ever called it: a mis-seeded or abandoned custom scan could only be removed by hand
  against the database)* Added `DeleteScanButton` (`components/DeleteScanButton.tsx`), wired into the
  feed page's nav bar next to the scan title. Renders nothing for the `collection` scan (the backend
  itself refuses to delete that one — this mirrors the rule instead of duplicating it). Two clicks,
  not a native `confirm()` (this app doesn't use those anywhere else): the first arms a "Confirm
  delete?" state that auto-reverts after 4s if never followed up; the second calls the API, toasts
  success, and navigates back to `/scans`; a failed delete toasts the server's error and leaves the
  scan in place. Verify: 5 new RTL tests in `feed.test.tsx`'s new "delete scan" block — no button on
  the collection scan; first click arms confirm and it reverts on its own after the window closes;
  "Cancel" reverts immediately and never calls the API; confirming calls `DELETE` and lands on
  `/scans`; a failed `DELETE` shows the error via `role="alert"` and leaves the scan/route in place.
  164/164 frontend tests pass (159 + 5 new), tsc/lint/build clean (chunk split intact — the button
  bundles into the existing `ScanFeedPage` chunk, its only importer). PR: see git history.

- [x] **Route like/block/undo failures through a toast with Retry, not a sticky inline error.**
  *(proposed by the hourly routine, 2026-09-03, Architect+QA-approved with one correction)* When
  `like`/`block`/`undoRetire` fail, `ScanFeedPage.tsx` drops a permanent `<p class="err">` at the
  top of the feed that only clears on a fresh fetch — inconsistent with copy-link/delete-scan,
  which already use the transient toast primitive (`lib/toast.ts`/`ToastStack.tsx`).
  Done, per QA's correction: `error`/`setError` is untouched everywhere else (`loadFirstPage`/
  `loadMore`/`unlike`/`unblock` all still use it) — only the `like`/`block`/`undoRetire` call sites
  moved to toasts. `Toast` gains an optional `action?: { label, onClick }`; `showToast` takes it as
  a 4th positional param (after `durationMs`, so every existing call site is untouched);
  `ToastStack` renders an inline button for it and dismisses the toast once `onClick` runs — CSS
  moves `.toast-dismiss`'s `margin-left: auto` onto the new `.toast-action` when present (`.toast-
  action + .toast-dismiss` zeroes it) so the pair sits flush right together instead of doubling the
  push. `undoRetire` (a plain function, not a `useCallback`) took the one real design wrinkle: by
  the time its catch block runs, `setUndo(null)` has already cleared `undo` state, so a naive
  `() => void undoRetire()` retry would immediately no-op against a stale `undo` read. Fixed by
  giving it an explicit `entry: typeof undo = undo` parameter — the normal call site still reads
  current state, but the failure's Retry action closes over the *same* `{rec, kind, index}` it was
  first called with and passes it straight back in, bypassing the state race entirely.
  `like`/`block` retry more simply — `onClick: () => void like(rec)` / `() => void block(rec)` —
  since both are stable `useCallback`s that already guard their own re-entry via `inFlight`.
  **Cross-test leak found and fixed along the way:** the toast queue is module-scope by design (the
  backlog's own toast-primitive entry above already documents this), and `feed.test.tsx` had never
  needed a `resetToastsForTests()` reset before — no test in that file raised one until now. Added
  a file-level `beforeEach(() => resetToastsForTests())`, the same fix `ToastStack.test.tsx`/
  `CopyLinkButton.test.tsx` already apply per-file.
  Covered by 2 new tests in `ToastStack.test.tsx` (an action button renders, runs its `onClick`,
  and dismisses the toast on click; no button renders when no action is given) and 1 new
  integration test in `feed.test.tsx`'s "optimistic like/block" block (a like that 500s once shows
  a Retry button; clicking it re-sends the like, which this time succeeds, and the card completes
  its optimistic retire) — the two pre-existing failure tests in that block needed no changes,
  since `findByText`/`getByText` matching the error message don't care whether it renders in the
  old inline paragraph or the new toast. 178/178 frontend tests pass (177 + 1 feed.test.tsx case +
  2 ToastStack.test.tsx cases), tsc/lint/build clean (chunk split intact). PR: see git history.

- [x] **Toast the user when a 401 mid-session logs them out.** *(proposed by the hourly routine,
  2026-09-03, Architect+QA-approved)* `AuthContext.tsx`'s `setUnauthorizedHandler` callback calls
  `setMe(null)` on any 401 mid-session with no explanation — a user typing a filter can get bounced
  to the login screen, indistinguishable from having chosen to log out themselves.
  Done, one design gap found beyond QA's sanity check: `ToastStack` was only mounted in the
  signed-in branch of `App.tsx`, but the 401 → `setMe(null)` transition unmounts that whole branch
  in the same commit the toast needs to render in — the toast would have been queued but never
  shown, since the signed-out branch (login screen) never mounted a `ToastStack` to pick it up.
  Fixed by mounting a second `<ToastStack />` in the `!me` branch too, so whichever branch is live
  at commit time still renders the queue (the module-scope queue itself survives the swap either
  way — `useSyncExternalStore`'s `getSnapshot()` reads it fresh on mount).
  `AuthContext.tsx` gets a `meRef` (synced via a `[me]`-effect) so the unauthorized handler — which
  registers once (`[]` deps) — can read the *current* `me` without re-registering on every change,
  same ref-for-imperative-reads shape as rule 3 in `frontend/CLAUDE.md`. The handler now does
  `if (meRef.current !== null) showToast(SESSION_EXPIRED_MESSAGE, 'alert')` before `setMe(null)` —
  the initial stale-token-on-load 401 (`meRef.current` still null there) and an explicit `logout()`
  call (bypasses the handler entirely) both correctly stay silent.
  Covered by two new tests in `auth.test.tsx`: a session that's genuinely live (signed in, `me` set)
  hitting a 401 on `ScanFeedPage`'s poll shows a `role="alert"` toast reading "session expired" and
  lands on the login screen (deliberately uses `ScanFeedPage`'s single-request poll rather than
  `ScanListPage`'s, which also fires a parallel `refresh()` `/api/auth/me` call each tick — using
  that one would race two concurrent responses over which `setMe` call lands last); a second test
  signs in, clicks "Sign out", and asserts no alert appeared. 177/177 frontend tests pass, tsc/lint/
  build clean (chunk split intact). PR: see git history.

- [x] **"You're offline" banner.** *(proposed by the hourly routine, 2026-09-03, Architect+QA:
  the `useOnlineStatus()` hook is sound and small, but the original toast-based design is not —
  see correction)* If wifi drops, every subsequent like/block/scan-create just fails with a generic
  error — nothing tells the user it's connectivity, not a bug.
  **QA correction (do not build as originally proposed):** routing this through
  `showToast(msg, variant, durationMs)` doesn't work — it always arms a real
  `window.setTimeout(dismiss, durationMs)`, `Infinity` coerces to a ~0ms timeout (immediate
  dismiss, not persistent), and `showToast` returns `void` so there's no id to hand `dismissToast`
  on `online` anyway. Build a `useOnlineStatus()` hook (`navigator.onLine` +
  `online`/`offline` listeners) mounted once in `App.tsx`, paired with a small standalone banner
  component (own visibility state, not routed through the toast queue) — NOT toast plumbing.
  Verify: a hook test dispatches `window` `offline`/`online` events and asserts the returned value
  flips (jsdom lets `navigator.onLine` be stubbed directly, no judgment call); a component test
  asserts the banner text appears/disappears with those same events.
  Done, built exactly to the QA correction: new `lib/useOnlineStatus.ts` — `useState(() =>
  navigator.onLine)` plus a mount-only effect (`[]` deps) registering `window` `online`/`offline`
  listeners. New `components/OfflineBanner.tsx` — a standalone `.banner.error` (reuses the
  existing error-banner tokens, no new color) rendered `role="status"`, returning `null` while
  online; no toast/timer plumbing at all, avoiding the `Infinity`-duration bug QA flagged. New
  `.offlinebanner` rule in `styles/base.css` makes it `position: sticky; top: 0` so it stays
  visible while scrolled, reusing existing spacing/radius tokens rather than inventing new ones —
  a layout/behavioral change, not a visual-taste one. Mounted in `App.tsx` in *both* branches
  (signed-in shell and the `!me`/login-or-signup branch, next to each `<ToastStack />`) since a
  dropped connection during sign-in is exactly as real as one mid-session, and the codebase
  already duplicates `ToastStack` the same way for the same reason. Covered by 2 new tests in
  `useOnlineStatus.test.ts` (initial value reads `navigator.onLine`; flips on `offline`/`online`
  events) and 3 in `OfflineBanner.test.tsx` (nothing rendered while online; appears/disappears
  with `offline`/`online` events; starts visible when the page mounts already offline — covering
  the "wifi was already down on load" case, not just the transition). 185/185 frontend tests pass
  (177 + 8 new), tsc/lint/build clean (chunk split intact — lands in the eagerly-loaded shared
  chunk via `App.tsx`, same as `ToastStack`, not a lazy route chunk). PR: see git history.

- [x] **Dropdown opens without moving focus, and closing loses it.** *(proposed by the hourly
  routine, 2026-09-03, Architect+QA-approved)* A keyboard user who opens a filter dropdown
  (Sort, Genre, …) via Enter/Space can't actually arrow-key through it — `Dropdown.tsx`'s
  `onPanelKeyDown` only fires for events bubbling from an already-focused `.ddrow`, and nothing
  puts focus there on open; closing via Escape doesn't return focus to the trigger either, so it
  can get lost to `<body>`. Fix: focus the first `.ddrow` when `open` becomes true; store/restore
  focus to the trigger `<button>` when the panel closes (Escape or outside-click). Verify: an RTL
  test — press Enter on the trigger, assert `document.activeElement` is the first `.ddrow`; press
  Escape, assert `document.activeElement` is the trigger button again.
  Done, with one refinement beyond the original proposal: `Dropdown.tsx` gained `panelRef`/
  `triggerRef`. An effect on `[open]` focuses the first `.ddrow` when the panel opens — but only
  if nothing inside it already has focus, so the Genre/Contains panels' own `autoFocus` search
  input (which React focuses during commit, before this passive effect runs) is left alone
  rather than fought over. On close, Escape and selecting a row (the render prop's `close()`)
  both restore focus to the trigger button; an **outside click does not** — a `restoreFocus` flag
  set to `false` inside the outside-click handler skips it, since the click itself already moved
  focus (or didn't) to whatever was clicked, and yanking it back to the trigger would fight that.
  This split wasn't in the original one-line proposal but follows directly from *why* Escape
  needed a fix in the first place (no natural focus target) versus an outside click (which
  already has one). Covered by 4 new tests in `Dropdown.test.tsx`'s new "open/close focus
  management" block: opening moves focus to the first row; Escape restores focus to the trigger;
  selecting a row restores focus to the trigger; an outside click leaves focus on whatever was
  clicked instead of stealing it back. A lint warning caught along the way
  (`react-hooks/exhaustive-deps` on reading `triggerRef.current` inside the effect's cleanup) was
  fixed by capturing it in a local `const trigger` at the top of the effect, same pattern
  `ShortcutsHelp.tsx`'s `previouslyFocused` ref already avoids by being a plain ref rather than a
  DOM-node capture. 184/184 frontend tests pass (180 + 4 new), tsc/lint/build clean (chunk split
  intact — `Dropdown` lands in the shared chunk used by both lazy routes, unchanged by this).
  PR: see git history.

- [x] **Rapid likes/blocks can pile up an unbounded toast stack.** *(proposed by the hourly
  routine, 2026-09-03, Architect+QA-approved)* `showToast` (`lib/toast.ts`) has no cap —
  repeated clicks or a batch bulk-block finishing queues one toast per action with no upper
  bound. Cap the queue (e.g. 4), evicting the oldest non-action toast first when a new one
  arrives (never evict one with a pending `action`, since that'd silently drop an undo). Verify:
  unit test — call `showToast` 6 times, assert the queue never exceeds the cap and the earliest
  are gone; a second case pushes an action-toast then 4 plain ones and asserts the action-toast
  survives.
  Done exactly as proposed: new `TOAST_STACK_CAP` (4) in `config.ts`. `showToast` now runs every
  new queue through `evictOverflow()` before storing it — a `while` loop that, as long as the
  queue is over the cap, drops the oldest toast with no `action` (`findIndex((t) => !t.action)`);
  if every current toast has a pending action, the loop breaks and the queue is left over cap
  rather than silently dropping one of them (an edge case rare enough not to need its own
  policy, per the proposal's own caveat). New `lib/toast.test.ts` — pure logic tests against the
  module's exported `showToast`/`useToasts`/`resetToastsForTests` (via `renderHook`, no full
  component render needed): pushing 6 plain toasts leaves exactly the 4 most recent; pushing one
  action-toast followed by 4 plain ones keeps the action-toast and evicts only from the plain
  ones. 182/182 frontend tests pass (180 + 2 new), tsc/lint/build clean (no bundle-size concern —
  `lib/toast.ts` is already in the eagerly-loaded shared chunk via `ToastStack`). PR: see git
  history.

- [x] **Signup's Bandcamp URL field has no format feedback until the server rejects it.**
  *(proposed by the hourly routine, 2026-09-03, Architect+QA-approved)* `SignupPage`'s "Your
  Bandcamp collection" input only checks non-empty — a malformed URL round-trips to the API and
  comes back as a generic error, whereas `NewScanForm` already validates seed URLs inline
  (`SEED_URL_RE` + `role="alert"`). Reuse that pattern here: extract a small `isValidFanUrl(url)`
  check, wire `aria-invalid`/`aria-describedby` on the input, show the inline error and disable
  submit before any network call. Verify: unit test for `isValidFanUrl` across valid/invalid
  cases; an RTL test asserting `aria-invalid="true"` and the error's `id` matches
  `aria-describedby` for an invalid value, and that submit stays disabled.
  Done: new `isValidFanUrl(url)` in `lib/format.ts`, next to the existing URL helpers
  (`bandcampHandle`/`seedKind`). Deliberately **stricter** than `NewScanForm`'s `SEED_URL_RE`:
  a fan's collection page always lives at the literal `bandcamp.com` host (`FAN_URL_RE =
  /^https?:\/\/bandcamp\.com\/[^/?#]+\/?(?:[?#].*)?$/i`), unlike an album/track URL which is
  hosted per-artist on any subdomain — the backend itself still only checks non-empty
  (`api/auth.py`), so this is UI-side early feedback, not a stricter gate than the API's. Rejects
  a bare `bandcamp.com`/`bandcamp.com/` (no handle) and an artist/label subdomain (that's a
  storefront, not a fan page); accepts a trailing slash, a tacked-on query string, surrounding
  whitespace, and is host-case-insensitive. `SignupPage.tsx`'s `fanUrlError` is a derived
  expression (frontend/CLAUDE.md rule 6 — no effect), shown only once the field is non-empty so a
  fresh form doesn't open already invalid; folded into the existing `complete` gate so submit stays
  disabled. The field's hint/error paragraphs now share one `aria-describedby` slot
  (`su-fanurl-hint` normally, `su-fanurl-error` — `role="alert"` — when invalid), with
  `aria-invalid="true"` added only in the error case. Covered by 9 new unit tests in
  `lib/format.test.ts` (valid plain URL, http/trailing-slash/whitespace, query string, host
  case-insensitivity, non-URL string, artist subdomain rejected, no-handle rejected, non-bandcamp
  host rejected, empty string) and 2 new integration tests in `auth/auth.test.tsx`: typing a
  malformed URL shows the alert with matching `aria-describedby`/`aria-invalid`, disables "Create
  account", and confirms `fetch` is never called; a well-formed URL shows no alert and leaves
  submit enabled. 202/202 frontend tests pass, tsc/lint/build clean (chunk split intact). PR: see
  git history.

- [x] **Confirm step for large bulk-block actions.** *(proposed by the hourly routine, 2026-09-03,
  Architect+QA-approved — "sound, easily mockable in RTL, small; genuinely new since bulk-block
  currently has no size guard or confirm step at all")* Bulk-select + bulk-block already exists
  with no size guard — undo covers a single mis-click, but a stray "select a run of cards" + block
  on a large filtered set has a bigger blast radius than the click that caused it, with no
  confirmation in between. (Two sibling proposals from the same Product/Architect+QA round were
  cut: a `?sort=` control turned out to already exist — `SortKey`/`useFeedFilters`/`FilterBar`
  already sort by score/neighbours/affinity, just not by the newest/A-Z keys Product assumed; a
  generic `EmptyState`-by-cause component turned out to mostly duplicate the already-shipped
  "Clear filters" empty state and `ColdStartPanel`, and QA's one narrowed slice —
  "filters-active-but-band-blocked" — wasn't concretely a distinct reachable state worth building
  blind, so left unqueued rather than built on a guess.)
  Done: new `BULK_CONFIRM_THRESHOLD` (5) and `BULK_CONFIRM_WINDOW_MS` (4000, same window as
  `DeleteScanButton`'s) in `config.ts`. `components/BulkActionBar.tsx` gets the exact same
  two-click, auto-reverting confirm shape `DeleteScanButton` already uses — no native `confirm()`,
  this app doesn't use those anywhere. At or below the threshold, clicking "Block selected" still
  fires `onBlock` immediately (today's behavior, unchanged — covered by the pre-existing test at
  `count={3}`). Above it, the same click arms a `Block N bands?` / `Cancel` pair instead
  (`.btn.ghost.danger`, reusing `DeleteScanButton`'s existing danger-button styling — no new CSS);
  a second click on `Block N bands?` fires `onBlock`, `Cancel` reverts without calling it, and the
  arm reverts on its own after `BULK_CONFIRM_WINDOW_MS` if neither is clicked. A `useEffect` on
  `[count]` also clears any pending confirm/timer the moment the selection size changes — armed
  against a stale N (e.g. a card deselected while the bar is up) would silently block the wrong
  count. Covered by 4 new tests in `BulkActionBar.test.tsx`'s new "confirm step above the
  threshold" block: a first click above the threshold doesn't call `onBlock` and shows the
  `Block N bands?` prompt, a second click does; at/below the threshold there's no prompt at all
  (pre-existing behavior, re-asserted at the threshold boundary itself); `Cancel` inside the
  confirm step calls neither `onBlock` nor the outer `onCancel` and returns to the normal bar;
  the armed prompt auto-reverts after `BULK_CONFIRM_WINDOW_MS` under fake timers. 206/206 frontend
  tests pass (202 + 4 new), tsc/lint/build clean (chunk split intact — `BulkActionBar` lands inside
  the `ScanFeedPage` chunk, its only importer). PR: see git history.

- [x] **Blocked panel never shows a temporary block's expiry.** *(found by the hourly routine,
  2026-09-03, via direct code audit)* The backend's `Blacklist.expires_at` (added by the earlier
  "Blacklist is all-or-nothing forever" item) is already returned end-to-end —
  `BlacklistOut.expires_at` on `GET /api/blacklist` — but the frontend `Blocked` type never
  declared the field and `BlockedPanel` (`SidePanels.tsx`) never rendered it: a temporarily-blocked
  band showed identically to a permanently-blocked one, with no way to tell it'll come back.
  (Adding UI to *set* an expiry from the block button is bigger scope — a duration picker on
  `FeedCard`'s ⊘ button — and left for a separate item; this is the smaller, purely-display slice:
  surface the expiry the API already sends.)
  Done: `Blocked.expires_at: string | null` added to `api/types.ts`. New `expiresLabel(iso)` in
  `lib/format.ts` — `''` for `null` (permanent) or an already-lapsed timestamp (the backend's own
  `expires_at > now()` filter keeps a lapsed row out of the response in the first place, so this
  is a display nicety, not the enforcement), else `"expires in Xm/Xh/Xd"` at the same granularity
  `ago()` already uses for the past. `BlockedPanel` renders it as a third `· `-joined hint segment
  next to `band_url`, only when non-empty. Covered by 5 new unit tests in `format.test.ts` under
  fake system time (null → empty, lapsed → empty, same-day → hours, sub-hour rounds up to at least
  1m, multi-day → days) and 1 new integration test in `feed.test.tsx`'s "unlike/unblock from the
  side panels" block: opening the Blocked panel with one temporary and one permanent entry shows
  `expires in Nh` on the temporary row's `<li>` and nothing matching `/expires in/` on the
  permanent one's. 212/212 frontend tests pass (206 + 6 new), tsc/lint/build clean (chunk split
  intact). PR: see git history.

- [x] **Blocked panel shows a band's URL as inert text, not a link.** *(found by the hourly
  routine, 2026-09-03, via direct code audit, same pass as the expiry item above)* `BlockedPanel`
  rendered `band_url` as a plain `<span>` — no way to actually open the blocked artist's page —
  while its sibling `LikedPanel`, right above it in the same file, already links its item's `url`
  via an icon-only "↗" anchor with a proper `aria-label`. Same data shape, inconsistent treatment.
  Done: `BlockedPanel` now renders `band_url` with the exact same icon-only-link pattern
  `LikedPanel` already uses (`.listen.sm`, `target="_blank" rel="noopener noreferrer"`,
  `aria-label="Open {band} on Bandcamp"`, decorative `↗` marked `aria-hidden`) instead of a text
  span — no new CSS, reuses the class `LikedPanel` already relies on. Covered by 1 new test in
  `feed.test.tsx`: a blocked band with a `band_url` gets a `role="link"` with the expected
  accessible name and `href`; one with `band_url: null` has no link at all inside its row.
  213/213 frontend tests pass (212 + 1 new), tsc/lint/build clean (chunk split intact). PR: see
  git history.

- [x] **Extract existing empty-state logic into a shared `EmptyState` component.**
  *(proposed by the hourly routine, 2026-09-03)* Product pitched this as three new empty-state
  variants (no scan yet / filtered-to-zero / genuinely empty); Architect+QA checked the actual
  code first and found all three already exist (`ColdStartPanel` for the cold-start cases, the
  "Clear filters" button for filtered-to-zero) — rescoped down to a consolidation: wrap the
  existing branches in one component with a `data-testid` per variant, no new behavior. Small,
  testable (RTL asserts the right testid for each mock combo), but lower value than net-new work
  since nothing user-visible changes — left queued behind the item below.
  **Scoped down further on build:** Product's three named variants (no-scan / filtered-to-zero /
  genuinely-empty) don't cleanly exist as three *renderable* states in the actual code — a
  "no scan yet" moment is just `ColdStartPanel` rendering `null` while `coldStart` hasn't loaded,
  not a distinct branch with its own copy. Built the two real, distinguishable causes instead of
  inventing a third to match the pitch: `filtered-empty` (an active filter narrowed the
  server-side result set to nothing) and `cold-start` (no filter at all — `ColdStartPanel`'s own
  existing internal branches, unchanged, explain the rest).
  Done: new `features/feed/EmptyState.tsx` — `{anyActive, coldStart, onClearFilters}` in, the
  exact same markup `ScanFeedPage.tsx`'s inline block already rendered, each variant now wrapped
  in a `div` carrying `data-testid="empty-filtered"`/`"empty-cold-start"`. `ScanFeedPage.tsx`'s
  `rows.length === 0 && !loading && !error` block is now one `<EmptyState ... />` call; no
  wording, styling, or behavior changed, so the pre-existing text-based assertions in
  `feed.test.tsx` (`findByText('Nothing matches these filters…')`,
  `findByText('No recommendations in this scan yet.')`) needed no changes and still pass
  unmodified — direct evidence the swap was behavior-preserving. Covered by 3 new tests in
  `EmptyState.test.tsx` (a standalone RTL render, no router/api mocking needed): `anyActive`
  renders `empty-filtered` with a working Clear-filters button and no cold-start testid; no active
  filter with `coldStart: null` renders `empty-cold-start` with no button; a loaded `coldStart`
  renders through to `ColdStartPanel`'s own diagnostics text. 221/221 frontend tests pass (218 +
  3 new), tsc/lint/build clean (chunk split intact — the new file lands in the `ScanFeedPage`
  chunk, its only importer). PR: see git history.

- [x] **Auto-prune URL-persisted filters that no longer exist in facets.**
  *(proposed by the hourly routine, 2026-09-03, Architect+QA-approved as genuinely new)* After a
  recompute or crawl, a `tag`/`label_id` filter carried in the URL can point at a facet that no
  longer exists, silently rendering an empty feed with no explanation why. When `GET /api/facets`
  returns and a persisted filter value isn't in the list, drop it from the URL/state and toast
  what was dropped (reusing the existing `lib/toast.ts`/`ToastStack` primitive). QA confirmed
  `ScanFeedPage.tsx` already fetches facets but has no diff/prune logic against the persisted
  filters today — genuinely net-new, not a duplicate of anything shipped. Verify: a unit test
  feeding a mock facets response missing the current filter into `useFeedFilters` asserts the
  param is removed and the toast fires with the dropped value's name — pure logic, no visual
  check needed.
  **Scoped down on build, beyond what Product/Architect+QA sanity-checked:** `label_id` is NOT
  pruned. `GET /api/facets`'s `labels` rows are `.limit(200)` server-side (`app/api/feed.py`), so
  a scan with more than 200 distinct bands in its recs (this app's own `CLAUDE.md` records a live
  curate producing 1,600) would see a perfectly valid `label_id` filter fall outside that top-200
  window and get wrongly "pruned" as stale — a false positive the original proposal didn't
  account for. `tags` has no such limit, so only `tag=`/`exclude_tag=` were in scope for real.
  Within that, only **include**-mode (`tag=`) entries are dropped: an `exclude_tag=` for a value
  that's currently absent from every rec is a harmless no-op (excluding something that isn't
  there changes nothing), not the "silently matches nothing" bug this item is actually about, so
  leaving it alone avoids surprising a reader by clearing an exclusion they set on purpose.
  Done: `useFeedFilters.ts` gains `pruneTags(stale: string[])` — removes one or more `by`-mode
  `tag=` entries from the URL in a single `setSearchParams` update (reuses the same
  `readModes`/`writeModes` helpers every other tag setter already goes through). `ScanFeedPage.
  tsx`'s `loadFacets()` now diffs the freshly-fetched `tags` facet against the currently active
  `by`-mode tags (read via a new `activeTagsRef`, kept in sync by a `[activeTags]` effect — an
  imperative read inside `loadFacets`, the same `meRef`-style shape `AuthContext` already uses, so
  toggling a tag filter doesn't itself re-create `loadFacets` and cause an extra facets refetch on
  every click); any that are missing get `pruneTags`'d and a `showToast(..., 'status')` names what
  was removed. `loadFacets` already re-runs on every `recCount` change (a recompute), which is
  exactly the trigger that can make a tag disappear, so no new call site was needed. Covered by 3
  new integration tests in `feed.test.tsx`'s new "auto-prune stale tag filters" block, driving a
  scan poll like the existing "feed reflow notice" tests do: a `tag=psybient` filter is dropped
  from the URL with a toast naming it once a simulated recompute's facets response stops
  containing that tag; an `exclude_tag=psybient` filter is left untouched and no toast appears
  under the identical facets change (proving the include/exclude asymmetry above); a still-valid
  `tag=psybient` filter survives a recompute unchanged with no toast. 218/218 frontend tests pass
  (215 + 3 new), tsc/lint/build clean (chunk split intact). PR: see git history.

- [x] **Add an accessible ISO-time fallback to `RelativeTime`.** *(proposed by the hourly
  routine, 2026-09-03, Architect+QA-approved with a correction)* Product pitched a new
  `formatRelativeTime` util; QA checked the code first and found `RelativeTime.tsx`/`ago()`
  already do self-refreshing relative text — the only real gap was accessibility: the component
  rendered bare text with no exact-timestamp fallback for a screen reader or a sighted user who
  wants precision, unlike `expiresLabel`/other timestamp displays in this codebase that already
  favor plain text over any ARIA metadata. Rescoped to "add `title`/`aria-label` to the existing
  component," not a parallel util (would have duplicated `ago()`).
  Done: `RelativeTime.tsx` now renders `<time dateTime={iso} title={iso}>{ago(iso)}</time>`
  instead of a bare `<span>` — semantic `<time>` element with the machine-readable `dateTime`
  attribute plus a `title` carrying the same raw ISO string, so hovering (sighted mouse user) or
  reading the element's title (assistive tech that surfaces it) gets the exact timestamp behind
  the relative text. No change to the refresh interval/logic. Covered by 2 new tests in
  `RelativeTime.test.tsx`: renders a `title` attribute equal to the raw ISO string alongside the
  relative text; a `null` iso still renders nothing (title has nothing to attach to). PR: see git
  history.

- [x] **Warn before the session silently expires.** *(proposed by the hourly routine, 2026-09-03,
  Architect+QA-approved)* A dropped session today just dies — the JWT lapses mid-task and the user
  only finds out when their next click 401s and drops whatever they were doing (a filter, a bulk
  selection). A sibling proposal from the same round, a `usePrefersReducedMotion()` hook, was cut
  before reaching QA: `frontend/src/styles/base.css` already has a global
  `@media (prefers-reduced-motion: reduce)` block zeroing `animation-duration`/`transition-duration`
  app-wide, so the hook would have been a full duplicate — logged so a future round doesn't
  re-propose it (see `tried-and-failed.md`, which already carries the same finding from an earlier
  round; consolidating both notes there is left for a future pass, not urgent).
  Done: new `lib/jwt.ts` — `decodeJwtExpMs(token)`, a ~10-line base64url decode of the JWT payload
  (no library — `atob` plus swapping `-_`→`+/` and re-padding), returning the `exp` claim in ms or
  `null` for anything that doesn't parse (malformed token, missing/non-numeric claim). This app
  never verifies the token client-side, only reads expiry for the warning — the server stays the
  real authority. New `lib/sessionExpiry.ts` — pure `msUntilWarning(token, nowMs)`: `null` for an
  unreadable or already-expired token (the existing 401 handler covers real expiry), otherwise the
  delay until `SESSION_EXPIRY_WARNING_MS` (5 minutes, new in `config.ts`) before `exp`, or `0`
  (warn immediately) if less than that window is already left. New `lib/useSessionExpiryWarning.ts`
  wraps it in a `useEffect` keyed on `token`: schedules one `setTimeout` calling the existing
  `showToast(..., 'alert')`, cleared on unmount or token change so a stale timer from a previous
  login never fires. Wired into `AuthContext.tsx` as `useSessionExpiryWarning(me !== null ?
  getToken() : null)` — one line, no new state, reusing the token/`me` the provider already tracks.
  Covered by 5 new tests in `jwt.test.ts` (valid claim, malformed token, bad base64/JSON, missing
  claim, non-numeric claim), 5 in `sessionExpiry.test.ts` (plenty of time left, less than the
  window left warns immediately, already-expired returns null, no claim, malformed token), and 5 in
  `useSessionExpiryWarning.test.ts` under fake timers (fires exactly once at the right offset with
  the right message/variant; null token schedules nothing; an unreadable token schedules nothing;
  unmount clears the timer; changing the token cancels the old timer rather than letting it fire
  late). 236/236 frontend tests pass (221 + 15 new), tsc/lint/build clean (chunk split intact —
  lands in the shared chunk via `AuthContext`, not a lazy route, which is correct since auth
  applies everywhere). PR: see git history.

- [x] **Surface soon-to-expire blocks in the Blocked side panel, with a renew action.**
  *(proposed by the hourly routine, 2026-09-03, Architect+QA-approved, then found blocked on
  build)* A sibling proposal from the same Product/Architect+QA round as the session-expiry
  warning above. Sort the Blocked panel by `expires_at` ascending (soonest-expiring first,
  permanent last) and add a "renew" action on rows expiring within 24h that re-POSTs the same
  `band_id` with a fresh `expires_at`. Architect+QA confirmed `POST /api/blacklist`
  (`backend/app/api/blacklist.py`) already upserts by `user_id`+`band_id` — no backend change
  needed, renew is mechanically just re-posting.
  **Not built — a real gap the QA pass didn't check:** nothing in the frontend ever sends
  `expires_at` when blocking. `api.block()` (`api/client.ts`) takes only a `bandId`, and its one
  caller, `ScanFeedPage.tsx`'s `block()`, calls it with no expiry — same for `BulkActionBar`'s
  path. So today a temporary block can only exist if someone posts to `/api/blacklist` directly;
  through the app itself every block is permanent, and this "renew" feature would have no real
  rows to act on. Worse, "renew for how long" has no established convention anywhere in the
  codebase to reuse (no default-duration constant, no duration picker) — picking one here would
  be inventing UI/UX unilaterally, not the "mechanical, no design call" change QA sanity-checked.
  **Rescoped and the prerequisite is now built (2026-09-03):** the real gap was the missing
  duration picker on the block action itself (also flagged separately by the "Blocked panel
  never shows a temporary block's expiry" entry above). `FeedCard`'s `⊘ block` button is
  untouched (still an immediate, permanent block — no test or keyboard-shortcut behavior
  changed) and a new "block for… ▾" `Dropdown` sits next to it, offering `1 day` / `1 week` /
  `1 month` (`BLOCK_DURATIONS` in `config.ts`); picking one computes `expires_at` as
  `Date.now() + duration` and calls the same `onBlock(rec, expiresAt)` path, now threaded
  through `ScanFeedPage.tsx`'s `block()` callback to `api.block(bandId, expiresAt)` (backend
  unchanged, already accepted `expires_at`). The picker hides while either action on that card
  is in flight, mirroring the existing busy-disables-both-buttons convention. "Renew" itself
  (the originally-proposed side-panel action) is still not built — left for a follow-up now that
  it has a real default duration to reuse, per the original rescoping note.
  Covered by 5 new tests in `FeedCard.test.tsx` (picker present/absent by band/busy state,
  computes the correct ISO expiry from a fixed system clock and closes the panel, the plain
  block button is still an immediate untouched call) and one integration test in
  `feed.test.tsx` ("blocking via the duration picker sends the computed expires_at and blocks
  the card": drives the real dropdown + `POST /api/blacklist` body end to end under fake
  timers). 242/242 frontend tests pass, tsc/lint/build clean (chunk split intact — the new
  `Dropdown` import lands inside the existing `ScanFeedPage` chunk, which already imports
  `Dropdown` via `FilterBar`). PR: see git history.
  **Renew follow-up landed (2026-09-03):** `SidePanels.tsx`'s `BlockedPanel` now sorts rows by
  `expires_at` ascending (soonest-expiring first, permanent last, via
  `byExpirySoonestFirst`), and a row within `RENEW_WINDOW_MS` (24h, new in `config.ts`) of
  lapsing gets a "renew ▾" `Dropdown` reusing the same `BLOCK_DURATIONS` options as the block
  picker — picking one calls a new `ScanFeedPage.tsx` `renew(bandId, expiresAt)` (mirrors
  `unblock`'s shape: same `blockedKeyOf`/`panelBusy`/`inFlight` guards) which re-POSTs
  `/api/blacklist` with the same `band_id` and only reloads the Blocked list (the band is
  already excluded from the feed, so no `loadFirstPage`/`loadFacets` round trip like a fresh
  block needs). Covered by 3 new tests in `feed.test.tsx`: renew appears only on the
  soon-to-expire row and the list sorts soonest-first; picking a renew duration posts the
  correct `band_id` and a `expires_at` ~1 week out; a block expiring in several days or a
  permanent one gets no renew action. 245/245 frontend tests pass, tsc/lint/build clean (chunk
  split intact — `Dropdown`/`BLOCK_DURATIONS` were already imported into the `ScanFeedPage`
  chunk). PR: see git history.

- [x] **`frontend/CLAUDE.md`'s "Known conflicts and deferred items" section was stale.**
  *(found by the hourly routine, 2026-09-03, via direct code audit)* Four of its five listed gaps
  had already been fixed by earlier rounds — deep-linking, skeleton loading, skip-links/focus-on-
  route-change, and the contrast measurement — but the doc still described them as open. Stale
  status here risks the same waste `tried-and-failed.md` already flags for summary-only Product
  rounds: a future proposal reading this section rather than the real code could re-propose (or
  re-investigate) something already shipped.
  Done: updated all four resolved bullets to say what actually landed and point at the file(s) that
  did it (`useFeedFilters.ts`, `FeedCardSkeleton`/`ScanCardSkeleton`, `App.tsx`'s skip link, `lib/
  contrast.ts`), verified against the actual source (not the backlog's prose) before writing each
  one. The one deliberately-unresolved item — icon glyphs vs. SVG icons — is untouched, per the
  standing instruction not to resolve that call unilaterally. Docs-only change; no tests apply, but
  `npm test`/`tsc`/`lint`/`build` were re-run to confirm nothing else was touched. PR: see git
  history.
- [x] **The "Load more" button literally reads "Load mores".** *(proposed by the hourly routine,
  2026-09-03, Architect+QA-approved, found via direct code audit rather than guessing)*
  `ScanFeedPage.tsx` built the label as `` `Load ${plural(LIMIT, 'more')}` ``, and `plural(n, one,
  many=one+'s')` only returns `one` when `n===1` — `LIMIT` is the fixed page size (50), never 1, so
  the button has read "Load mores" unconditionally since it shipped. "more" here is a fixed adverb,
  not a count being pluralized, so `plural()` was never the right tool for this call site (its other
  callers — `ScanListPage.tsx`, `ColdStartPanel.tsx`, `FeedCard.tsx` — all pluralize genuinely
  variable counts and are unaffected).
  Done: replaced the `plural()` call with the fixed string `'Load more'`. Covered by a new test in
  `feed.test.tsx` asserting the button's accessible name is exactly `'Load more'` when more pages
  remain — fails against the old code, passes now.

- [x] **A scan name can be created with baked-in leading/trailing whitespace.** *(proposed by the
  hourly routine, 2026-09-03, Architect+QA-approved, found via direct code audit)* `NewScanForm.tsx`
  gates the Create button on `!name.trim()` but `create()` posts `api.createScan({ name, seeds })`
  with the raw, untrimmed state — a name typed as `"  My Scan  "` (or with a stray trailing space
  from autocomplete/paste) passes the enabled check and is persisted with the whitespace intact
  everywhere the scan's name is displayed.
  Done: trim at the point of submission (`api.createScan({ name: name.trim(), seeds })`) — the
  `disabled` check and the input's own `onChange` are untouched. Covered by a new test asserting
  `api.createScan` is called with the trimmed name when the field holds leading/trailing whitespace.

- [x] **`expiresLabel` rounds across its own bucket boundary.** *(proposed by the hourly routine,
  2026-09-03, found via direct code audit — a repeat of the same "read the actual files, don't
  brainstorm features" approach that found the two bugs above)* `lib/format.ts` chose the
  minutes/hours/days bucket from the *raw* seconds (`s < 3600`) but rounded the *displayed* number
  independently, so a value in the last ~30s before an hour (or ~30min before a day) rounded up
  past its own bucket: 59m50s left rendered "expires in 60m", 23h45m left rendered "expires in
  24h" — exactly the nonsensical labels the bucketing exists to avoid. Real-world trigger: a block
  renewed for `1 day` (the "renew ▾"/"block for… ▾" pickers) shows "expires in 24h" for its last
  half hour.
  Done: bucket on the *rounded* value instead, falling through to the next unit when rounding
  overflows the current one (`minutes = Math.round(s/60); if (minutes < 60) …`, then hours, then
  days). Covered by a new `format.test.ts` case asserting both boundary inputs now render `1h`/`1d`
  instead of `60m`/`24h`.

- [x] **An empty `label_id` in a bookmarked feed URL silently filters to a nonexistent band.**
  *(proposed by the hourly routine, 2026-09-03, same code-audit round as above)* `useFeedFilters.ts`
  parsed the artist filter as `Number(searchParams.get('label_id'))`, and `Number('')` is `0` —
  which `Number.isInteger` accepts — so `?label_id=` (present but empty: a hand-edited or
  partially-stripped bookmarked/shared URL, the exact input this hook's own "shareable/bookmarkable"
  docstring commits to tolerating) parsed as a real filter on band id 0 instead of "no filter",
  silently zeroing the feed instead of showing it unfiltered. `itemType`/`sort` in the same file
  already guard this shape correctly via an explicit allow-list (`isItemType`/`isSortKey`); the
  label parse was the one path trusting a loose numeric coercion instead.
  Done: treat `id === ''` the same as `id === null` (no filter), alongside the existing
  non-numeric-string guard. Covered by a new `feed.test.tsx` case opening `/scans/1?label_id=` and
  asserting no artist-filter pill renders and the (unfiltered) feed still shows its row.
  249/249 frontend tests pass, tsc/lint/build clean, both bugs from this round.

- [x] **`GET /api/facets` tag facets drop every genre that only tracks carry.** *(proposed by the
  hourly routine, 2026-09-03, found via the same "read the actual files" code-audit method, this
  round pointed at the backend)* `api/feed.py`'s tag-facets query inner-joined `AlbumTag` only, so
  any recommendation with `item_type == "track"` (`album_id` is `NULL`) could never match — a genre
  that only tracks carried via `TrackTag` silently never appeared in the facet list, even though
  `GET /api/recommendations?tag=<that genre>` (via `_has_tag`, which correctly ORs `AlbumTag`/
  `TrackTag`) would filter on it correctly. The `labels` facet three lines below already handles
  album/track symmetrically (`outerjoin` + `coalesce`); the tag-facets query was the one place in
  this file still treating them asymmetrically — the exact class of bug CLAUDE.md's M4 notes already
  flagged once for curation scoring itself.
  Done: union the `AlbumTag` and `TrackTag` matches (mirroring `_has_tag`'s OR shape) before
  aggregating, instead of inner-joining `AlbumTag` alone. Covered by a new
  `test_facets_include_track_only_tags`, confirmed to fail against the old query (empty tag set)
  before the fix and pass after.

- [x] **A failed recompute call still consumes the rate-limit cooldown.** *(proposed by the hourly
  routine, 2026-09-03, same backend code-audit round as above)* `POST /api/recommendations/recompute`
  wrote `_last_recompute_at[user.id]` before checking the `scan_id` belonged to the caller and
  before `curate()` could raise — so a legitimate 404 (bad `scan_id`, or a collection not yet
  crawled) still started the cooldown window, locking an immediately-following *correct* call
  behind a 429 it didn't deserve.
  Done: moved the `scan_id` ownership check (a fast, deterministic 404) above the cooldown block
  entirely, and wrapped the `curate()` call so a `ValueError` restores the previous cooldown
  timestamp (or clears it if there wasn't one) instead of leaving the just-written one in place.
  Covered by a new `test_recompute_failure_does_not_consume_the_cooldown` (bad `scan_id` under an
  enabled cooldown, then an immediate valid call still gets `200`), confirmed to fail against the
  old ordering (`429`) before the fix. 249/249 backend tests pass, ruff clean, both bugs from this
  round.

- [x] **Announce the updated match count after "Load more."** *(proposed by the hourly routine,
  2026-09-03, Architect+QA-approved: "sound, testable, small. Ship it.")* `ScanFeedPage.tsx`'s
  `.countline` paragraph ("N recs match your filters") updates visibly when "Load more" resolves,
  but it's a plain `<p>` with no `aria-live`, so a screen-reader user gets no confirmation that
  more rows actually loaded. Add `role="status" aria-live="polite"` to it. Verify: RTL test
  asserting the countline has `role="status"` and its text reflects the new count after
  `loadMore` resolves — no visual check needed.
  Done: added `role="status" aria-live="polite"` to the countline. In practice `total` (what the
  countline shows) doesn't change on "Load more" itself — it's the server-side match count, not a
  loaded-so-far tally — so the announceable case is really any `total` change (a like/block
  decrementing it, a filter narrowing it, etc.), which this covers identically. Also fixed three
  existing "auto-prune stale tag filters" tests that used a bare `*ByRole('status')` to detect a
  toast — now ambiguous since the countline shares that role — by scoping to the toast's own
  `.toast` class instead. Covered by a new test in `feed.test.tsx`: the countline has
  `role="status"` and its text updates from "1 results" to "0 results" after a like resolves.
  250/250 frontend tests pass, tsc/lint/build clean. PR: see git history.

- [x] **"Select all loaded" for bulk-select.** *(proposed by the hourly routine, 2026-09-03,
  Architect+QA-approved — "testable if confined to a pure state-derivation function; must read
  from the already-filtered `visibleRows`, not raw data")* Bulk-select only toggles one card at a
  time, so clearing a genre's worth of recs from a large scan still means clicking every checkbox.
  Add a "Select all loaded" control (select mode only) that sets the selection to every currently
  *visible* row's key (respecting the active quick-filter/genre filters, not the full server-side
  result set), toggling back to none on a second click. Verify: unit test — with N visible rows
  and select mode on, one click makes the selection size equal `visibleRows.length` and every
  card show `selected=true`; a second click clears it back to zero.
  Done: `ScanFeedPage.tsx` derives `selectableKeys` from `visibleRows` filtered to `band_id !==
  null` (mirrors `FeedCard`'s own checkbox gate — nothing is offered for selection that never had
  a checkbox), and a new `selectAllLoaded()` toggles the selection between "every selectable key"
  and empty, based on whether every one is already selected (not a plain boolean flip — clicking
  it after individually checking some, but not all, rows completes the selection rather than
  clearing it). `FilterBar.tsx` renders a "☑ Select all loaded" / "✕ Deselect all" button next to
  the select-mode toggle, shown only in select mode and only when there's at least one selectable
  row. Covered by 2 new tests in `feed.test.tsx`'s "bulk select" block: clicking it checks every
  card and a second click clears them all (scoped against the bulk bar's own count via `within`,
  not a bare `findByText`, since the feed's countline can coincidentally show the same digit as
  the unfiltered total); a quick-filtered view offers only the narrowed set. 252/252 frontend
  tests pass, tsc/lint/build clean (chunk split intact). PR: see git history.

- [x] **Tab-title status marker for a finished scan.** *(proposed by the hourly routine,
  2026-09-03, Architect+QA-approved with a caveat: "sound in isolation but riskiest of the three —
  keep the effect isolated to one small hook so the test doesn't need the whole ScanFeedPage tree,
  and watch for `document.title`/`document.hidden` mock cleanup polluting other test suites")* A
  scan can run for a while (crawl on the operator's Mac); tabbing away gives no signal it finished
  — `useDocumentTitle` only ever shows the scan's name, never its status. Prefix the title (e.g.
  `"✓ "`) when a poll observes a `running`→`done` transition while the tab is hidden/unfocused,
  clearing the prefix on refocus. Verify: a hook-level unit test (not a full-page render) driving
  a mocked status transition plus `document.hidden`, asserting the title gains the prefix on the
  transition and loses it on simulated refocus.
  Done, per QA's caveat: new standalone `lib/useScanFinishedMarker.ts` — a pure `boolean` hook,
  no `document.title` formatting inside it (that's still `useDocumentTitle`'s job; the two compose
  in `ScanFeedPage.tsx` rather than merging). `marked` only flips true on an observed `running`→
  `done` transition (a `useRef` holds the previous status) while `document.hidden` at the moment
  of that transition — a scan already `done` on mount, or one that finishes while the tab is
  visible, is correctly left unmarked (nothing "just finished" from the reader's perspective in
  either case). A second effect, alive only while `marked`, clears it on the next
  `visibilitychange` where `document.hidden` is false. `ScanFeedPage.tsx` calls
  `useDocumentTitle(scan?.name ? (justFinished ? \`✓ ${scan.name}\` : scan.name) : scan?.name)`.
  Covered by 5 new tests in `useScanFinishedMarker.test.ts` (`renderHook`, no page mount needed):
  marks true on the transition while hidden; clears on a simulated `visibilitychange` to visible;
  a scan already `done` on mount is never marked; a transition while the tab is visible is never
  marked; a `visibilitychange` event with nothing marked is a no-op — each test resets
  `document.hidden` in `afterEach` per QA's cleanup caveat. One new integration test in
  `feed.test.tsx`'s "document title" block drives a real scan-status poll (`SCAN_POLL_MS`) under
  fake timers with `document.hidden` stubbed true throughout, confirming the full path end to end:
  `document.title` gains the `"✓ "` prefix once the poll observes `done`, and loses it once a
  `visibilitychange` event fires with `document.hidden` false. 258/258 frontend tests pass,
  tsc/lint/build clean (chunk split intact). PR: see git history.

- [x] **Password show/hide toggle.** *(proposed by the hourly routine, 2026-09-03,
  Architect+QA-approved — "sound, RTL-testable, small — ship it")* `LoginPage.tsx`/
  `SignupPage.tsx` both render a raw `<input type="password">` with no way to verify what was
  typed — a typo surfaces only as a failed sign-in/sign-up. Verified via grep before proposing:
  no existing `PasswordInput`/toggle component anywhere in `frontend/src`.
  Done: new `components/PasswordInput.tsx` wraps the existing `<input>` (same `id`/
  `autoComplete`/`value`/`onChange` the two pages already passed) with a `.pwtoggle` button that
  flips the input's `type` between `password`/`text` and its own text between "Show"/"Hide",
  carrying `aria-pressed` — a visible-text button, so no separate `aria-label` is needed (same
  rule `frontend/CLAUDE.md`'s icon-button guidance already applies to `♥ like`/`⊘ block`). Kept
  as a plain text toggle rather than picking a new icon glyph, deliberately staying out of the
  unresolved icon-glyphs-vs-SVG question flagged in `frontend/CLAUDE.md`. `PasswordInput.css`
  positions it absolutely inside the field (existing `.input` gets extra `padding-right`) using
  existing tokens only, no new colors. Both pages now use `<PasswordInput id="password"
  autoComplete="current-password" .../>` in place of the raw input; the `id`/`<label htmlFor>`
  wiring is unchanged, so every existing `getByLabelText('Password')` test kept working with no
  edits. Covered by 4 new tests in `PasswordInput.test.tsx` (standalone RTL render, no
  router/api mocking needed): starts masked with a "Show" toggle at `aria-pressed="false"`;
  clicking it reveals the value, flips to "Hide"/`aria-pressed="true"`, and a second click
  reverts both; the `onChange` wiring still fires; `autoComplete` passes through. 257/257
  frontend tests pass, tsc/lint/build clean (chunk split intact — `LoginPage`/`SignupPage`
  chunks pick up the shared component without collapsing into the eager bundle). PR: see git
  history.

- [x] **Caps Lock warning on password fields.** *(proposed by the hourly routine, 2026-09-03,
  Architect+QA-approved — "sound and testable, small — ship it, with a caveat: `getModifierState`
  can't detect Caps Lock already on before the field is focused/typed in — a known non-blocking
  API limitation, not a defect to fix")* A sign-in failing because Caps Lock silently mangled the
  password gives no signal today.
  Done: added directly to `components/PasswordInput.tsx` (built for the show/hide-toggle item
  just above) rather than duplicating an `onKeyUp` handler in both `LoginPage.tsx` and
  `SignupPage.tsx` — both already route their password field through it. `onKeyDown`/`onKeyUp`
  both call `event.getModifierState('CapsLock')` (`onKeyDown` too, so the warning appears on the
  very keystroke that turns it on, not one keystroke later); a `role="status"` `<p className=
  "pwcaps">` renders next to the field while it's true, wired via `aria-describedby` on the input
  — the same hint/error pattern `SignupPage.tsx`'s `fanUrlError` already uses. New `--warn` token
  color (already used elsewhere for expiry/budget warnings), no new colors. The known
  `getModifierState` limitation (can't see Caps Lock already on before the field is touched) is
  left as-is per QA's caveat, not treated as a defect. Covered by 2 new tests in
  `PasswordInput.test.tsx`: no warning by default; a `keydown` with `getModifierState` stubbed
  `true` on the dispatched event (jsdom's `KeyboardEvent` constructor drops non-standard init
  fields, so the stub has to be set on the event instance directly, not passed through
  `fireEvent`'s init dict) shows the warning wired via `aria-describedby`, and a `keyup` with it
  stubbed `false` hides it again. 259/259 frontend tests pass, tsc/lint/build clean (chunk split
  intact). PR: see git history.

- [x] **Persist `art_id` onto `albums`/`tracks`.** *(proposed by the hourly routine, 2026-09-03,
  Architect+QA-approved — "sound and testable ... genuinely just wiring existing parsed data
  through the mapper/column/API rather than new parsing logic ... small enough for one sitting")*
  Found via direct code audit, prompted by an earlier round's rejected "album art placeholder"
  proposal (see `tried-and-failed.md`): `app/bandcamp/parse.py` already extracts Bandcamp's art
  asset id for albums (`ParsedAlbum.art_id`, from `tralbum.art_id`) and fan-collection items
  (`ParsedItem.art_id`, from `item_art_id`), but nothing downstream stored it — `Album`/`Track`
  had no art column and `mapper.py` never read `art_id` at all. Deliberately backend-only: no
  `<img>`, no `art_url` construction, no frontend change — a bounded slice for a future
  frontend-facing follow-up.
  Done: `art_id: int | None` (BigInteger) added to `Album` and `Track` in `app/db/models.py`;
  migration `0014_art_id.py` (guarded like 0002-0013 — no-ops on a fresh DB built from ORM
  metadata). `get_or_create_album`/`get_or_create_track` (`mapper.py`) take an optional `art_id`
  kwarg, set on create and set-if-null on the existing-row branch, same pattern as `url`/`title`.
  Threaded from all three real sources: `ingest_item` (fan-collection ingestion, both the album
  and track branches — `item.art_id` is the item's own art, not a parent album's), `ingest_album`
  (`pa.art_id`), and `ingest_track_page` (added `art_id` to `ParsedTrackPage` itself, populated
  from the same `tralbum.get("art_id")` `parse_album_page` already reads, since a standalone
  track/single page embeds the identical tralbum shape). `ParsedTrack` (an entry inside an
  album's own `trackinfo[]`) carries no `art_id` in Bandcamp's JSON at that level, so a track
  ingested via `ingest_album` only gets its art from a later fan-collection or track-page visit —
  not a gap this task invented, just the real shape of the source data.
  `GET /api/recommendations`'s `RecommendationOut` gained `art_id: int | None`, selected via
  `func.coalesce(Album.art_id, Track.art_id)` alongside the existing `url`/`title` coalesce.
  Verified against the real fixtures, not invented values: `tests/fixtures/album_page.html`'s
  `art_id` is `435129856` (also reachable via `fan_page.html`'s `item_art_id` for the same
  "Panchito" item), `track_page.html`'s is `3864705594`. Extended
  `test_ingest_album_populates_graph`, `test_ingest_track_page_populates_graph`, and
  `test_ingest_populates_graph` (fan collection — asserts the item's own art_id lands on its row,
  not a parent's) with `art_id` assertions against those real values; added
  `top["art_id"] == 99` to `test_recommendations_feed` (API-level, `test_api.py`'s existing `_seed`
  fixture, one Album given `art_id=99`). 248/248 backend tests pass, ruff clean; `alembic upgrade
  head` / `downgrade -1` / `upgrade head` round-trips clean against a fresh sqlite DB. PR: see git
  history.

- [x] **Cross-tenant guard test for `follows` scoping.** *(proposed by the hourly routine,
  2026-09-03, Architect+QA-approved — "pure pytest over shared Band/Album rows plus two
  Users/Fans, no live crawl/Docker/browser required ... small — one new test file, a handful of
  assertions")* CLAUDE.md notes `follows` used to leak across tenants until it got per-fan scoping
  (composite unique on `fan_id`+`band_id`), and `build_exclusions` was fixed to query
  `blacklist`/`likes` per-user — but there was no regression test pinning that two users'
  `follows`/`blacklist` rows stay isolated in curation, so a future edit could silently
  reintroduce the leak with no red test to catch it.
  Done: new `backend/tests/test_curation_tenant_isolation.py`. Two `User`+`Fan` pairs share the
  same global `Band` catalog rows (per the "graph stays global" model, the real shape two tenants
  see in practice) — user A gets a `Follow` row on Band X (fan-scoped) and a `Blacklist` row on
  Band Y (user-scoped), user B gets neither. Calls `curation.engine.build_exclusions` directly for
  each and asserts both bands land in A's own `exclusions.band_ids` (the inverse case — A's own
  exclusions do apply to A) while neither leaks into B's, despite both sharing the same `Band` rows.
  Confirmed the test actually catches the regression it's meant to, not just a happy-path
  assertion: temporarily stripped the `Follow.fan_id == me.id` filter from `build_exclusions` and
  reran — the test went red (`assert 1 not in {1}`) exactly as expected, then reverted. 249/249
  backend tests pass, ruff clean. PR: see git history.

- [x] **Construct `art_url` and expose it on `GET /api/recommendations`.** *(proposed by the
  hourly routine, 2026-09-03, Architect+QA-approved — "sound, pure function, one field wired
  through an existing query that already selects the underlying column, small"; a paired
  frontend-rendering proposal from the same round was explicitly CUT by QA — see below)* Direct
  follow-up to the `art_id` persistence item above, which deliberately stopped short of building a
  usable URL. `Album.art_id`'s own docstring in `app/db/models.py` already spelled out the
  formula (`f"https://f4.bcbits.com/img/a{art_id}_10.jpg"`) as the next step.
  Done: new `app/bandcamp/art.py::art_url(art_id: int | None) -> str | None`, an `art_id is None`
  check (not falsy — QA flagged that a hypothetical `art_id=0` must still build a URL, not be
  silently dropped like `None`). `RecommendationOut` gained `art_url: str | None`
  (`app/api/feed.py`), computed from the row's already-selected `art_id` at response-construction
  time — no new query/column, `art_id` was already coalesced from `Album`/`Track` by the prior
  item. Covered by 3 new tests in `test_bandcamp_art.py` (`None`→`None`, a real id→the expected
  URL, `0`→a URL, not `None`) and one assertion added to `test_api.py`'s existing
  `test_recommendations_feed` (already seeds `art_id=99`) confirming `art_url` on the response
  row. 252/252 backend tests pass, ruff clean.
  **Deliberately NOT done this run — frontend rendering, cut by QA**: a paired proposal to add
  `art_url` to `frontend/src/api/types.ts` and render an `<img>` in `FeedCard.tsx` was rejected —
  not because the conditional-render logic itself is untestable (RTL can confirm an `img` with the
  right `src` is present or absent), but because Bandcamp's `_10` art size is a large square with
  no existing sizing/`object-fit`/layout rule anywhere in the frontend to constrain it, so an
  unstyled `<img>` risks visibly breaking `FeedCard`'s existing flex layout — a real CSS/design
  decision with no objective pass/fail this browser-less sandbox can check. Left for a session
  with actual visual verification (a `run`/screenshot pass or Roy watching), per this routine's
  own "never pick a change whose only 'done' signal is visual taste" constraint. PR: see git
  history.

- [x] **Persist `Track.track_num` / `Track.duration`.** *(proposed by the hourly routine,
  2026-09-03, Architect+QA-approved — "sound, well-scoped, one-sitting change ... every claim in
  the brief checks out against the code")* Same shape as the `art_id` gap fixed earlier this run:
  `ParsedTrack` (an entry in an album page's `trackinfo[]`) has always parsed `track_num` and
  `duration`, but `Track` had no matching columns and `mapper.py` never read either field.
  Done: `track_num: int | None` and `duration: float | None` (Float) added to `Track`
  (`app/db/models.py`); migration `0015_track_num_duration.py` (guarded like 0002-0014, `tracks`
  table only — these are per-track, an album has no single duration). `get_or_create_track`
  gained `track_num`/`duration` kwargs (same set-if-null backfill idiom as `art_id`); threaded
  from `ingest_album`'s track loop only (`pt.track_num`, `pt.duration`) — deliberately **not**
  `ingest_track_page`, since `ParsedTrackPage` (the standalone `/track/<slug>` parse) carries
  neither field at all; Bandcamp doesn't expose a tracklist position/duration off-album, so
  there's nothing to thread there.
  **Deliberately schema-only this sitting, per Product's own scoping call (QA agreed)**: NOT added
  to `RecommendationOut`/`GET /api/recommendations`, unlike `art_id`→`art_url` earlier this run —
  the recs feed lists individual ranked items, not a rendered tracklist-with-position context, and
  no frontend surface currently reads either field. `art_id` got its API field alongside a real
  consumer (`art_url`) in the same sitting; these should wait for theirs (e.g. a track detail
  view, or duration-based curation weighting) rather than growing the API speculatively.
  Verified against the real fixture, not invented values: `tests/fixtures/album_page.html`'s one
  track is `track_num=1`, `duration=486.761`. Extended `test_ingest_album_populates_graph` with
  both assertions. 252/252 backend tests pass, ruff clean; `alembic upgrade head` / `downgrade -1`
  / `upgrade head` round-trips clean. PR: see git history.

- [x] **Export the current feed to CSV.** *(proposed by the hourly routine, 2026-09-03,
  Architect+QA-approved — "pure function, no external deps or fixtures needed, tested entirely
  with unit tests via round-trip through a CSV parser")* A companion "sort order" proposal from
  the same round was rejected before reaching QA: `useFeedFilters`/`FilterBar` already have a Sort
  dropdown (`score` / `neighbours` / `affinity`, `SortKey` in `api/types.ts`) — re-checked against
  the actual source, not a summary, precisely to avoid the duplicate-proposal failure mode logged
  twice already today in `tried-and-failed.md`. CSV export had no existing equivalent (checked via
  `grep -i 'csv|createObjectURL|download='`, zero hits) and was the one proposal that survived.
  Done: `lib/export.ts` — `formatRecommendationsAsCsv(recs): string`, a pure RFC-4180 formatter
  (rank/type/title/artist/score/co-owners/genre-match/url columns, CRLF rows, quote+comma+newline
  escaping) with no DOM or fetch dependency, plus a thin `downloadCsv(filename, csv)` DOM wrapper
  (Blob → object URL → temporary anchor click → revoke). Wired into `FilterBar.tsx` as an "⇩ Export
  CSV" button next to Liked/Blocked, disabled when there's nothing loaded. Exports `exportRows`
  (`ScanFeedPage`'s `visibleRows`) — deliberately the currently-loaded, currently-filtered page(s)
  already on screen, not a fresh full-result-set fetch, so it needed no new API surface. Covered by
  6 new tests in `export.test.ts` (a test-only RFC-4180 parser round-trips a comma, a quote, and an
  embedded newline back to the original string; header row; column count; null-field fallback;
  empty-list header-only output) and 2 new integration tests in `feed.test.tsx` (disabled with zero
  rows loaded; a click with one row calls `URL.createObjectURL` once with a `text/csv` Blob whose
  text contains the row, clicks the anchor, and revokes the URL). 255/255 frontend tests pass,
  tsc/lint/build clean (route chunk split intact). PR: see git history.

- [x] **Cover art on feed cards.** *(found by the hourly routine, 2026-09-03, via direct code
  audit — the migration `0014` docstring for `art_id`/`art_url` explicitly names this as its own
  intended next step: "Building an actual image URL from the id is a one-line format string for a
  future frontend-facing follow-up")* `GET /api/recommendations` has returned `art_url` per row
  since `art_id` landed (#111/#109), but nothing in the frontend read it — `Recommendation` had no
  `art_url` field and `FeedCard` rendered no `<img>` anywhere. A feed of bare score/title/band rows
  reads as unfinished next to any card-based app with real cover thumbnails.
  Done: `art_url: string | null` added to `Recommendation` (`api/types.ts`). `FeedCard.tsx` renders
  a 60×60 (44×44 on mobile, matching `.score`'s existing responsive breakpoint) `.card-art`
  thumbnail next to the score box when `rec.art_url` is present — same border/radius tokens as the
  score box, no new visual direction. `alt=""` (decorative — the adjacent title/artist text already
  identifies the item, so a real alt would be a redundant per-card screen-reader announcement); a
  failed load (missing `art_id`, a stale/404ing CDN URL) falls back to no image via `onError`,
  never a broken-image icon. Covered by 3 new tests in `FeedCard.test.tsx`: no image without
  `art_url`; an image with the right `src`/empty `alt` when present; `onError` removes it. 258/258
  frontend tests pass, tsc/lint/build clean (chunk split intact). PR: see git history.

- [x] **Notice when a scan's feed changed since your last visit.** *(proposed by the hourly
  routine, 2026-09-03, Architect+QA-approved with a correction)* Product's original pitch was
  per-item "new since last visit" badges off `recommendations.computed_at` — QA killed that:
  `store_recommendations` clear+inserts every recompute, so `computed_at` is stamped fresh on
  every surviving row on every recompute (a like, a block, an unrelated filter recompute), not
  just genuinely new items; badging on it would be a false-positive machine.
  Done (corrected version): keys off `recompute_generation` instead, the same per-scan "did the
  feed change" counter the existing in-session reflow banner already uses — but this is a
  different signal: the reflow banner only fires for a bump observed while the page is already
  open (a `useRef`, gone once the tab closes), while this persists a per-scan "last seen
  generation" to `localStorage` (`lib/lastSeenGeneration.ts`, same try/catch pattern as
  `visited.ts`), so it can say the feed moved on since your *previous* visit, not just this
  session. `features/feed/useUpdatedSinceLastVisit.ts` runs the check once per `scanId` (a
  `checkedFor` ref, same shape as `useResumeScroll`'s `restoredFor`), showing a dismissible
  banner (reuses the existing `.banner.reflow` styling) the first time a real prior visit's
  generation is behind the current one. Can only say "the feed changed", not which items —
  per-item novelty would need a `first_seen_at` set once via upsert-preserve rather than reset on
  every clear+insert, flagged as a separate, larger follow-up if wanted. Covered by 8 new unit
  tests in `lastSeenGeneration.test.ts` and 4 new integration tests in `feed.test.tsx`'s
  "updated-since-last-visit notice" block: silent on a scan's first-ever visit; shows and is
  dismissible when the generation moved on since the recorded visit; silent when it matches;
  persists the current generation so a same-session reload doesn't repeat it. 272/272 frontend
  tests pass, tsc/lint/build clean (chunk split intact). PR: see git history.

- [x] **Retry button on initial page-load failures.** *(proposed by the hourly routine,
  2026-09-03, Architect+QA-approved with a scope correction)* If the first fetch on
  `ScanListPage` or `ScanFeedPage` fails (network blip, transient 500), the page showed static
  red error text with no way to recover except a full browser reload — worse than the
  like/block/undo mutations, which already have a toast "Retry" action.
  Done, both pages per QA's scope correction: `ScanListPage.tsx`'s existing `<p className="err"
  role="alert">` got a `Retry` button re-calling the existing `load()` `useCallback` — the
  straightforward case, matching the ticket as first written. `ScanFeedPage.tsx` needed the
  separate fix QA flagged: its in-feed `error` state (and paragraph) only renders inside
  `{showFeed && (...)}`, which requires `scan !== null` — a failed *initial* `loadScan()` left
  `scan` permanently `null`, so that paragraph never rendered at all and the page sat silently
  on "Loading…" forever, with the retry-poll effect also bailing early on `!scan`. Added a new,
  separate `scanError` state (distinct from the existing `error`, which stays scoped to
  in-feed mutation failures — undo/renew/load-more) set only by `loadScan`'s own catch block,
  rendered as its own top-level `<p role="alert">…<button>Retry</button></p>` right under the
  page's nav, unconditional on `scan`'s value so a later poll failure surfaces too, not only
  the very first one.
  Covered by two new tests in `feed.test.tsx`'s "initial page-load failure" block: a failed
  `/api/scans` list load shows the alert + Retry button, and clicking it re-fetches and renders
  the real list once the mock is swapped to succeed; a failed `/api/scans/1` load on the feed
  page shows the same affordance while the heading is still stuck on "Loading…", and clicking
  Retry clears the alert and renders the scan once it succeeds. 275/275 frontend tests pass,
  tsc/lint/build clean (chunk split intact). PR: see git history.

- [x] **Warn before losing an in-progress scan draft.** *(proposed by the hourly routine,
  2026-09-03, Architect+QA-approved with two corrections)* A user can paste several seed URLs
  into `NewScanForm`, then accidentally reload or close the tab, losing the whole unsaved list
  with no warning — unlike almost every other data-entry flow in the app.
  Done, both QA corrections applied: a single `useEffect` in `NewScanForm.tsx` keyed on the
  derived boolean `hasDraft = seeds.length > 0` (not the `seeds` array reference, so
  adding/removing seeds doesn't tear the listener down and back up) adds a `beforeunload`
  listener that calls both `event.preventDefault()` and sets `event.returnValue = ''` — pairing
  both since some engines key off `returnValue` alone. No separate "just submitted" flag: a
  successful `create()` calls `onCreated()`, which unmounts this component synchronously
  (`ScanListPage`'s `setCreating(false)`), so the effect's own cleanup (`removeEventListener`)
  already covers that case for free.
  Covered by three new tests in `NewScanForm.test.tsx`'s "draft-loss warning" block, each
  dispatching a synthetic `beforeunload` `Event` on `window` with a `preventDefault` spy (jsdom
  doesn't fire the event natively, but a manually-dispatched event is the standard way to test
  this, matching how this codebase already tests other window-level listeners): warns once a
  seed has been added (`preventDefault` called, `returnValue` falsy — asserted as falsy rather
  than the exact empty string, since jsdom's `Event.returnValue` coerces any assigned value to a
  boolean where real browsers keep the assigned string); does not warn with an empty seed list;
  stops warning once the last seed is removed. 276/276 frontend tests pass, tsc/lint/build clean
  (chunk split intact). PR: see git history.

- [x] **Add a request timeout to `api/client.ts`.** *(proposed by the hourly routine,
  2026-09-03, Architect+QA-approved with a value correction)* `request()` — the single
  chokepoint every API call goes through — called `fetch()` with no `AbortController`/timeout at
  all. The existing `catch` block only fires on outright fetch rejection (DNS/connection
  failure); a hung-but-accepted connection (a dead proxy, a backend that accepts the TCP
  connection but never responds) never rejects on its own, so it left the caller's loading state
  stuck forever with zero feedback — not even helped by this run's own Retry button, since
  nothing ever reaches its catch block to show it.
  **QA correction, applied:** QA's own suggested 30-45s timeout would still have been too short —
  `AuthContext.tsx`'s existing comment documents the Render free tier's cold-start window as
  "~30-60s," so a 45s timeout could still misfire as a false "request timed out" during an
  ordinary cold start, the exact case the pre-existing network-failure message already explains
  correctly. Used `REQUEST_TIMEOUT_MS = 90000` (new in `config.ts`) instead, comfortably above the
  documented window.
  Done: `request()` creates an `AbortController` per call, passes `signal` to `fetch()`, and
  `window.setTimeout`s an abort at `REQUEST_TIMEOUT_MS` — cleared in a `finally` block on every
  path (QA's other correction: an uncleared timer leaks on every successful/normal-error request,
  not just a timed-out one). The `catch` block now checks for `DOMException`/`AbortError`
  specifically and throws a distinct `ApiError(0, 'The request timed out. Please try again.')`
  before falling through to the existing generic "can't reach the server" message. No caller
  runs deliberately long over this chokepoint to worry about: confirmed `POST
  /api/scans/{id}/run` just flips status and returns immediately (the crawl itself runs
  out-of-band via the ARQ poller), and recompute is a DB-bound scoring pass, not a scrape.
  Covered by two new tests in `client.test.ts`'s "request timeout" block: a `fetch` mock that
  only rejects once it observes the passed `signal`'s `abort` event (a bare never-resolving mock
  would just hang forever under fake timers, per QA's note — this one actually exercises the
  abort wiring) confirms the call rejects with the timeout message only after `vi.
  advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS)`; a second test confirms a normally-resolving
  call is unaffected. 269/269 frontend tests pass (stable across repeated runs — one transient,
  unrelated command-palette flake in a single mixed run did not reproduce on rerun or in
  isolation), tsc/lint/build clean (chunk split intact). PR: see git history.

- [x] **Cap the Liked/Blocked side-panel lists.** *(proposed by the hourly routine, 2026-09-03,
  Architect+QA-approved)* `LikedPanel`/`BlockedPanel` (`SidePanels.tsx`) render every liked/
  blocked item with no cap — likes/blocks are per-user and accumulate forever (blocks even
  longer since most have no expiry), so the panel just keeps growing.
  A first proposal from the same round — a dedicated "not found" page for a bad/deleted scan
  link — was self-caught as already covered before spending an Architect+QA call:
  `ScanFeedPage.tsx`'s `scanError` state already renders a `role="alert"` message with a Retry
  button whenever `api.getScan` fails, alongside the existing "← Scans" link back.
  Done: new `SIDEPANEL_PAGE_SIZE` (20) in `config.ts`. Both panels keep a local `visibleCount`
  `useState`, slice their (for `BlockedPanel`, already-sorted) items array to it, and show a
  "Show more" `btn ghost` button that grows the count by another page — plain client-side
  slicing, no new API call, no change to either panel's existing props. Covered by five new
  tests in the new `SidePanels.test.tsx` (standalone RTL render, no router/api mocking needed —
  neither panel has any dependency of its own): each panel with 30 fake items renders exactly
  20 rows plus a "Show more" button; clicking it reveals all 30 and removes the button; a list
  of 5 items (under one page) never shows the button at all. 274/274 frontend tests pass,
  tsc/lint/build clean (chunk split intact). Merged same run (PR #127). PR: see git history.

- [x] **Add a React error boundary.** *(proposed by the hourly routine, 2026-09-03,
  Architect+QA-approved)* Self-found via `grep -rn 'ErrorBoundary|componentDidCatch'` across
  `frontend/src` — zero hits. The app had no error boundary anywhere: an uncaught render-time
  exception in any component (a malformed API response causing a null-access, or any other
  render bug) white-screened the entire app with no fallback, taking down even the
  `ToastStack`/`OfflineBanner` layer that could otherwise have explained it.
  Done: new `components/ErrorBoundary.tsx` — a small class component (`getDerivedStateFromError`/
  `componentDidCatch` have no hook equivalent) rendering a "Something went wrong." message with a
  `btn` "Reload" button (`window.location.reload()`) on catch; the caught error/info is logged to
  `console.error` since there's no error-reporting service to send it to. Wraps the signed-in
  shell's routed `<main>` in `App.tsx`, inside the existing `<Suspense>` boundary — a render error
  in a lazy-loaded route page is caught the same as one in an already-loaded component. The
  signed-out shell (login/signup) is left unwrapped: its two pages are simple and already
  `Suspense`-guarded, and wrapping it would mean a second boundary with no shared benefit.
  Covered by two new tests in `ErrorBoundary.test.tsx` (standalone RTL render, no router/api
  mocking needed): a throwing child renders the fallback text and Reload button instead of
  crashing the test (console.error mocked for these two, since React logs the caught error in
  addition to calling `componentDidCatch` — jsdom has no dev-server error overlay to swallow it);
  a non-throwing child renders normally with no fallback shown. 271/271 frontend tests pass
  (one transient, unrelated command-palette-adjacent flake did not reproduce on rerun, matching
  the flake already logged against the previous item), tsc/lint/build clean (lands in the
  eagerly-loaded shared chunk via `App.tsx`, not a lazy route chunk, as expected for a boundary
  that must exist before either route renders). Merged same run (PR #128, after a merge conflict
  with #127 in this same file — resolved by keeping both entries). PR: see git history.

- [x] **Duplicate seed URL gives no feedback.** *(proposed by the hourly routine, 2026-09-03,
  Architect+QA-approved)* `features/scans/NewScanForm.tsx`'s `addSeed()` (line 44-54) called
  `setError('')` and `setSeedUrl('')` unconditionally even when `seeds.includes(u)` was already
  true — re-adding a URL already in the list silently no-opped, so it looked like the Add click
  didn't register.
  Done: `addSeed()` now checks `seeds.includes(u)` before the dedupe-and-add, and on a hit calls
  `setError('Already in your seed list.')` and returns without touching `seedUrl` — the
  offending text stays in the input instead of being silently cleared. The multi-line paste path
  (`onSeedPaste`) is untouched; it already dedupes silently by design with its own test coverage,
  and this fix only changes the single-URL Add/Enter path.
  Covered by a new test in `NewScanForm.test.tsx`'s "seed URL validation" block: add a seed via
  the Add button, add the identical URL again, assert `role="alert"` shows "Already in your seed
  list." and the seed list is still exactly one `listitem`. 277/277 frontend tests pass,
  tsc/lint/build clean (chunk split intact). Merged PR #129.

- [x] **Command palette arrow-key nav doesn't scroll the active row into view.**
  *(proposed by the hourly routine, 2026-09-03, Architect+QA-approved)*
  `components/CommandPalette.tsx`'s `onInputKeyDown` (line 117-128) moved `activeIndex` but
  nothing called `scrollIntoView` on the newly active row — on a longer filtered list, arrowing
  down past the visible rows highlighted an option the user couldn't see.
  Done: a new effect right after `activeRow`'s definition, keyed on `[open, activeRow]`, looks
  up the active row by `cmdk-opt-${activeRow.id}` (the id every row already carries for
  `aria-activedescendant`) and calls `.scrollIntoView({ block: 'nearest' })`. Both the element
  lookup and the method call use optional chaining (`?.scrollIntoView?.(...)`) since jsdom
  doesn't implement `scrollIntoView` at all — a real DOM element always has the method, so this
  is a no-op difference outside tests, not a defensive hedge against real browsers lacking it.
  Covered by a new test in `CommandPalette.test.tsx`: stubs `Element.prototype.scrollIntoView`
  with `vi.fn()`, opens the palette (clearing the initial mount call for row 0), presses
  ArrowDown, and asserts the mock was called with `{ block: 'nearest' }`. 277/277 frontend tests
  pass, tsc/lint/build clean (chunk split intact). PR #130 (this change).

- [x] **Block reason has no UI.** *(proposed by the hourly routine, 2026-09-03,
  Architect+QA-approved — "sound and small; the backend contract (`Blacklist.reason` /
  `POST /api/blacklist` / `Blocked.reason`) already exists end-to-end and is tested, this is
  purely additive frontend wiring")* Found via direct code audit after two prior Product
  proposals this run turned out to be duplicates on inspection (free-text search — already
  `lib/quickFilter.ts`'s `matchesQuery`; "snooze a rec" — already the `blacklist.expires_at`
  auto-expiry mechanism; both logged in `tried-and-failed.md`). `Blacklist.reason` was wired
  through the backend and typed on the frontend (`Blocked.reason: string | null`) but nothing
  ever set or displayed it — dead plumbing. A companion "pre-block confirm on a single card"
  proposal from the same round was cut by Architect+QA: the existing 6s Undo banner already
  covers the same mis-click failure mode for a single card with less friction than a confirm
  dialog would add to every correct block.
  Done, entirely frontend (no backend/migration needed — the API already accepts and returns
  `reason`): `client.ts`'s `block()` gained an optional third `reason` param, folded into the
  existing POST body. `SidePanels.tsx`'s `BlockedPanel` gained a new `onSetReason` prop and,
  per row, a compact `input.reason` (`feed.css`, fixed 140px width — a dense row already packs
  band name/expiry/renew/unblock, so the full-width `.input` base wouldn't fit) prefilled with
  any existing reason, saved on Enter (mirroring the seed-URL/genre-add Enter-to-submit
  convention elsewhere in the app); an existing reason also renders inline next to the expiry
  text. `ScanFeedPage.tsx`'s new `setBlockReason(bandId, reason)` mirrors the existing `renew()`
  shape exactly, including its one necessary wrinkle: `POST /api/blacklist` overwrites
  `expires_at` unconditionally on every call, so setting a reason on an already-temporarily-
  blocked band reads its current `expires_at` back out of `blocked` state and passes it straight
  through — otherwise attaching a reason would silently convert a temporary block into a
  permanent one. Backend only overwrites an existing row's `reason` when the new value is
  non-empty (`blacklist.py`'s `if payload.reason:`), so a blank/unchanged Enter is a no-op on
  the frontend side too rather than firing a wasted request. Covered by four new tests in
  `SidePanels.test.tsx`'s "BlockedPanel reason" block: an existing reason renders next to the
  band; an empty reason shows an empty, correctly-labeled input; typing a new reason and
  pressing Enter calls `onSetReason` with the trimmed text; Enter with unchanged or
  whitespace-only text does not call it. 282/282 frontend tests pass, tsc/lint/build clean
  (chunk split intact — lands in the existing `ScanFeedPage` chunk). PR: see git history.

- [x] **Login has no lockout/rate-limit.** *(proposed by the hourly routine, 2026-09-03, via the
  same Explore-backed Product round that found the block-reason gap above — Architect+QA-approved
  with one correction)* `app/api/auth.py`'s `login()` did a bare password check with zero attempt
  tracking — the only rate limiter in the codebase (`app/scraping/ratelimit.py`) is for the
  unrelated Bandcamp-scraping token bucket, not auth — and this app is publicly reachable
  (Render), so it was an unbounded online password-guessing exposure. QA's one correction: use a
  `locked_until: datetime | None` column (mirroring `Blacklist.expires_at`'s shape — expiry is a
  plain timestamp comparison at read time) rather than a boolean, since a boolean can't expire on
  its own without a third column.
  Done: `User` gained `failed_login_attempts: int` (default 0) and `locked_until: datetime | None`
  (migration `0016_login_lockout`, guarded like 0002-0015). New `Settings.auth_login_max_attempts`
  (default 5) / `auth_login_lockout_minutes` (default 15) — tunable without a redeploy-and-migrate
  cycle, per QA. `login()`: a locked account gets 429 with `verify_password` skipped entirely
  (both to avoid wasted bcrypt work under a guessing attempt and, more importantly, so a locked
  account never leaks whether the password would otherwise have been right); a failed verify
  increments the counter and sets `locked_until` once the threshold is hit; a successful login
  resets both to 0/`None`. Concurrent-request races on the counter (a lost update letting one or
  two extra attempts slip through) were flagged by QA and accepted as-is — not worth
  `SELECT ... FOR UPDATE` for a 5-attempt threshold on a small invite-only app. Covered by 4 new
  tests in `test_auth.py`: locks out after the 5th failed attempt (429 even with the *correct*
  password on the 6th try, so a 401-vs-429 split can't be used to fish for validity); a successful
  login below the threshold resets the counter (verified both via a direct DB read and by
  confirming 3 more failures, not 2, are needed to re-trigger); a lockout clears once its window
  has passed (same "write a past timestamp directly" convention as
  `test_expired_blacklist_stops_excluding` — no clock mocking); the threshold is actually driven
  by `Settings`, not hardcoded (a custom `auth_login_max_attempts=2` locks after 2). 258/258
  backend tests pass, ruff clean; `alembic upgrade head` / `downgrade -1` / `upgrade head`
  round-trips clean against a fresh sqlite DB. PR: see git history.

- [x] **Cold-start panel doesn't show the crawl budget.** *(found by the hourly routine,
  2026-09-03, via direct code audit — same "wired backend field, no frontend consumer" pattern
  that turned up "Block reason has no UI" this run, see PR #131)* `GET /api/stats`'s
  `requests_used`/`request_budget` were typed on the frontend (`Stats.requests_used`/
  `.request_budget`) and already fetched — but only in the one case where `ScanFeedPage` calls
  `loadStats()` at all: `total === 0` (the cold-start/empty-feed case, see "Cold-start feeds give
  no reason, just emptiness" above) — and never rendered. That's exactly the situation where
  knowing "the crawl has used 743 of 1,000 requests this scan" is most useful: it tells a reader
  looking at an empty feed whether the crawl is still running (budget has room) or has already
  used up what it's allowed to spend (budget exhausted), instead of just looking sparse with no
  explanation.
  Done: `ColdStartPanel` gained two optional props, `requestsUsed`/`requestBudget`, rendering a
  "N of M crawl requests used this scan." line (reusing the same `count()`/`.num` formatting as
  its existing counts) on both branches (no-neighbours-yet and the exclusion-breakdown case) when
  both are present and the budget is nonzero; absent/zero renders nothing extra, so an unrelated
  caller (or a test) that doesn't pass them is unaffected. Threaded straight through
  `EmptyState`'s existing `coldStart` pass-through prop, from `ScanFeedPage`'s already-fetched
  `stats.requests_used`/`stats.request_budget` — no new fetch, no new API surface. Covered by 4
  new tests in `ColdStartPanel.test.tsx`'s "crawl-budget line" block (renders on both branches
  when provided; absent when the values are missing or the budget is zero), 1 new test in
  `EmptyState.test.tsx` (pass-through), and an extension of the existing cold-start integration
  test in `feed.test.tsx` (asserts the full rendered budget line's text, not a bare number — the
  mock's `requests_used: 40` collides with its own `cold_start.excluded_wishlisted: 40` as an
  exact-text match, so the assertion checks the whole sentence instead of a standalone `'40'`).
  283/283 frontend tests pass, tsc/lint/build clean (chunk split intact). PR: see git history.

- [x] **Stale comments claimed `FeedCard` has a block-duration picker.** *(found by the hourly
  routine, 2026-09-03, via direct code audit)* `FeedCard.tsx`'s `onBlock` prop doc and `config.ts`'s
  `BLOCK_DURATIONS` doc both described a "block for… ▾" picker on the feed card itself — but that
  picker was deliberately removed from `FeedCard` in #103 (a real product decision, not a
  regression; only `SidePanels`' "renew ▾" action on an already-temporary block still uses
  `BLOCK_DURATIONS`/`expiresAt`). Already flagged as a stale-doc risk in
  `team/memory/tried-and-failed.md` — left uncorrected, a future round could mistakenly re-propose
  "resurrecting" a feature Roy explicitly rejected.
  Done: reworded both comments to describe the current, real wiring. Comment-only change; 287/287
  frontend tests pass, tsc/lint/build clean. Merged (#134).

- [x] **Dead `COPY_LINK_FEEDBACK_MS` constant + `ShortcutsHelp` missing the Ctrl/Cmd+K row.**
  *(found by the hourly routine, 2026-09-03, via direct code audit)* `config.ts`'s
  `COPY_LINK_FEEDBACK_MS` was orphaned when `CopyLinkButton`/`CopyMarkdownButton` were removed in
  #107 — confirmed via a repo-wide grep, its only remaining reference was its own declaration.
  Separately, `ShortcutsHelp`'s panel lists `l`/`b`/arrows/Home/End/`/`/`?` but never mentioned
  `Ctrl`/`Cmd`+`K`, even though `CommandPalette` is mounted globally and live on the same page.
  Done: deleted the dead constant; added the missing shortcuts row plus a test assertion. 287/287
  frontend tests pass, tsc/lint/build clean (chunk split intact). Merged (#135).

- [x] **Collection-scan neighbour seeding ignores owned standalone tracks.** *(found by the hourly
  routine, 2026-09-04, via direct code audit)* `_seed_ids()` (`app/curation/engine.py`) only pulled
  seed ids from owned albums for the `COLLECTION` scan kind (your primary "My collection" feed) —
  an owned standalone track never contributed to `seed_track_ids`, even though downstream
  (`_scan_neighbours`, the `CUSTOM` scan branch) was already fully track-aware. Net effect: if you
  own a standalone track, that track's supporters silently never became your taste-neighbours in
  your primary feed — a real loss of co-ownership signal, no error.
  Done: mirrored the existing `album_ids` query with an identical `track_ids` one.
  `neighbour_size_report`/`cold_start_diagnostics` also benefit, since they share `_seed_ids`. New
  `test_collection_scan_owned_track_finds_neighbours` confirmed red before the fix, green after.
  259/259 backend tests pass, ruff clean. Merged (#136).

- [x] **`DELETE /api/scans/{id}` orphans `crawl_frontier`/`provider_usage` rows.** *(found by the
  hourly routine, 2026-09-04, via direct code audit)* Neither `CrawlFrontier.scan_id` nor
  `ProviderUsage.scan_id` declares `ondelete="CASCADE"` (unlike `ScanSeed`/`Recommendation`, which
  do), and `delete_scan` never cleaned them up itself — any scan that has actually run at least
  once has rows in both tables, so deleting it on Postgres (the real deployment target) raises an
  unhandled `IntegrityError` (500) instead of succeeding. On SQLite (tests, no FK pragma) the
  delete instead silently orphans the rows. The only existing delete test deleted a scan
  immediately after creation, before either table had rows, so this was untested.
  Done: mirrored the existing explicit `Recommendation` delete with two more explicit deletes
  (`CrawlFrontier`, `ProviderUsage`) before `session.delete(scan)`. New
  `test_delete_scan_drops_frontier_and_usage_rows` confirmed red before the fix, green after.
  260/260 backend tests pass, ruff clean. Merged (#137).

- [x] **A typed block reason is silently discarded unless you press Enter.** *(proposed by the
  hourly routine, 2026-09-04, Architect+QA-approved with a caveat)* `SidePanels.tsx`'s
  `BlockedPanel` reason input only committed on `Enter` (`onKeyDown`) — clicking away, tabbing to
  the next control, or closing the panel dropped whatever was typed with no save and no warning.
  A second Product proposal from the same round ("wire up the already-dead `recsToMarkdown` into a
  Copy-as-Markdown button") was caught and dropped before building — see
  `team/memory/tried-and-failed.md`, it would have reintroduced a feature Roy explicitly asked
  removed in #107.
  Done: extracted the existing Enter-commit logic into a shared `commitReason()` and wired it to a
  new `onBlur` handler too. QA flagged a real race first: disabling the input mid-save (the
  existing `disabled={rowBusy}`) itself fires a browser blur event, which would otherwise
  re-submit the same value a second time while the Enter-triggered save is still in flight — guarded
  by skipping the blur commit whenever `rowBusy` is true. No success toast added (scope check found
  the row's own `· "reason"` text already updates once the save lands, via the same `loadBlocked()`
  every sibling action — `renew`/`unblock` — already uses without a toast either, so adding one here
  would have been an inconsistency, not a fix). Covered by three new tests in `SidePanels.test.tsx`:
  blur commits a changed, non-blank reason; blur with unchanged/blank text does not; blur while the
  row's own save is already in flight does not double-submit. 290/290 frontend tests pass,
  tsc/lint/build clean (chunk split intact). PR: see git history.
