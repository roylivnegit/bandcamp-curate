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

- [ ] **E0-5 · Branch protection.** Require the E0-3 checks on `main`, allow auto-merge,
  block force-push.
  *Why:* this is what makes the gate real rather than self-reported.
  **Blocked on Roy** — needs admin on the repo.

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

- [ ] **Make the order mean something, not the length.** Roy wants a long list kept — do not
  cut the feed down. The actual problem is ranking, not volume: work out whether the ranking
  is too flat, the co-ownership signal too weak, or ties too common, then sort by relevancy
  so the *best* matches are reliably at the top even with ~1,600 items sitting underneath.
  Measure: does the top of the list hold up — does Roy find something worth clicking near
  the top, not just somewhere in a long scroll.

- [ ] **Tag coverage caps tag-affinity.** Tags live on album *pages*, which the crawl mostly
  does not fetch, so the genre signal is sparse and the "via …" explanations are thin.
  Options: enrich top recs only, derive from `band_tags`, or find a cheaper source of genre.
  See `CLAUDE.md` (M4 Curation).

- [ ] **Mega-supporters flatten the signal.** A collector who owns 8,000 records co-owns
  everything with everyone. Score their overlap lower than a collector with 200 records and a
  40% overlap with Roy. Worth measuring before building.

- [ ] **Explanations Roy can trust.** A rec with a reason he believes gets clicked; a bare
  score does not. `reasons.seed_tags` already exists — build on it.

- [ ] **Second source: research first.** Beatport, SoundCloud, Discogs, Resident Advisor.
  Which of these exposes, without login and without paying: an artist's related artists, a
  release's buyers or likers, or a genre chart? Writes findings to `memory/research/`. Do not
  start building a provider before that note exists.
  **Real Nimble usage now authorized for this item specifically** (2026-09-01), POC only,
  capped at 100 requests total — see `team/memory/research/nimble-usage.md` for the running
  count, kept up to date every time this key is spent. Stop and ask Roy (email or in-session)
  before going over 100; do not keep going past the cap on your own judgment. This is the
  ONLY backlog item this key may be used for.

- [ ] **Per-user crawl budgets.** `crawl_max_requests` and `provider_usage` are global, so one
  user's deep scan starves everyone else's. From `CLAUDE.md` "Immediate next steps".

- [ ] **A secondary budget cap** — max total frontier size, or max fetches per run, on top of
  the depth bound. Depth 3 on a popular album still fans out very wide. Same source.

- [ ] **Retire the legacy operator crawl chain.** `seed_crawl` / `crawl_next` /
  `scripts/crawl.py` still key off the single global `BANDCAMP_FAN_URL`. Documented as
  operator-only, which is a comment, not a guard rail. Same source.
