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

- [ ] **Conditional GET (ETag) on `/api/recommendations` and `/api/facets`.** *(proposed by the
  hourly routine, 2026-09-02, Architect+QA-approved with a correction)* Every feed poll re-transfers
  the full payload even when nothing changed. Set `ETag: gen-{scan_id}-{generation}` on both
  responses (reusing `scans.recompute_generation` — no new state, corrected from the Product
  proposal's global `gen-{generation}`, since generation is per-scan); a matching `If-None-Match`
  returns `304` with no body. Verify: `pytest` — GET recs, assert `ETag: gen-{scan_id}-N`; repeat
  with `If-None-Match` set to that value, assert `304` + empty body; recompute (bumps generation),
  repeat, assert `200` with a new ETag.

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
