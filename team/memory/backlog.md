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
