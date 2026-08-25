# ADR-0004 — ADR-0004 — Ship the co-ownership floor with a histogram that makes it settable

_Cycle 2026-08-24T1227-c006._

## Problem

The feed is ~1,600 recs (CLAUDE.md, M4) and nobody reads 1,600 records, so most of what the product finds is never seen. The parked branch adds the knob that would cut it down — `curation_min_co_owners`, default 1, i.e. off — and gives no way to know what to set it to. Shipping the knob alone ships a dead control and re-opens the same question next cycle.

## Approach

Land the parked branch `team/2026-08-24T0840-c005-co-ownership-floor-and-weight` as-is (both ADR-0003 amendments are already committed at e32b2a6), plus one new read-only script `backend/scripts/co_owner_stats.py` and its test. For each candidate floor N the script calls `compute_recommendations(session, scan, user, min_co_owners=N, stats_out=...)` and reports `len(result)` alongside `candidates` and `filtered_by_floor` from `stats_out`. The seam: this is a READER of the curation engine, not a second curation path. It calls one public engine function and never `curate`, `store_recommendations`, or `ensure_collection_scan` — that last one get-or-creates a Scan and flushes (`engine.py:92-100`), so it is a write. User and scan come from explicit arguments and scope every query.

## Rollback

Single `git revert` of the script commit: two new files, nothing imports them, no schema change, no data touched. Reverting the whole merge also removes `curation_min_co_owners`; since it ships defaulting to 1 (no behaviour change), neither revert alters any feed already computed.

## Invariants

- The script never writes: no `session.add`, `session.commit`, `session.flush`, `delete(...)`, and no call to `curate` / `store_recommendations` / `ensure_collection_scan`. Grep the new file for those names — every hit is a bug.
- The floor's input set is the engine's, not the script's: each count is `len(compute_recommendations(..., min_co_owners=N))`. The script must not select from `recommendations` and must not filter on `reasons["co_owners"]` — ADR-0002 binds the floor pre-dedup (`engine.py:508`, `engine.py:567`) while `one_per_band` collapses after (`engine.py:586-594`), so any stored-row count is a lower bound, not the number.
- Ownership is explicit and scoped: the script takes a user (and optionally a scan) as an argument, resolves the scan by `Scan.user_id == user.id`, and exits non-zero if the scan is missing or belongs to someone else. `Recommendation` has no `user_id` — it scopes transitively via `scan_id` (`app/db/models.py:317`) — and unscoped reads of this exact shape produced the four M8 cross-tenant leaks.
- Zero network, zero credits: no import of `app.scraping`, `httpx`, or any crawl module. Postgres/SQLite reads only.
- `curation_min_co_owners` still defaults to 1 in `app/config.py` after this PR — the histogram informs Roy's choice, it does not make it.
- `limit` stays `None` in every `compute_recommendations` call; a limit would truncate the very number being reported.
- The countable logic is importable: the per-floor computation is a function taking `(session, user, scan, floors)` and `main()` only parses args and opens the sessionmaker, so the test runs against the in-memory sqlite fixture with no `DATABASE_URL` and no subprocess.
- The engine's public behaviour is unchanged: no edit to `app/curation/engine.py`, no edit to `build_exclusions`, no new engine kwargs. On top of the parked branch the diff is two new files.
- No frontend, no API, no `reasons.top_neighbours` — naming neighbours is next cycle's item and must not appear in this diff.
- `ruff check .` reports the same 4 pre-existing errors as main: none added, and the existing four not fixed here.

## Changes

- backend/scripts/co_owner_stats.py — new; read-only histogram of feed length across candidate floors
- backend/tests/test_co_owner_stats.py — new; fixture session with a known co-owner distribution, asserts the reported counts
- No schema change, no migration, no new table or column
- No endpoint change, no frontend change
- PR body states 208 tests (QA measured on the branch), not 205

## Tests

- Fixture session in the shape of `test_curation.py:34-40` (`sqlite+aiosqlite://`) with bands/albums/supporters at known co-owner counts, including at least one band whose SECOND item has more co-owners than its first — the case a `reasons.co_owners`-based count gets wrong. Assert per-floor counts.
- A floor above every item's co-owner count reports 0 recs and does not raise.
- Nothing is persisted: `select(count()).select_from(Recommendation)` is unchanged after the call, and no `Scan` row is created for a user who had none.
- The script refuses a scan belonging to another user (raises / exits non-zero).
- Existing floor and weight coverage stays green: `backend/tests/test_curation.py:376-708`.
- Full suite 208 passed; `ruff check .` at the same 4 pre-existing errors.

## Rejected

- Count stored `recommendations` rows where `reasons["co_owners"] >= N`. One query, no re-scoring, and wrong: `co_owners` only lands in `reasons` on rows that survived `one_per_band`, while the floor runs before dedup. A band whose top item has 2 co-owners and whose second has 4 vanishes from the count and not from the feed. This was the original proposal and is the mistake this ADR exists to prevent.
- One pass at the lowest floor with `one_per_band=False`, then bucket by `reasons["co_owners"]` and count distinct `band_id`. Exact today and ~5x cheaper than N passes. Rejected because it re-implements the dedup rule in the script, including that items with `band_id is None` are never deduped (`engine.py:588-594`). When dedup changes — per-label, per-release-group — the histogram silently reports a feed length that no longer exists. A short candidate list buys back the cost.
- Make it an API endpoint. More surface, needs auth and a request budget for a query that runs seconds to minutes, and Roy runs it once to pick a number. A script is the right size.
- Pick the default floor for him in this PR. Nobody knows the distribution yet. If it comes back flat — nearly every rec at 1 or 2 co-owners — the floor cannot separate good from bad and the answer is a different discriminator, not a threshold; that result goes in `memory/tried-and-failed.md` per the proposal's own kill criteria.
- Fold in the exclusion/staleness audit (P3) as a second subcommand. It would audit rows that the first recompute after this merge replaces. It is next cycle's first item, built on `build_exclusions` rather than a second implementation of the six exclusion paths.

## Risks

- Silent failure mode, the one to watch: N full re-scoring passes over Roy's real data (15,938 albums, 22,606 fan_items) can run for minutes with no output. If the script prints only at the end, a slow run looks like a hang and gets killed. Print each row as it completes.
- The numbers are a snapshot of crawl progress, not of taste. Co-owner counts rise as collections finish paging (`PAGES_PER_VISIT = 10`, parked-and-resumed visits). A floor picked mid-crawl is stricter than the same floor after the crawl completes. The output must say so in one line next to the table — the same disease ADR-0003 recorded for the weight.
- A reviewer may wave through the scoping invariant because 'it is only a script'. Cross-tenant reads on this table are exactly how the M8 leaks happened; check the scan resolution by eye.
- Scope creep into a query layer: if the script needs selects beyond 'find the user, find their scan', it has stopped being a reader of the engine — stop and say so, per the Lead's scope limit.
