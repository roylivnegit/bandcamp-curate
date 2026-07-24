# crate-digger — working notes for Claude

Personal Bandcamp discovery engine. Mines your Bandcamp collection, walks the social
graph (album **supporters** → their **collections**), and produces a curated, ranked
feed of tracks you don't own yet. Full build plan: `~/.claude/plans/i-want-to-create-purrfect-pascal.md`.

## Stack & layout
- **Backend:** Python 3.12+ / FastAPI (async), SQLAlchemy 2.0 + Alembic, Postgres.
- **Jobs:** Redis + ARQ workers + token-bucket rate limiter (M3, not built yet).
- **Scraping:** Nimble **v2** `/extract` only, behind a provider seam (`app/scraping/`).
- **Parsing:** Bandcamp embeds clean JSON in the page (`#pagedata data-blob`, `data-tralbum`,
  `data-band`); we parse it **locally in Python** (`app/bandcamp/parse.py`) rather than
  Nimble server-side parsit-ai — see "Open decision" below.
- Layout: `backend/app/{scraping,bandcamp,db,api}`, `backend/nimble_parsers/` (unused so far),
  `backend/tests/`, `backend/scripts/` (verify_nimble.py, dump_extract.py).

## Status (as of 2026-07-24, M2 done + M3 started)
- **M0 Scaffold** ✅ committed (`da93068`) — FastAPI skeleton, 15-table schema, Alembic
  baseline (builds from ORM metadata), docker-compose, health endpoints.
- **M1 Nimble waterfall** ✅ committed (`25443bb`) — `ScraperProvider` ABC, `NimbleProvider`
  (v2 `/extract`, Bearer, maps 401/402/429/5xx → `data.parsing.entities`), `ScraperGateway`
  (priority fallback, quota→circuit-open, 429→backoff, auth→fail-fast), rate limiter, cache,
  `provider_usage` logging. **Live smoke test passed (HTTP 200).** Also updated the
  `nimble-webit-api` skill in ~/Downloads to v2 and scrubbed the leaked key from it.
- **M2 Parsers + mappers** ✅ committed (`fce998c`):
  - ✅ `fan_collection`: `parse_fan_page()` + `ingest_fan_collection()` mapper.
  - ✅ `album_page`: `parse_album_page()` (`data-tralbum` id/url/`current.title`/`trackinfo[]`,
    `data-band` id+name, tags via `<a class="tag">`) + `ingest_album()` mapper (band/album/
    tracks/tags, idempotent).
  - ✅ `album_supporters`: `parse_album_supporters()` + `ingest_album_supporters()` mapper.
    **Correction to earlier note:** supporters ARE in a clean JSON blob — `<div
    id="collectors-data" data-blob="{thumbs:[{fan_id,username,name}],more_thumbs_available,
    token}">`. We parse that (gives **fan_id**), and fall back to the `<a class="fan pic">` DOM
    anchors (username only) if the blob is absent.
  - Real fixture `tests/fixtures/album_page.html` (trimmed from a live panchito fetch + 2
    synthetic supporters for multi/dedup coverage).
- **M3 Crawl workers** ✅ live-validated (committed): `app/crawl/` = frontier repo (`crawl_frontier`,
  idempotent enqueue/claim/complete) + `service` (`crawl_fan_collection`→enqueue owned albums;
  `crawl_album`→ingest supporters, enqueue their collections) + `runner` (Redis-free driver) +
  `seed`. `app/worker.py` = ARQ adaptor (`seed_crawl`/`crawl_next` self-perpetuating chain).
  `scripts/crawl.py` = in-process CLI (`seed`/`run`/`status`). Unit-tested with a fake fetcher over
  the fixtures (no credits), **and run live 2026-07-24** (local brew Postgres+Redis, `run 3`):
  seed→182 fan_items (collection XHR pagination), 179 bands/119 albums/180 tracks/45 follows,
  2 albums→17 album_supporters (thumbs XHR pagination), depths 0/1/2 as expected, **3 Nimble
  credits** (page renders only; all pagination free-direct).
