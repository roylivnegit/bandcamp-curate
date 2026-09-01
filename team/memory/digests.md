# Grooming digests

The Lead's curated essence of each cycle's grooming debate — what was decided and why, distilled
down from the raw back-and-forth. Written at the end of grooming, not at retro, so it survives a
cycle that never reaches phase 7 (the common case so far).

Standup reads the **most recent** entries (the tail of this file), since it's append-only and
grows. Nothing is ever deleted.

<!-- cycles append below this line -->

## 2026-08-24T0840-c005 · Merge the parked co-ownership floor and weight

ROUND 1 (only round). All three roles converged on Proposal 1; no contention on the pick.

RULED: Proposal 1 — co-ownership weight + floor. Branch team/2026-08-23T1249-c004-co-ownership-floor-and-weight, commit 2c1c2ed, worktree at /private/tmp/crate-team-worktrees/.

EVIDENCE ON THE RECORD:
- QA ran the branch: 205 passed / 0 failed, incl. 21 curation tests (mega-vs-tight-overlap, floor-cuts-both-loops). ruff: 4 errors in scripts/ + test_scraping.py, identical on main → pre-existing, not a blocker.
- QA confirmed both curate() call sites in scan_service.py (_curate_progress, finalize_scan) thread stats_out into scan.stats → "a misconfigured floor is visible" is real.
- Architect: no seam broken. Settings read only inside compute_recommendations; floor applied after build_exclusions (not forking it); provider and frontier untouched.
- Researcher: commit 2c1c2ed verified real. grep for purchase/added/timestamp in backend/app/bandcamp/parse.py returns nothing → recency is not parsed anywhere today.

REQUIRED AMENDMENTS (must be in the ADR and the diff):
1. Weight as written is unbounded and linear: sum(1 + overlap(f)). Roy's collection ~1,700 items, so one neighbour with overlap 200 scores 201 and beats fifty distinct co-owners sharing two records each — inverts the goal. Dampen (1 + log1p(overlap), or cap the per-fan term).
2. Re-scale W_TAG_AFFINITY = 0.25 in the SAME diff — against a numerator in the hundreds it can never break a tie again. Tag affinity is silently retired otherwise.
3. Existing "mega-collector loses to tight-overlap neighbour" test passes today only because both fixtures are small. Needs a fixture that actually exercises the scale gap.
4. Crawl-progress bias hits the NUMERATOR, not just the denominator ADR-0002 addressed: a fan paged ten deep has more overlap than one paged once (PAGES_PER_VISIT = 10, mark_partial parks the rest). Stated kill criterion is real and currently untested.
5. CORRECTION to the proposal text: curation_min_co_owners = 1 is a true no-op, but curation_weighted_co_owners = True — weighting is ON by default. Merging re-ranks the existing ~1,600-item feed on next recompute. QA test plan must capture a before/after RANK diff on the seeded sandbox, not only "membership never shrinks."

RUNNER-UP (lost, deferred to next cycle): Proposal 2, overlap chip. Depends on P1's weights to know which neighbours are worth naming; and the "41% overlap" figure needs exactly the denominator ADR-0002 declared unusable — an invented percentage is worse than a bare count. Next cycle it ships the RAW shared-record count. Researcher offered to pull engine.py:390 (reasons schema) before that cycle commits effort.

DEFERRED, HEARD: Proposal 3 (recency signal) — not a build item; researcher runs it in parallel this cycle. Zero credits, browser-saved fixture per the hard rule, parsers stay fetch-free. team/memory/research/ is empty → unclaimed. Architect has no objection subject to those two conditions.

Ruling: build — This is the item last cycle parked, and the charter says finishing beats starting. The work exists at commit 2c1c2ed with tests, QA already ran the branch green (205 passed, ruff failures pre-existing on main), and the Architect confirmed no seam is broken — settings are read only inside compute_rec

