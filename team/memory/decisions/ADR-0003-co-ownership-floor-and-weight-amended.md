# ADR-0003 — Bounding the co-owner weight (amends ADR-0002)

_Cycle 2026-08-24T0840-c005. Amends, does not supersede, ADR-0002. Every ADR-0002 invariant
still binds; this file adds five._

## Problem

ADR-0002 landed on a branch (`2c1c2ed`) and was never merged. Its weight is
`sum(1 + overlap(f))` over the co-owning fans — unbounded and linear in overlap
(`backend/app/curation/engine.py`, `_co_owner_weight` in `2c1c2ed`). Roy owns ~1,700 items,
so one neighbour with overlap 200 contributes 201 and outscores fifty distinct co-owners who
each share two records (50 × 3 = 150). That is the exact inversion the ADR set out to fix:
the score stops meaning "many people close to my taste own this" and starts meaning "one
whale owns this".

Two consequences follow from the same unbounded numerator:

- `W_TAG_AFFINITY = 0.25` (`engine.py:45`) was calibrated against a raw fan count in the
  single digits. Against a numerator in the hundreds it can never break a tie again, so the
  tag term is silently retired.
- Crawl progress contaminates the **numerator**, not only the denominator ADR-0002 argued
  about. A collection visit spends at most `PAGES_PER_VISIT = 10` pages and parks the rest
  (`backend/app/crawl/service.py:70`, `frontier.mark_partial`), so a fan we paged ten deep
  has more measurable overlap than one we paged once. Linear weighting passes that 10×
  difference straight into the score.

Also on the record: ADR-0002's proposal text said merging is a no-op. Half true.
`curation_min_co_owners = 1` is a real no-op; `curation_weighted_co_owners = True` is not.
Merging re-ranks Roy's existing ~1,600-item feed on the next recompute.

## Approach

Same seam as ADR-0002 — everything stays inside `compute_recommendations`. Two edits:

**1. Damp the per-fan term.** `1 + overlap` becomes `1 + log1p(overlap)`. Nothing else about
the weight changes: still a numerator, still no denominator, still ≥ 1 per co-owner, so
weighting still cannot drop a candidate to zero.

| overlap | 0 | 2 | 20 | 40 | 200 | 1700 |
|---|---|---|---|---|---|---|
| damped weight | 1.00 | 2.10 | 4.04 | 4.71 | 6.30 | 8.44 |

Fifty co-owners at overlap 2 now score 105 against the whale's 6.3. Under the branch as
written the whale won, 201 to 150. Sublinearity is also the defence against amendment 4: a
fan crawled 10× deeper carries at most ~1.6× the weight, not 10×.

**2. Put the tag term on a bounded scale in the same diff.** `tag_affinity` is
`sum(tag_profile[t] for t in album tags)` where `tag_profile[t]` counts *Roy's owned albums*
carrying that tag (`engine.py:198-209`). On 1,700 owned albums a common genre is in the
hundreds, so the raw term is already in the hundreds today — the comment at `engine.py:43`
("co-ownership dominates; tag affinity breaks ties") is already false on Roy's real data,
before this diff. A new constant cannot fix a scale that moves with collection size. So the
score becomes:

```
score = W_CO_OWNER * co_owner_weight + W_TAG_AFFINITY * log1p(tag_affinity)
```

with `W_TAG_AFFINITY` set so the tag term can never outweigh a second real co-owner.
`reasons["tag_affinity"]` keeps its raw meaning — it is displayed; only the scoring is damped.

Everything else is ADR-0002 unchanged: floor after exclusions, one helper and one counter
across both loops, settings read at one edge, `stats_out` into `scan.stats`.

## Invariants

Carry forward **every invariant in ADR-0002** (build_exclusions untouched; floor after
exclusions and before sort/dedup; one helper, one counter, both loops; floor tests the raw
distinct-fan count; no denominator anywhere; overlap over owned items only and never `me`;
config read only in `config.py` + `engine.py`; no shared mutable state; no migration; no
credit can be spent). New, and each one checkable against this diff:

- **No unbounded per-fan term.** `grep` of the weight expression shows `log1p` (or an
  explicit cap); `1 + neighbour_overlap.get(...)` with no damping appears nowhere.
- **Per-fan weight is monotone and bounded in a stated range.** Weight is non-decreasing in
  overlap, ≥ 1.0 at overlap 0, and ≤ 1 + log1p(size of Roy's collection) — asserted
  numerically, not asserted in prose.
- **Many beats one.** On a corpus where the whale's overlap is 100× a tight neighbour's,
  fifty tight co-owners still outrank the item only the whale owns. This is the invariant the
  branch violates today; a test that passes only because both fixtures are small does not
  satisfy it.
- **The tag term cannot outrank a co-owner.** With an extreme `tag_profile` (one tag on 500
  owned albums), a 1-co-owner item carrying that tag ranks **below** a 3-co-owner item
  carrying no matching tag. Both loops share the scale, so this is checked on the album loop
  and the ordering of an album against a same-band track is unaffected.
- **Sublinear in crawl depth.** Multiplying one neighbour's overlap by 10 (simulating a fan
  paged ten deep versus once) moves that neighbour's contribution by less than 2×. Asserted
  directly on the weight helper, so it does not depend on corpus shape.
- **Parity is still exact.** Weighting off, floor 1 → identical ids, order and scores to
  `main`. Damping changes only the weighted path.
- **Weighting on is still membership-neutral at floor 1** — same id set as the parity run,
  different order. This is what makes "on by default" defensible.
- **`reasons["tag_affinity"]` is the raw sum, not the damped one.** The damping lives in the
  score expression only. Same rule ADR-0002 set for `co_owners` vs `co_owner_weight`.
