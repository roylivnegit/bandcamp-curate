# ADR-0001 — Cut the feed by requiring more than one stranger

- **Cycle:** 2026-08-23T0726-c003
- **Status:** proposed (Lead ruled `build`, assignee backend-dev)
- **Slug:** `curation-co-ownership-floor`

## Problem

One stranger owning a record is enough to call it a recommendation. `engine.py:355-366` and
`engine.py:404-416` group `fan_items` by item over this scan's neighbours with no minimum, and
`engine.py:386` scores a single co-owner at 1.0 — so a 1,600-row feed is mostly items where
exactly one collector agreed with Roy once. `one_per_band` dedup (`engine.py:441`) shrinks the
list but not the noise: it picks the top item per band, it does not require agreement. We want
a floor on how many distinct neighbours must own an item before it is a rec, shipped so that
today's behaviour stays the default and the new behaviour is measurable against it.

## Approach, and the seam it lives behind

The floor is a **threshold on the candidate queries**, not a new filter and not a new module.

- `compute_recommendations` gains two keyword params: `min_co_owners: int | None = None`,
  `min_neighbours_for_floor: int | None = None`. `None` means "read `get_settings()`".
  Config is read at one edge only. `get_settings` is `@lru_cache`d (`app/config.py:130`), so
  tests pass explicit ints rather than mutating env.
- New settings: `curation_min_co_owners: int = 1`,
  `curation_min_neighbours_for_floor: int = 25`. Default 1 is today's behaviour; the new path
  is opt-in via env.
- The floor is **active** iff `min_co_owners > 1 AND len(neighbours) >= min_neighbours_for_floor`.
  When it is not active, **no `HAVING` clause is added at all** — the default path emits the same
  SQL it emits today, so parity is structural, not just arithmetic.
- When active, `.having(func.count(func.distinct(FanItem.fan_id)) >= floor)` is appended to
  **both** grouped queries — albums (`engine.py:355-366`) and tracks (`engine.py:404-416`).
  Both, because `one_per_band` runs *after* scoring (`engine.py:441`): an album-only floor lets
  a band we just cut walk back in through a 1-co-owner track, which both understates the measured
  cut and shifts the album/track mix. Tracks have no tag term (`engine.py:434`), so at equal
  co-owner count a track always ranks below its album — the mix shift would be invisible in the
  top of the feed and visible in the tail.
- 25 neighbours is the gate because one popular album's supporter page yielded 17 neighbours on
  the live 2026-07-24 run (CLAUDE.md, M3). Below ~25, "two independent strangers" is a sampling
  artefact of how much we happened to crawl, not agreement.

**Observability.** `compute_recommendations` and `curate` take an optional `stats_out: dict | None`
which is filled with `min_co_owners`, `neighbours`, `floor_applied`,
`bands_cut_no_multi_co_owner`. `scan_service.py:366` and `scan_service.py:437` pass a dict and
merge it into `scan.stats` (already JSON — no schema change). Without this, an empty feed and a
too-high floor look identical on a later read, and the whole point of the cycle is measurement.

`bands_cut_no_multi_co_owner` is computed **only when the floor is active**, by two extra grouped
queries of the same shape with `HAVING count(...) < floor`, selecting the same columns so they run
through the same exclusion predicates, then subtracting the band ids that survived. Cost: two extra
aggregate scans per curate when the floor is on, no tag loading. It exists because per-item
flooring throws away band-level agreement — a band with three albums each owned by a different
single neighbour is cut entirely at floor 2, even though three distinct neighbours own something
by that band. That is real signal, and the write-up must report it next to feed size rather than
let the feed reduction look better than the taste improvement is.

