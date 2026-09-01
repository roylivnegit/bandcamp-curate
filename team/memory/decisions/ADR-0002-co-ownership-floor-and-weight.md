# ADR-0002 — ADR-0002 — A floor under a rec, and a weight on the stranger who made it

_Cycle 2026-08-23T1249-c004._

## Problem

engine.py:361 scores an item by count(distinct FanItem.fan_id) over the scan's neighbours and engine.py:386 turns that straight into a score with no minimum anywhere. One stranger owning a record makes it a recommendation, and every stranger counts the same — the 8,000-record collector who co-owns everything with everyone counts exactly as much as the 200-record collector who shares half of Roy's taste. The result is ~1,600 recs (CLAUDE.md, M4) ordered by something close to noise. Note: ADR-0001 (cycle c003) ruled build on the floor alone and never landed — config.py has no curation section, engine.py:300-308 has no floor param, no branch carries it. This ADR supersedes it.

## Approach

Both changes live inside compute_recommendations (engine.py:300); nothing above it changes. Two Settings fields — curation_min_co_owners (default 1) and curation_weighted_co_owners (default true) — are read from get_settings() inside the engine, never threaded from the four curate() call sites (feed.py:405, scan_service.py:362, scan_service.py:430, scripts/curate.py:34), because :362 is the mid-crawl re-curate and :430 is finalize; a caller-supplied value would make the running feed and the finished feed rank the same data differently. Kwargs exist only as a test override (test_curation.py:44 already forwards **kw). The floor is one helper called from the album loop (engine.py:377) and the track loop (engine.py:419), after the exclusion and exclude_seed_tags checks and before scored.sort / one_per_band (engine.py:440-450), incrementing one shared per-call counter. The weight is a count, never a ratio: each co-owner contributes 1 + overlap(f), where overlap(f) is how many of Roy's owned items that fan also owns. No division — the only available denominator, count(fan_items), is crawl progress (crawl/service.py:70 parks collections mid-pagination; models.py:124-137 has no item count), so a ratio boosts the fans we crawled least. The numerator is crawl-contaminated too, but in the safe direction: under-crawled means under-weighted, never inflated. This turns the two GROUP BYs into pair-level (item_id, fan_id) selects aggregated in Python, bounded by fan_items (22,606 rows, CLAUDE.md M6); per the Lead, if that rewrite grows past the two existing GROUP BYs, ship the floor alone and park the weight. stats_out: dict | None on compute_recommendations and curate carries min_co_owners, weighted, candidates, filtered_by_floor into scan.stats at scan_service.py:366 and :437, which api/scans.py:43,68 already passes through as an open dict — per call, never module state, since slices drain at crawl_concurrency 50. reasons["co_owners"] keeps meaning distinct fans; the weighted figure is a new key, co_owner_weight.

## Rollback

Single `git revert` of the PR. No migration and nothing persisted that survives it: store_recommendations clears and re-inserts a scan's recs wholesale (engine.py:458-472), so the next curate restores the old feed, and leftover scan.stats keys are inert JSON. Before a revert is needed, setting CURATION_WEIGHTED_CO_OWNERS=false (with floor 1) restores today's ranking at runtime with no deploy — that is the point of reading both from Settings.

## Invariants

- build_exclusions is untouched — no diff in it, no second exclusion path. The floor is a threshold, not an exclusion.
- Floor and weight are applied after the exclusion checks (engine.py:378, engine.py:420) and after exclude_seed_tags, never before — so filtered_by_floor never counts an item already excluded as owned / wishlisted / followed-by-band-id / followed-by-host / liked / blacklisted.
- Default floor (1) with weighting OFF reproduces today's feed exactly: same ids, same order, same scores, on the existing fixture graph.
- Weighting ON at floor 1 changes order only, never membership — the id set is identical to the parity run. Asserted, not assumed; this is the Lead's stated reason for defaulting it on.
- One helper, one counter, both loops: the album loop and the track loop call the same floor function and increment the same counter. No `if co_owners < floor` written twice, no filtering in store_recommendations or the API layer.
- Album and track scores stay on one scale — both read the same weight map. one_per_band (engine.py:441) compares an album against a track of the same band, so weighting one loop and not the other silently flips which release survives.
- The floor tests the raw distinct-neighbour count, not the score: `co_owners >= floor`, never `score >= floor`.
- The weight has no denominator — no division, no len(fan_items), no ratio anywhere in the weight expression. Every co-owner weighs >= 1, so weighting can never drop a candidate to zero.
- Overlap is computed against Roy's owned items only (is_wishlist false) and never includes Roy himself (fan_id != me.id, already at engine.py:334,341).
- Config is read at one edge: `grep -rn curation_min_co_owners` returns app/config.py and app/curation/engine.py only — not feed.py, not scan_service.py, not scripts/curate.py.
- No shared mutable state — the counter and stats_out are per-call locals. No module-level or class-level accumulator (two scans curate concurrently).
- No schema change, no migration, no data altered: alembic/versions/ gains no file; scan.stats gains keys.
- Nothing in the diff can spend a credit: no app/scraping/ call, no scan start, no worker drain.
- Any existing assertion in test_curation.py that moves (e.g. A4 > A5 under weighting) is named and justified in the PR body. A quietly rewritten expectation is how a wrong ranking ships green.