- **The PR body states, in one sentence, that merging re-ranks the existing feed** and names
  `CURATION_WEIGHTED_CO_OWNERS=false` as the runtime way back. Any moved assertion in
  `test_curation.py` is named and justified there.

## Changes

- `backend/app/curation/engine.py` — damp `_co_owner_weight` with `log1p`; damp the tag term
  in both score expressions; re-set `W_TAG_AFFINITY` with a comment saying what it is now
  relative to one co-owner.
- `backend/tests/test_curation.py` — three new tests: the scale-gap corpus (fifty tight
  co-owners vs one whale), the tag-cannot-outrank-a-co-owner case, and the direct
  sublinearity assertion on the weight helper.
- `backend/app/config.py` — unchanged from `2c1c2ed`. No new settings.
- `backend/app/crawl/scan_service.py` — unchanged from `2c1c2ed`.
- Tables: none. Migrations: none. Endpoints: none. Frontend: none.

## Tests

- `backend/tests/test_curation.py` — scale gap: 50 fans with overlap 2 versus 1 fan with
  overlap 200; the fifty-owned item outranks the whale-owned item. Fails on `2c1c2ed`.
- `backend/tests/test_curation.py` — tag ceiling: `tag_profile` of 500 on one tag; the
  1-co-owner tagged item ranks below the 3-co-owner untagged item.
- `backend/tests/test_curation.py` — sublinearity: weight(overlap × 10) < 2 × weight(overlap),
  called on the helper directly for a few overlaps.
- Existing ADR-0002 suite must stay green unmodified, especially the parity and
  membership-neutrality tests. 21 curation tests today.
- QA, on the seeded sandbox, outside the suite: a **before/after rank diff** (main versus
  branch, weighting on, floor 1) and feed size at floor 1 / 2 / 3. Plus the kill-criterion
  measurement — correlate each neighbour's overlap with that neighbour's total `fan_items`
  count. If overlap tracks `fan_items`, the weight is measuring crawl depth: **drop the
  weight, keep the floor, ship that.** Do not redesign the scoring to rescue it.

## Rollback

Single `git revert` of the merge commit. Nothing persists that survives it —
`store_recommendations` clears and re-inserts a scan's recs wholesale, so the next curate
restores the old ranking, and leftover `scan.stats` keys are inert JSON. No migration.

Before a revert is needed: `CURATION_WEIGHTED_CO_OWNERS=false` with floor 1 restores today's
ranking at runtime, no deploy. That is the whole reason both values are read from `Settings`.

## Rejected

- **A hard cap (`min(overlap, K)`) instead of `log1p`.** Simpler, but it needs a `K` that is
  a fraction of Roy's collection size, so it is a magic number that goes wrong as the
  collection grows, and it flattens every neighbour above `K` into one indistinguishable
  bucket. `log1p` needs no constant and keeps ordering everywhere.
- **Re-tuning `W_TAG_AFFINITY` as a constant only, leaving the tag term raw.** Cannot work:
  `tag_affinity` scales with the size of Roy's collection and the popularity of his genres,
  so any constant is right at one collection size and wrong at the next. The scale has to be
  bounded, not re-weighted.
- **Normalising `tag_affinity` by owned-album count instead of `log1p`.** That is a ratio, and
  its denominator has the same crawl-progress disease ADR-0002 rejected a denominator for.
  Damping needs no denominator.
- **Dropping the weight and shipping the floor alone.** Tempting — the floor is provably safe
  and the weight is the contaminated half. Rejected *for now* because a floor at its default
  of 1 changes nothing at all, so that ship would be an empty merge. It remains the ruled
  fallback if QA's crawl-progress measurement fires.
- **Defaulting `curation_weighted_co_owners` to `False` to make the merge a true no-op.**
  Honest, and rejected: a setting nobody turns on is a setting nobody evaluates, and Roy
  cannot compare rankings he never sees. The correct fix is to *say* it re-ranks, which the
  PR body now must.
- **Building a real overlap denominator (the DONE-gated ratio from ADR-0002).** Still the next
  door, still out of scope. It mixes two weight scales in one score and needs its own
  experiment.
- **Putting the damped weight into `reasons["co_owners"]`.** Same reasoning as ADR-0002:
  `co_owners` is the readable half of next cycle's sentence and the unit of Roy's histogram.
  Add keys, never redefine one.
- **Naming co-owners on the card in this diff** (the runner-up proposal). Out of scope, and
  the "41% overlap" figure needs exactly the denominator we have twice written down as
  unusable. Next cycle, with a raw shared-record count.

## Risks

- **SILENT, and the main one:** damping bounds the crawl-progress bias, it does not remove it.
  A fan we crawled deeply still carries more weight than the same fan crawled shallowly, just
  ~1.6× instead of 10×. Nothing in the suite can catch this — only QA's overlap-versus-
  `fan_items` correlation on real data can, and it is a judgement call, not an assertion.
- **SILENT:** `W_TAG_AFFINITY`'s new value is calibrated on fixture-scale data. If Roy's real
  `tag_profile` is an order of magnitude larger than the test corpus, the tag term could still
  dominate, and the suite would be green while the live feed is genre-sorted. The ceiling test
  bounds the shape, not the constant.
- A floor above 1 can empty a thin feed (a custom scan had 17 neighbours live, CLAUDE.md M3).
  `filtered_by_floor` in `scan.stats` is the only thing separating "floor too high" from
  "no data".
- Merging re-ranks the existing ~1,600-item feed with no before/after captured from
  production — we cannot read it. The comparison comes from Roy or from the sandbox.
- Mid-crawl drift is unchanged and expected: `crawl_curate_each_slice` re-curates while
  neighbours and overlaps grow, so order moves between polls. `stats` is how a reader tells
  that from a bug.
