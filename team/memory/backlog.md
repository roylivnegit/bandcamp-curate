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

- [ ] **Feed filters belong in the URL.** `useFeedFilters` lives in `useState`, so a filtered
  view can't be shared or bookmarked, and browser-back silently drops it. Move it onto
  `useSearchParams`. Same source in `frontend/CLAUDE.md`.

- [ ] **Verify contrast on hint text.** `--faint: #667085` on `--surface: #141823` is the
  likeliest AA failure in the palette and nobody has measured it. Compute the real ratio; if it
  fails, adjust the token once, everywhere. Same source.

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
  **Left open:** no frontend surfacing yet — the data is in `/api/stats` but nothing in
  `frontend/` reads `cold_start` yet. A follow-up can add the "why is my feed empty" UI on
  top of this without touching the backend again.

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