## Changes

- backend/app/config.py — add curation_min_co_owners: int = 1 and curation_weighted_co_owners: bool = True, each with a comment saying why
- backend/app/curation/engine.py — read settings in compute_recommendations; pair-level candidate queries replacing the two GROUP BYs (engine.py:355-368, :404-417); per-neighbour overlap map; shared floor helper + shared counter; co_owner_weight in reasons; stats_out on compute_recommendations and curate
- backend/app/crawl/scan_service.py:366 and :437 — pass stats_out and merge it into scan.stats
- backend/tests/test_curation.py — the seven tests below, on the existing sqlite in-memory fixture
- Tables: none. Migrations: none.
- Endpoints: none — GET /api/scans already passes scan.stats through as an open dict (api/scans.py:43,68)

## Tests

- Parity: floor 1, weighting off → identical ids, order and scores to today (backend/tests/test_curation.py)
- Weighting reorders, never shrinks: same graph with weighting on → identical id set to the parity run
- Mega-collector loses: a fan owning 200 items but only 2 of Roy's, versus two fans owning 30 items with 15 of Roy's; an item owned only by the mega-collector ranks below an item owned only by a tight one. The corpus must make 'mega' mean large collection AND small absolute overlap — otherwise the test proves nothing
- The mega-collector assertion repeated independently on a track candidate — the track loop has no tag term (engine.py:434) and is the one most likely to be left behind
- Floor cuts both loops: a band whose only items are a 1-co-owner album and a 1-co-owner track produces zero recs at floor 2
- Counter is honest: filtered_by_floor equals the number cut and does not count an item build_exclusions had already removed
- Settings reach the engine with no kwargs: patched settings change the result of a bare compute_recommendations(...) call — this is what makes all four curate() call sites agree

## Rejected

- overlap ÷ collection size — the only available denominator is count(fan_items), which is crawl progress (crawl/service.py:70; models.py:124-137 has no item count). It boosts the fans we crawled least, and does it in a way that looks like a good result.
- The DONE-gated ratio — real and now known to be queryable: mark_done clears the cursor (frontier.py:183-185), a parked collection stays PENDING with one (:199-201), and completed_elsewhere (:265) already selects on DONE across scans; the join is CrawlFrontier.url == Fan.url since CrawlFrontier has no fan_id (models.py:333-347). Deferred because mixing two weight scales in one score needs its own experiment. This is the next door.
- The floor as SQL HAVING (ADR-0001's approach) — it counts before exclusions, so filtered_by_floor would not mean what a reader thinks; and the weighted path needs pair-level rows anyway, so the HAVING saves nothing.
- The floor after one_per_band — a below-floor item would keep its band alive and suppress the band's better release, and the counter would stop meaning anything.
- The floor on the weighted score — unreadable (nobody can look at a rec and say what cleared it) and it would not match the co_owners histogram Roy is being asked for.
- Threading floor/weight as kwargs from the four curate() call sites — the mid-crawl feed (scan_service.py:362) and finalize (:430) would then rank the same rows differently, visible to Roy as recs vanishing and reappearing during a scan.
- Overwriting reasons['co_owners'] with the weighted number — it is the readable half of next cycle's sentence and the unit of Roy's histogram. Add a key; do not redefine one.
- ADR-0001's min_neighbours_for_floor gate and bands_cut_no_multi_co_owner diagnostic — both good, both out of this scope, and both inert while the floor default is 1.
- A log line instead of a counter in scan.stats — not queryable after the run, which is the only time anyone asks.
- The Postgres sandbox — test_curation.py:114,172,185,211,233 already covers all five exclusion paths in sqlite.

## Risks

- SILENT: the numerator does not fix every mega-collector. It demotes the fan with a big collection and small absolute overlap; a fan with a big collection and big overlap still wins. If the test corpus conflates the two, the suite goes green while proving less than it claims. The real fix is the DONE-gated ratio.
- A floor above 1 can empty a thin feed — a custom scan had 17 neighbours live (CLAUDE.md, M3). ADR-0001's min_neighbours_for_floor gate is out of scope, so filtered_by_floor in scan.stats is the only thing separating 'high floor' from 'no data'.
- Weighting ships on by default and changes Roy's ranking with no before/after captured, because we cannot read production. The comparison has to come from him.
- Mid-crawl drift: crawl_curate_each_slice re-curates while neighbours and overlaps grow, so the order moves between two polls. Expected; stats is how a reader tells that from a bug.
- Memory: pair-level aggregation holds a fan-id set per candidate in Python. Fine at 22,606 fan_items; fails as a worker OOM, not as a wrong answer, if the graph grows orders of magnitude.