## 2026-08-24T1227-c006 · Merge the co-ownership floor, and give Roy the histogram that makes it usable

## Proposals on the table

**P1 — `co_owner_stats.py`: read-only script that reports how feed length varies with the `min_co_owners` floor**, so the floor is picked from data instead of guessed. Architect's amendments (both accepted as conditions of the design):
- Do NOT count stored `recommendations` rows by `reasons.co_owners >= N`. That forks the definition of "a rec": `co_owners` only exists in `reasons` on rows that already survived `one_per_band` dedup, and ADR-0002 binds the floor to apply *before* dedup. A band whose top item has 2 co-owners but whose second has 4 disappears from the count and not from the feed — the histogram would be a lower bound, not the number.
- Instead call `compute_recommendations(..., min_co_owners=N, stats_out=...)` once per candidate N and count the returned list; never call `store_recommendations`. One code path, exact numbers, read-only, zero credits.
- **Blocking amendment (Architect):** the script takes an explicit user/scan and scopes every query through it. `Recommendation` has no `user_id` — it scopes transitively via `scan_id` (`models.py:317`) — so a bare select over `recommendations` is a cross-tenant read of exactly the shape that produced the four M8 leaks.

**P2 — name the taste-neighbours on a rec card** ("shares N of your records" + link to their Bandcamp fan page). Contested on two counts, both with a resolution already on the record:
- The data is not free: `neighbour_overlap` is computed only inside `if weighted_co_owners:` (`engine.py:442-447` on the branch). Naming neighbours either couples the card to a scoring flag or forces the query unconditionally — the design must pick one. Use `Fan.url` (`models.py:134`); do not rebuild the fan URL in the frontend.
- The number is a moving floor, not a fact: a fan is paged at most `PAGES_PER_VISIT = 10` then parked (ADR-0003, CLAUDE.md; p90 ≈ 43 pages/collection), so the count changes between polls while a neighbour is mid-crawl. QA raised this as a correctness risk needing a decision before code. **Resolution both agreed on: ship it as "shares at least N", or ship no number.**
- Researcher: the fan-page link assumes `bandcamp.com/<username>`, matching `BANDCAMP_FAN_URL`'s documented shape — a 2-minute fixture check before merge, not a blocker.

**P3 — staleness detector**: same script, second subcommand, same mandatory scan/user scoping. It must call `build_exclusions` rather than re-check the six exclusion paths itself — a second implementation is the exact fork CLAUDE.md forbids. Consequence, and it must be said plainly in the ADR: this detects **staleness** (recs stored before a follow or a newly-owned item existed), not logic bugs. That is fine — staleness is the failure that actually bit us — but do not promise more.

## Gates, measured on the parked branch (QA ran them)

- `pytest` → **208 passed**. Proposal 1's text says 205; correct the number before it reaches the PR body.
- `ruff` → same 4 pre-existing errors as main. No new debt.
- Floor/weight logic is already well covered: `test_curation.py:376-708`.
- **As scoped, `co_owner_stats.py` ships with zero tests** — breaks the charter's "tests come with the change, in the same PR". Required: one test against a fixture session with a known co-owners distribution, asserting the reported buckets.

## Carried forward, not built this cycle

- QA verified a real coverage gap: existing `build_exclusions` tests check the function in isolation, never the **immediate-prune paths** that likes/blacklist trigger separately from a full recompute (CLAUDE.md, M5). Small, read-only, good next-cycle item. Do not let it silently drop.
- Researcher: none of the three proposals need outside research; `team/memory/research/` is empty, confirming the "not_proposing" note about second-source research. That work stays off the build slot and can run in parallel for free whatever wins.

Ruling: build — Resume the parked branch `team/2026-08-24T0840-c005-co-ownership-floor-and-weight` — do not start from main, both of last cycle's amendments are already committed there (e32b2a6, log1p weight bound per ADR-0003). The branch ships `curation_min_co_owners` defaulting to 1, i.e. a knob that is off with
