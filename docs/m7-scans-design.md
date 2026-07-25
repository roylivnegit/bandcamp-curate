# M7 — Scans (design note)

**Status:** proposed, for review. Branch `feature/scans`.

## Goal
Turn the single implicit discovery run into named **scans**, each with its own **seed
set** (Bandcamp album/track URLs). The feed becomes per-scan. The UI can queue a scan;
your Mac executes it. Blocked, liked, and the collection/wishlist/follows exclusion base
are **shared** across all scans.

## Concepts & what's shared vs per-scan
| Thing | Scope |
|---|---|
| **Scan** (name + seed URLs) | new entity |
| **Recommendations** | **per-scan** |
| Bandcamp graph (bands/albums/tracks/supporters/fan_items) | **shared** (it's just the public graph) |
| Exclusion base — collection / wishlist / follows (from the **root fan URL**) | **shared** |
| **Blocked** list, **Liked** list | **shared** |
| Crawl budget (`crawl_max_requests`) | **shared/global** (for now) |

"Scan 1" = today's run, defined as **seeds = your collection's albums** (the `is_me` fan).
The root fan URL (`BANDCAMP_FAN_URL`) stays required — it's the shared exclusion base for
every scan (only surface tracks whose bands aren't already in your world).

## The hard part: UI (cloud) triggers a crawl on your Mac
The `scans` table doubles as a **job queue**. Flow:
1. UI creates a scan → row with `status='queued'`.
2. An **always-on poller on your Mac** polls Neon for `queued` scans, atomically claims one
   (`UPDATE … SET status='running' WHERE id=? AND status='queued'`), runs the crawl locally
   (spending Nimble credits), writes results, sets `status='done'` (or `'error'`).
3. UI polls `GET /api/scans/{id}` and shows queued → running → done.

Cloud never reaches into the Mac; the Mac *pulls* work. If the Mac/poller is off, scans sit
`queued`. This preserves the Option-A split (cloud = always-on read; Mac = crawl).

## Data model (migration `0006`, guarded)
- **`scans`**: `id, name, kind('collection'|'custom'), status('draft'|'queued'|'running'|'done'|'error'),
  error(nullable), stats(JSON: credits/counts), created_at, updated_at, last_run_at`.
- **`scan_seeds`**: `id, scan_id→scans, url, seed_type('album'|'track'),
  resolved_album_id(nullable), resolved_track_id(nullable)`.
- **`recommendations`**: add `scan_id→scans` (indexed, NOT NULL). Unique constraint becomes
  `uq(scan_id, item_type, album_id, track_id)`.
- Backfill: create the **"My collection"** scan (kind=`collection`) and assign all existing
  recommendation rows to it.
- `blacklist` and `likes` are **unchanged** (stay global).

## Per-scan curation (the core algorithm change)
Today `compute_recommendations` counts co-ownership across **all** non-me fans. Generalize to
scope the neighbour set to a scan's seeds:

- `seed_album_ids(scan)` = resolved album ids of its seeds (for `collection`: your owned albums).
- **neighbours** = distinct fans in `album_supporters` for those seed albums (minus `is_me`).
- **candidates** = those neighbours' `fan_items`; `co_owners` = how many of *them* own each item.
- Shared exclusions (`build_exclusions`) + blocked + liked applied as today.
- Tag-affinity + seed-tag provenance scoped to the scan's seeds.
- Store with `scan_id`; `curate(scan_id)` clears+inserts only that scan's rows.

This makes scans genuinely different (each reflects *its* seeds' supporters), and Scan 1 stays
equivalent to today (its seeds = your collection).

## Crawl path for custom seeds
Reuse the existing walk. For each seed:
- **album URL** → `crawl_album` (ingests album/tracks/tags/supporters, enqueues supporters'
  collections), then `run_until_empty` bounded by `crawl_max_depth` + `crawl_max_requests`.
- **track URL** → needs a small addition: crawl the track's supporters via the thumbs XHR with
  `tralbum_type='t'` (the client already supports it), then walk their collections. *(See open Q1.)*
The frontier's `(url, kind)` uniqueness means seeds already crawled by another scan aren't
re-fetched — the graph is shared; only curation is re-scoped.

## API
- `GET /api/scans` — list (id, name, kind, status, seed_count, rec_count, last_run_at).
- `POST /api/scans` — create `{name, seeds:[url,…]}` → `status='queued'` (auto-run).
- `GET /api/scans/{id}` — detail incl. seeds + status + stats (for the UI's status poll).
- `POST /api/scans/{id}/run` — re-queue (re-crawl/recompute).
- `DELETE /api/scans/{id}` — delete a scan + its recs (Scan 1 protected).
- Feed endpoints (`/recommendations`, `/count`, `/facets`, `/stats`, `/recompute`) gain a
  **`scan_id`** param (defaults to Scan 1). Blocked/liked stay global; block/like prune the
  band's recs across **all** scans.

## UI
- New landing view: **scan list** (cards: name, status badge, rec count, seed count, last run) +
  **“＋ New scan”**.
- **New-scan flow:** name + add album/track URLs one at a time (input → add → removable list) →
  **Create & run**; show queued/running (poll status) then it lands in the list.
- Click a scan → the **current feed UI**, scoped to that scan (all filters/sort/like/block work,
  now carrying `scan_id`), with a **“← Scans”** back link.
- Blocked/Liked panels stay (global).

## Staged delivery (one PR per stage, deploy after each)
- **Stage 1 — backend core:** migration + backfill "My collection" scan, per-scan curation,
  feed endpoints gain `scan_id`. No UI change yet. Tests. *(Feed still works, defaulting to Scan 1.)*
- **Stage 2 — scan management + poller:** scans CRUD API, the Mac poller (`scripts/scan_worker.py`),
  custom-seed crawl path. Tests + a live single-scan run.
- **Stage 3 — UI:** scan list, new-scan flow, drill-in wiring, status polling.

## Open questions
1. **Track seeds** — for a pasted *track* URL, crawl that track's own supporters
   (`tralbum_type='t'`), or resolve to its parent album and use album supporters? (I lean: use the
   track's own supporters — truest to what you pasted.)
2. **Budget** — keep one global `crawl_max_requests` cap for now, or a per-scan cap? (I lean: global
   now, per-scan later.)
3. **Poller cadence / packaging** — a standalone `scripts/scan_worker.py` loop (simple, run it in a
   terminal/login item) vs folding into the existing ARQ worker? (I lean: standalone loop — no Redis
   needed, matches the Redis-free crawl path.)