- **Pagination = mimic the XHR, not render+scroll.** Two clients POST Bandcamp's public JSON APIs
  directly and page via the returned token; the fan/album page is rendered once for the first page + ids.
  - `collection_api.CollectionApiClient` → `api/fancollection/1/collection_items` **and**
    `.../wishlist_items` (identical shape; pass `url=WISHLIST_ITEMS_URL`) →
    `{items, last_token, more_available}`. Items reuse `parse_collection_item()`. For `is_me`,
    `crawl_fan_collection` pages the **full collection AND the full wishlist** (both embed only the
    first ~20/page) so curation excludes every owned/wishlisted item.
  - `follows_api.FollowsApiClient` → `api/fancollection/1/following_bands`
    (`{fan_id, older_than_token, count}` → `{followeers[], more_available, last_token}` — note the
    misspelled `followeers` key). The page embeds only the first ~45 follows but a fan can follow
    thousands, so `crawl_fan_collection` pages the **full** list for `is_me` — curation must exclude
    every followed artist/label. (Bug fixed 2026-07-24: follows were capped at 45 → followed labels
    like `adncolors`/`atomesmusic` leaked into recommendations.)
  - `supporters_api.SupportersApiClient` → `api/tralbumcollectors/2/thumbs`
    (`{tralbum_type, tralbum_id, token, count}` → `{results[], more_available}`). NOTE the XHR
    response uses `results`/`more_available`, **different** from the embedded `#collectors-data`
    blob's `thumbs`/`more_thumbs_available`; `parse_thumbs_api()` handles both. Each result also
    ships a ready `url`.
  Both are injectable (fakes in tests, `MockTransport` unit tests); direct httpx now, swap the
  transport to route via Nimble if IP-throttled. **Both endpoints live-verified 2026-07-24**
  against `guron`'s collection (40 items/page) + `panchito`'s supporters (results shape captured).
- **Fan-out is bounded by depth** (`crawl_frontier.depth`, seed=0; `crawl_max_depth` config,
  default 3) **and by a request budget** (`crawl_max_requests`, default 100 = cumulative successful
  provider fetches; enforced in `runner.run_until_empty` + the ARQ `crawl_next` chain). Ingest
  still happens at the boundary, only outward enqueue stops.
- **M4 Curation** 🔨 POC done (committed + run live): `app/curation/engine.py` scores unowned
  albums/tracks by **co-ownership among taste-neighbours** (# non-me fans who own it) + a
  **tag-affinity** nudge from your owned-album genres, after excluding everything already in your
  world — **owned + wishlisted** (`fan_items`, the wishlist via `is_wishlist`), **followed** bands
  (`follows`, matched by band_id **and by URL host** so a followed label excludes albums whose
  stored band is the artist), and active **blacklist**. "You" = the `is_me` fan (from
  BANDCAMP_FAN_URL). Writes
  explainable rows to `recommendations` (idempotent clear+insert). `scripts/curate.py [N]` prints
  the feed. **Wishlist ingestion added**: `fan_items.is_wishlist` (migration `0002`, guarded), parsed
  from `item_cache.wishlist`, ingested only for `is_me`.
  - **One rec per band** (`compute_recommendations(one_per_band=True)`), and **seed-tag
    provenance**: for each rec, `_seed_tag_provenance()` records the genres of *your* albums whose
    supporters own it (stored in `reasons.seed_tags`, shown as "via …" in the UI). `exclude_seed_tags`
    drops recs generated from your albums carrying those genres — the "don't show me things from my
    <genre> collection" filter (curation-time; `POST /api/recommendations/recompute?exclude_seed_tag=`).
  - **Tags tracked at 3 levels**: `album_tags` (existing) + `band_tags` + `track_tags` (migration
    `0003`, guarded + backfilled). `ingest_album` links album-page tags to the album, its band, and
    each of its tracks. `curation.seed_tags()` lists your own albums' genres (the seed-exclusion
    facet). `GET /api/facets` returns tags + labels + seed_tags.
  - **Live**: curate → 1,600 recs (= 1,600 distinct bands). Tag-affinity/genre-filter data grows as
    album *pages* are crawled (tags live there, not in `collection_items`); a targeted batch tags the
    top recs without fan-out (enqueue at `depth=max_depth`, or fetch+`ingest_album` directly).
  - **Rate-limit hygiene**: the direct API clients (`CollectionApiClient`/`SupportersApiClient`/
    `FollowsApiClient`) now pause `DEFAULT_DELAY=0.4s` between pages — Bandcamp 429s bulk direct
    pagination without it. Tests pass `delay=0`.