**Guard fix (Lead's scope call).** `run-cycle.sh:69` and `cycle.py:897-900` both match the strings
`neon`/`render`/`amazonaws` — a denylist, which passes any other hosted host. Replace with one
allowlist function `db_url_is_local(url)` in `team/tools/cycle.py` (allow: empty, `sqlite`/file
URLs, host in `localhost`/`127.0.0.1`/`::1`) plus a `--check-db-url` entry point that exits
non-zero when the URL is not local. `run-cycle.sh` calls that entry point instead of restating the
match, so the allowlist exists in exactly one place and cannot drift between the two languages.
Any error in the check (missing python, import failure, unparseable URL) refuses to run.

## Invariants it must not break

Check these against the diff, one by one:

1. **The floor is applied in both candidate queries and nowhere else.** `HAVING` appears on the
   album query and the track query. No `if co_owners < floor: continue` anywhere in the scoring
   loops, no filtering in `store_recommendations`, no filtering in the API layer.
2. **`build_exclusions` is untouched and remains the only place exclusions are decided.** The
   floor is a threshold on co-owner count, not a new exclusion path. `app/curation/` exclusion
   code shows no diff other than call-site plumbing.
3. **The default config reproduces today's feed exactly.** With `curation_min_co_owners = 1`,
   no `HAVING` is emitted and the recommendation set on the existing fixture graph is unchanged,
   row for row.
4. **A band cut at album level does not reappear as a track.** With floor 2, a band whose only
   items are a 1-co-owner album and a 1-co-owner track produces zero recs.
5. **The floor counts distinct neighbour fans only.** The count stays
   `count(distinct FanItem.fan_id)` over the `fan_id.in_(neighbours)` set — Roy's own fan row and
   non-neighbour fans never contribute to clearing the floor.
6. **Scores are unchanged.** `W_CO_OWNER`/`W_TAG_AFFINITY` and the two score expressions
   (`engine.py:386`, `engine.py:434`) are byte-identical. This change removes candidates; it does
   not re-rank survivors.
7. **Every curate records what floor it used.** Both `scan_service.py:366` and `:437` write
   `min_co_owners`, `neighbours` and `floor_applied` into `scan.stats`. A run with a thin feed is
   distinguishable from a run with a high floor without reading the code.
8. **No schema change, no migration, no data alteration.** `alembic/versions/` has no new file.
9. **`grep -rn 'neon' team/tools/` finds no host guard.** The allowlist lives in exactly one
   function; the shell guard calls it rather than restating it, and fails closed on any error.
10. **Nothing in the diff can spend a credit.** No `/extract`, no scan start, no worker drain, no
    new call into `app/scraping/`.

## What changes

- `backend/app/config.py` — `curation_min_co_owners: int = 1`,
  `curation_min_neighbours_for_floor: int = 25`, each with a comment saying why.
- `backend/app/curation/engine.py` — `compute_recommendations` gains `min_co_owners`,
  `min_neighbours_for_floor`, `stats_out`; conditional `.having(...)` on both grouped queries;
  the cut-band diagnostic; `curate` threads the same three params through.
- `backend/app/crawl/scan_service.py:366` and `:437` — pass `stats_out` and merge into `scan.stats`.
- `team/tools/cycle.py` — `db_url_is_local()` + `--check-db-url`; preflight uses it.
- `team/tools/run-cycle.sh:69` — calls `--check-db-url` instead of the string denylist.
- `backend/tests/test_curation.py` — the four curation tests below.
- `backend/tests/test_team_guards.py` (new) — the guard tests below.
- Tables: none. Endpoints: none (`/api/recommendations` and `/api/scans` shapes unchanged;
  `scan.stats` gains keys, and `app/api/scans.py:43` already passes `stats` through as an open dict).

## Tests

1. **Parity.** floor=1 (default) on the existing fixture graph returns the same recommendations as
   before the change — same count, same ids, same order.
2. **Floor cuts both item types.** One graph, one band, a 1-co-owner album and a 1-co-owner track:
   both present at floor=1, neither present at floor=2 after `one_per_band`.
3. **Neighbour gate, both sides.** 24 neighbours → floor inactive (item with 1 co-owner survives);
   25 neighbours → floor active (it does not). Pinned as two cases, not one.
4. **Stats.** A curate run writes `min_co_owners`, `neighbours`, `floor_applied` and
   `bands_cut_no_multi_co_owner` into `scan.stats`, and `bands_cut_no_multi_co_owner` does not
   count a band that `build_exclusions` already excluded.
5. **Guard allowlist.** Parametrised over `localhost`, `127.0.0.1`, sqlite, empty (all pass) and a
   Neon URL, a Render URL, and `postgres://u:p@db.some-other-host.com/x` (all refuse). The
   last one is the case the denylist got wrong. Includes one subprocess call of the real
   `--check-db-url` entry point asserting a non-zero exit, so the shell path is covered too.

All of this runs on the existing sqlite in-memory fixture (`test_curation.py:35-37`). No Postgres,
no sandbox database, no credits.

## Rollback

Single `git revert` of the PR. No migration, no data written that a revert leaves behind:
`store_recommendations` clears and re-inserts a scan's recs wholesale (`engine.py:458-472`), so the
next curate after a revert restores the unfloored feed. The extra keys left in `scan.stats` from a
floored run are inert JSON. Before a revert is even needed, setting
`CURATION_MIN_CO_OWNERS=1` makes the change a no-op at runtime.

## Rejected

- **Neighbour weighting by overlap ÷ collection size.** The denominator is *what we ingested*, not
  what the fan owns. `service.PAGES_PER_VISIT = 10` parks collections back as PENDING mid-
  pagination and `Fan` (`app/db/models.py:124-137`) carries only `last_crawled_at` — no
  completeness or item-count column. A half-crawled 8,000-record completionist therefore reads as
  a 400-record high-overlap curator, and the weighting inverts exactly the ranking it is meant to
  fix. Revisit when a per-fan completeness signal exists, and use raw overlap count (monotone
  under a partial crawl) rather than a ratio.
- **A post-filter in the scoring loop.** Simpler to write, but it puts the threshold in a second
  place, keeps `_album_tags`/`_tag_names` (`engine.py:373-375`) loading tags for candidates we are
  about to drop, and invites a future third place. The `HAVING` shrinks the candidate set before
  any of that work happens.
- **Band-level agreement instead of per-item.** It is the better signal and it is the named
  follow-up — but it changes what a candidate *is*, and both grouped queries group by item, never
  by band (`engine.py:366`, `engine.py:415`). That is a scoring-pass restructure, which the Lead
  put out of scope. We measure the cost of not having it (`bands_cut_no_multi_co_owner`) so the
  follow-up starts with a number.
- **Defaulting the floor to 2.** It would cut the feed on the next run without anyone comparing
  the two, and the charter wants precision *measured*, not asserted. Default 1 keeps today's
  behaviour as the control.
- **Making the floor relative to neighbour count** (e.g. 0.5% of neighbours) instead of an
  absolute value with a gate. Rejected as unreadable: nobody can look at a rec and say what
  threshold produced it. The gate at 25 solves the small-custom-scan case with one number a
  reviewer can check.
- **Shipping the sandbox database first.** Its stated why-now was that `docker compose up -d
  worker` now writes to production, but `run-cycle.sh:62` already unsets `DATABASE_URL` before the
  cycle runs, and `docker-compose.yml:69` is a deliberate commented choice. QA then showed the
  floor needs no Postgres. Parked at the top of the backlog, not dropped.
- **A separate cycle for the guard fix.** A fail-open guard on a charter hard rule is three lines;
  carrying a whole infra item to get them was the more expensive path.
- **Duplicating the allowlist in bash and Python.** Two copies of a safety check is a fork of the
  thing we are fixing. One function, called from both.

## Known cost, accepted

Per-item flooring discards band-level agreement (see above). The measured feed reduction will look
better than the taste improvement actually is, so the write-up reports
`bands_cut_no_multi_co_owner` next to feed size. Also: during a crawl, `crawl_curate_each_slice`
re-curates every slice while `neighbours` is still growing, so the floor can flip from inactive to
active mid-scan and the feed can shrink between two polls. That is expected; `floor_applied` in
stats is how a reader tells that apart from a bug.