- **M5 API + UI** 🔨 POC done (committed + run live): FastAPI serves a self-contained dark feed UI
  at `GET /` (`app/api/ui.py`, no build step) over these `/api` endpoints (`feed.py`,
  `blacklist.py`):
  - `GET /api/stats` — recs / neighbours / owned / wishlist / follows / crawl budget.
  - `GET /api/recommendations` — ranked, `limit`/`offset`, `item_type` filter, plus **filter
    by/out**: `tag` / `exclude_tag` (genre) and `label_id` / `exclude_label_id` (band). Each row
    carries `band_id`.
  - `GET /api/facets` — tags + labels (bands) present in the current recs, with counts (drives the
    filter UI).
  - `POST /api/recommendations/recompute` — re-runs `curate`.
  - `GET/POST /api/blacklist` (+ `POST /api/blacklist/{band_id}/unblock`) — block a band (also
    prunes its current recs so the feed updates instantly), list blocked, unblock.
  - `GET/POST /api/likes` (+ `POST /api/likes/unlike`) — **like** an item (♥): a positive
    dismissal ("I wishlisted/bought/followed it"). Inserts a `likes` row (table + migration `0004`),
    prunes the item from the feed now, and curation excludes liked items until your next collection
    crawl reflects the real action. Rec rows carry `album_id`/`track_id`; stats has `liked`.
  UI features: stat tiles, All/Albums/Tracks filter, 3-state genre-tag chips (off→include→exclude),
  click a band to filter by that label, **⊘ block** per card, a **Blocked (N)** panel to unblock,
  load-more, Recompute. **Curation now returns one rec per band** (`compute_recommendations(
  one_per_band=True)` — the band's top-scoring item). Run: `uvicorn app.main:app` (host venv +
  localhost override) → http://127.0.0.1:8000. Verified live (1,600 recs = 1,600 distinct bands;
  block/unblock/label-filter all work). `ruff` ignores B008 (FastAPI Depends idiom) + E501 for the
  UI template. Tag facets are sparse until more album *pages* are crawled (tags live there).
- **M6** pending (deploy). The compose `api`/`worker` services already build ./backend; wiring a
  real deploy target is what's left.

## Local infra — docker-compose (canonical, set up 2026-07-24)
Postgres 16 + Redis 7 run as containers via `docker-compose.yml` (services: `postgres`, `redis`,
`api`, `worker`). Docker runtime is **colima** (headless, Apple Virtualization.Framework — Docker
Desktop needs a GUI first-launch we can't automate). Compose maps pg→`localhost:5432`, redis→`localhost:6379`.
```bash
colima start                              # boot the docker VM (once per login)
docker compose up -d postgres redis       # bring up the data services
docker compose ps                         # both should be healthy
# app/worker containers (optional): docker compose up -d api worker   (builds ./backend)
docker compose down                       # stop; `down -v` also drops the pgdata volume
```
The gitignored `.env` uses compose hostnames (`@postgres`,`@redis`) — the `api`/`worker` containers
use those directly. **Running the app/alembic/scripts from the host venv needs the localhost override:**
```bash
cd backend && . .venv/bin/activate && set -a && . ../.env && set +a && \
  export DATABASE_URL='postgresql+asyncpg://crate:crate@localhost:5432/crate' \
         REDIS_URL='redis://localhost:6379/0'
```
DB `crate`/role `crate` (pw `crate`); schema at `0001_baseline`; the 2026-07-24 POC data was
pg_dump/restored into the compose volume (counts intact). Inspect:
`docker exec crate-digger-postgres-1 psql -U crate -d crate -c '\dt'`.
(An earlier ad-hoc `brew` Postgres/Redis was used first, then decommissioned via `brew services
stop postgresql@16 redis` — still installed but off, so it won't fight compose for the ports.)

## Immediate next steps
1. ~~Live end-to-end smoke test~~ ✅ done 2026-07-24 — `scripts.crawl seed && run 3` populated the
   graph (see M3 status above); 3 Nimble credits. To crawl wider: `python -m scripts.crawl run <N>`
   (each N = one more page render/credit) or run the ARQ worker (`arq app.worker.WorkerSettings`)
   for the self-perpetuating chain.
2. Consider a secondary budget cap (max total frontier size / max fetches per run) on top of the
   depth bound before a very wide run — depth 3 on a popular album still fans out wide.
3. **M4 (curation)** is now unblocked with real data in the DB: score unowned tracks/albums by
   supporter overlap + tag affinity + follow signals → `recommendations` table.

## Open decision — RESOLVED (2026-07-24)
Earlier flagged: local Python parsing vs Nimble server-side parsing, with the v2 parser def
format "unconfirmed." **It's confirmed now** — the `parser-builder` skill (imported to
`~/.claude/skills/parser-builder/`) documents the exact format offline (no credits to iterate):
`json` selectors + `coercion_filter` parse the JSON-encoded `data-tralbum`/`data-band` attrs and
auto-parse `network_capture` XHR bodies. So server-side parsing is a viable, unblocked option.
**We're keeping local parsing** (built, tested, free of parse credits, full control); server-side
is a thin adapter behind the same provider seam if we ever want to offload it. User confirmed the
Nimble parser can parse JSON and to prefer mimicking XHRs over render+scroll (both reflected above).

## Dev workflow
- Secrets live only in gitignored `.env` (`NIMBLE_API_KEY` as raw token — code adds `Bearer `;
  `BANDCAMP_FAN_URL=https://bandcamp.com/guron`). **Never commit the key or print it.** The key
  was exposed in plaintext in the Nimble skill file + likely `~/Downloads/nimnim.docx` — user
  should rotate it.
- Set up env & tests (no global venv persists between sessions):
  ```bash
  cd backend
  python3 -m venv .venv && . .venv/bin/activate   # 3.12+; this box has 3.14 only
  pip install -e ".[dev]" aiosqlite
  pytest -q                                        # 46 tests as of M3
  ```
  The `.env` lives at the **repo root** (not `backend/`); config reads it via env vars, so
  `set -a && . ../.env && set +a` before running scripts that need the Nimble key.
- Nimble calls cost credits (~3–35s each). Use `scripts/dump_extract.py <url> <out.json>` to
  save real responses and author parsers offline against them. Saved samples from this session
  were in the scratchpad (gone now); re-fetch if needed.
- v2 request quirks: `network_capture` items wrap the filter → `[{"filter":{"url":{"type":
  "contains","value":"..."}}}]`; `browser_actions` use the action as the key → `[{"auto_scroll":
  true},{"wait":2000}]`; parsed output at `response.data.parsing.entities`.

## Conventions
- Commit per milestone; end messages with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Enum-ish columns stored as strings (`app/enums.py`). JSON columns use `JSONVariant`
  (JSONB on Postgres, JSON elsewhere so SQLite tests work). `bands.url`/`albums.url` nullable
  (discover-by-id, enrich later).
