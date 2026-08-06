# crate-digger — working notes for Claude

Personal Bandcamp discovery engine. Mines your Bandcamp collection, walks the social
graph (album **supporters** → their **collections**), and produces a curated, ranked
feed of tracks you don't own yet. Full build plan: `~/.claude/plans/i-want-to-create-purrfect-pascal.md`.

## Stack & layout
- **Backend:** Python 3.12+ / FastAPI (async), SQLAlchemy 2.0 + Alembic, Postgres. JSON API only —
  it serves no HTML.
- **Frontend:** separate React app (`frontend/`, Vite + TypeScript), own origin, talks to the API
  over CORS with a JWT bearer token. **Read `frontend/CLAUDE.md` before touching it** — the React
  perf/correctness and UI/UX rules the app is written to (memoized list rows, stale-response tickets,
  lazy routes, announced errors, coarse-pointer touch targets), distilled from the
  `react-best-practices` and `ui-ux-pro-max` skills, plus the conflicts left deliberately unresolved.
- **Jobs:** Redis + ARQ workers + token-bucket rate limiter.
- **Scraping:** Nimble **v2** `/extract` only, behind a provider seam (`app/scraping/`).
- **Parsing:** Bandcamp embeds clean JSON in the page (`#pagedata data-blob`, `data-tralbum`,
  `data-band`); we parse it **locally in Python** (`app/bandcamp/parse.py`) rather than
  Nimble server-side parsit-ai — see "Open decision" below.
- Layout: `backend/app/{scraping,bandcamp,db,api,auth,crawl,curation}`, `backend/nimble_parsers/`
  (unused so far), `backend/tests/`, `backend/scripts/`; `frontend/src/{api,auth,components,
  features,styles}`.

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
  Both are injectable (fakes in tests, `MockTransport` unit tests). **Both endpoints live-verified
  2026-07-24** against `guron`'s collection (40 items/page) + `panchito`'s supporters.
- **Pagination transport — Nimble by default now** (`pagination_via_nimble=True`). Each client takes
  a `gateway`; when set, the POST is routed through Nimble (`nimble_transport.post_json_via_nimble`:
  `render:false, method:POST, body:<json>` → JSON in `data.html`) instead of direct httpx. Verified:
  40 concurrent fan paginations through Nimble → **0 × 429** (Nimble rotates the exit IP), vs the
  direct path which 429s under load. Cost: **1 credit/page** (direct is free) — and these calls are
  now rate-limited, retried, and logged to `provider_usage` (parser `bc_api`) / counted in the crawl
  budget, exactly like renders. `build_pagination_clients(gateway, via_nimble=…)` wires the worker +
  CLI; flip `PAGINATION_VIA_NIMBLE=false` for the free direct path. `FetchRequest.cache_key` now folds
  in an `extra` digest so same-URL POSTs don't collide in the cache.
- **A scan is a CHAIN of short jobs, not one long one** (`scan_service.SCAN_SLICE_ENTRIES = 10`).
  `advance_scan` drains at most 10 frontier entries and returns "more?"; the ARQ `run_scan` job
  re-enqueues itself while that's true (same self-perpetuating shape as the legacy `crawl_next`),
  then calls `finalize_scan`. No single job can outlive `job_timeout` however big the crawl is, the
  chain survives worker restarts, and the UI sees progress as it goes (the frontend already polls
  `scan.status`). `run_scan` is kept as the blocking form for the CLI/tests: start → slices → finalize.
  - **The owner's own fan page is now an ordinary frontier entry** (`SELF_FAN_PRIORITY = 100`, so it
    drains first; the runner marks it `is_me` by URL). It resumes via the same cursor as everyone
    else, which retired `MAX_COLLECTION_VISITS`. `user.fan_id` is linked from the crawl outcome the
    slice that ingests it — so slice 1 has no `seed_fan_id` and the followed-artist prune is inactive
    for that slice only (harmless: depth-2 entries aren't reached that early, and curation excludes
    them regardless).
  - `finalize_scan` **refuses to curate** if that self-crawl entry isn't DONE (e.g. the credit budget
    ran out mid-collection) — every exclusion comes from it, so curating early silently surfaces
    artists you already own/follow. The scan errors instead: visible, re-runnable, resumes cheaply.
- **Pagination is bounded per visit and resumable** (`service.PAGES_PER_VISIT = 10`). A visit to a
  fan collection spends at most 10 pagination requests and **commits after every page**; leftover
  tokens come back as `CrawlOutcome.cursor` and the runner parks the entry back as PENDING carrying
  them (`frontier.mark_partial` → `crawl_frontier.cursor`, JSON `{fan_id, collection, wishlist,
  follows}`, migration `0009`). A resumed visit **skips the fan-page render** — the cursor holds
  everything needed, so it costs only its pagination. `claim_next` now orders by `priority DESC,
  attempts ASC, id ASC`: `attempts` makes the queue sweep in *passes*, so every collection gets a
  bounded slice before any gets a second, instead of one whale monopolising the crawl.
  - **Why:** collections are big (p90 ≈ 1,700 items ≈ 43 pages) and the old loop accumulated every
    page in memory, committing once at the end. On 2026-08-06 that blew past ARQ's `job_timeout`
    (600s) twice: **245 Nimble credits spent, zero rows persisted**, frontier counts unmoved.
    Per-page commits mean an interruption now costs one page, not the whole collection.
  - Newly discovered work (`attempts=0`) still outranks a parked collection (`attempts=1`), so a
    pass discovers broadly and then spends the budget tag-crawling what it found. Note that
    `run_scan`'s own-collection branch is NOT frontier-backed, so it drains visits in a loop
    (`MAX_COLLECTION_VISITS`) — your wishlist/follows must be complete or curation under-excludes.
- **Fan-out is bounded by depth** (`crawl_frontier.depth`, seed=0; `crawl_max_depth` config,
  default 3) **and by a request budget** (`crawl_max_requests`, default 100 = cumulative successful
  provider fetches; enforced in `runner.run_until_empty` + the ARQ `crawl_next` chain). Ingest
  still happens at the boundary, only outward enqueue stops.
- **Fan-out is also pruned by your follows** (`service.FOLLOWED_FILTER_MIN_DEPTH = 2`): from depth 2
  down (a neighbour's collection), an owned item whose artist/label you already follow is **ingested
  but not detail-crawled** — the ownership edge is the co-ownership signal, while its page (tags,
  supporters, subgraph) only feeds recs curation excludes anyway. `service.followed_bands(fan_id)`
  loads the follows once per collection and matches on **band bandcamp_id OR storefront host** — the
  same pair `curation.build_exclusions` uses, because a followed *label*'s releases carry the
  *artist's* band_id and are only identifiable by subdomain (`app/bandcamp/urls.url_host`, now shared
  by crawl + curation). Threaded as `seed_fan_id` from `run_scan` (the scan owner's `user.fan_id`,
  picked up right after the depth-0 collection crawl that creates it) → `run_until_empty` →
  `process_one/process_entry` → `crawl_fan_collection`. `seed_fan_id=None` (the legacy operator
  crawl chain) disables it. Counted per crawl as `CrawlOutcome.skipped_followed` and logged.
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
    dismissal ("I wishlisted/bought/followed it"). Inserts a `likes` row (table + migration `0004`)
    and curation excludes the liked item **and its band** — liking one release means you've engaged
    with that artist, so the whole band drops from the feed (else one-per-band dedup would re-surface
    it via another release). The like also prunes that band's current recs immediately. Holds until
    your next collection crawl reflects the real action; unlike brings the band back. Rec rows carry
    `album_id`/`track_id`; stats has `liked`.
  **Curation returns one rec per band** (`compute_recommendations(one_per_band=True)` — the band's
  top-scoring item). `ruff` ignores B008 (the FastAPI `Depends`/`Query` idiom). Tag facets stay
  sparse until more album *pages* are crawled (tags live there).
  **NOTE: `app/api/ui.py` is gone** — the server-rendered feed was replaced by the React app in
  M8 (below). The backend serves no HTML; `GET /` is a 404.
- **M6 Deploy** 🔨 self-hosted stack done (committed): `docker compose up -d` brings up the **whole
  app** — `postgres`, `redis`, a one-shot `migrate` (runs `alembic upgrade head`, then api/worker
  wait on `service_completed_successfully`), `api` (uvicorn, `/health` healthcheck), and `worker`
  (`arq app.worker.WorkerSettings`). Dockerfile fixed (was `pip install .` before copying `app/` →
  build failed); baked image = a real deployable (no host source needed). `docker-compose.dev.yml`
  overlay bind-mounts source + adds `--reload` for dev. Verified live: all services healthy, api
  serves the real data in-container, worker connected to Redis.
- **M6 cloud deploy — Option A (free, in progress 2026-07-25):** hosted **read** API on Neon, crawl
  stays **local**. Architecture: **Neon** (managed Postgres, eu-central-1, free) holds the data; a
  free **Render** web service (Frankfurt, Docker) reads Neon and serves the feed UI anywhere (phone);
  **crawls run on the Mac** on-demand and write to Neon (you control Nimble spend, using the local
  key). **No Redis, no 24/7 worker** — on-demand crawl uses the Redis-free `runner.run_until_empty`,
  and the API only reads Postgres.
  - **DB URL normalizer** (`app/db/url.normalized_async_url`, wired into `get_engine` + alembic env):
    managed providers hand you `postgresql://…?sslmode=require&channel_binding=require` with no
    `+asyncpg` — the normalizer forces the async driver, maps `sslmode`→asyncpg's `ssl` connect arg,
    strips libpq-only params; no-ops for local/sqlite URLs. Use Neon's **DIRECT** (non-pooled)
    endpoint — the `-pooler` one is PgBouncer/txn-mode and breaks asyncpg prepared statements.
  - **`.env` quoting:** the Neon URL contains `&`, so it MUST be single-quoted in `.env` or
    `set -a && . ../.env` backgrounds on the ampersand and silently falls back to the config default
    (localhost). Bit me once — quoted now.
  - **Data migrated** (2026-07-25): `pg_dump` local compose PG → restore into Neon via the postgres
    container's `psql` (`--no-owner --no-privileges`, direct endpoint). Row counts match exactly
    (fans 97 / bands 5,252 / albums 15,938 / tracks 42,269 / fan_items 22,606 / album_tags 35,156),
    schema at `0005`. `.env` `DATABASE_URL` now points at Neon direct → host scripts/uvicorn hit Neon.
  - **Deployable validated:** `render.yaml` (free Frankfurt web service, `backend/Dockerfile`,
    `/health`, `DATABASE_URL` set in-dashboard). Dockerfile CMD binds `${PORT:-8000}` (Render injects
    PORT; compose still overrides to 8000). Built the image and ran it with `PORT=10000` +
    `DATABASE_URL=<neon>` → `/health`, UI, and `/api/stats` all serve **live Neon data**. Hosted API
    needs only `DATABASE_URL` (all config fields have safe defaults; no Nimble key / Redis on cloud).
  - **Remaining (user click-ops, browser OAuth — can't automate):** push repo to GitHub (private ok;
    `.env` is gitignored so no secrets leak), then Render → New → Blueprint → pick repo → set
    `DATABASE_URL` = Neon direct url → deploy. Then the feed is live on the Render URL.
  - **Going-forward workflow:** crawl locally (`cd backend && . .venv/bin/activate && set -a &&
    . ../.env && set +a && python -m scripts.crawl run <N>`) → writes Neon; recompute via the hosted
    API's `POST /api/recommendations/recompute` (or `scripts.curate` locally); browse on the Render
    URL. (Fly/Railway/VPS still an option; compose remains the fully-local alternative.)

## Local infra — docker-compose (canonical, set up 2026-07-24)
Postgres 16 + Redis 7 + api + worker run via `docker-compose.yml`. Docker runtime is **colima**
(headless, Apple Virtualization.Framework — Docker Desktop needs a GUI first-launch we can't
automate). Compose maps pg→`localhost:5432`, redis→`localhost:6379`, api→`localhost:8000`.
```bash
colima start                              # boot the docker VM (once per login)
docker compose up -d                      # WHOLE stack: pg + redis + migrate + api + worker
docker compose ps                         # api healthy, worker up
docker compose logs -f worker             # follow the crawl worker
# dev (live reload): docker compose -f docker-compose.yml -f docker-compose.dev.yml up
docker compose down                       # stop; `down -v` also drops the pgdata volume
```
Just the data services (for host-run uvicorn/scripts): `docker compose up -d postgres redis`.
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

## M8 — multi-tenant auth + React frontend (2026-07-26/27)
- **Auth (merged, PR #7)**: JWT bearer tokens (PyJWT HS256, `AUTH_SECRET_KEY`) + bcrypt directly
  (not passlib). Signup is gated by a shared `AUTH_INVITE_CODE` — every scan runs on the operator's
  Mac against their Nimble credits, so it can't be open. `app/auth/security.py` holds
  hash/verify/`create_access_token`/`get_current_user`/`require_auth_configured`.
- **Real multi-tenancy.** New `users` table; `user_id` on `scans`/`likes`/`blacklist`
  (recommendations/scan_seeds scope transitively via `scan_id`). **`users.fan_id` — not the legacy
  `Fan.is_me` flag — is now the "which Fan am I" mechanism.** The Bandcamp catalog + social graph
  (bands/albums/tracks/tags/fans/fan_items/supporters/crawl_frontier) stays **global and shared**:
  one user's crawl enriches everyone's discovery. Migration `0008` backfills an operator user from
  the pre-existing `is_me` fan and **aborts rather than leaving NULL owners** (an unowned row would
  be permanently invisible to ownership scoping).
  - Fixed 4 cross-tenant leaks found along the way: `follows` had **no per-fan scoping at all**
    (globally unique on `band_id` — one user's follow suppressed that band for everyone; now
    `follows.fan_id` + composite unique), `blacklist`/`likes` exclusions were queried globally in
    `build_exclusions`, and `/api/stats` both resolved "me" via a global `is_me` lookup **and**
    counted neighbours as `is_me == False` (which excludes every *other* tenant's own fan).
  - **Per-user collection onboarding**: signup creates a seedless `Scan(kind=collection)`;
    `scan_service.run_scan` branches on that kind to crawl the user's own `bandcamp_fan_url`
    directly and set `user.fan_id`, then falls into the same drain+curate path as a custom scan.
    Previously "crawl my collection" and "the collection Scan row" were disconnected mechanisms.
  - `scripts/set_password.py <username> <pw>` — required once after migrating, since the migration
    can't hash a password (backfilled users carry an unusable `!` placeholder).
- **React frontend** (`frontend/`, Vite + React + TS + react-router): replaces `app/api/ui.py`,
  which is **deleted**. Separate origin, so the backend is a pure JSON API behind CORS
  (`FRONTEND_ORIGIN`). Bearer token in `localStorage`; a 401 anywhere drops the session — except on
  `/api/auth/login|signup`, where a 401 is a wrong password, not an expired session.
  `npm run dev` (port 5173, strict) + `npm test` (17 vitest tests).
- **Deploy**: `render.yaml` now defines two services — `crate-digger-api` (Docker) and
  `crate-digger-web` (static, with a `/*` → `index.html` rewrite so client routes survive a
  refresh). `VITE_API_BASE_URL` and `FRONTEND_ORIGIN` are dashboard-set, **not** `fromService`:
  that yields a bare host and both need the scheme.

## Immediate next steps
1. Consider a secondary budget cap (max total frontier size / max fetches per run) on top of the
   depth bound before a very wide run — depth 3 on a popular album still fans out wide.
2. **Per-user crawl budgets.** `crawl_max_requests`/`provider_usage` are still global, so one
   user's deep scan can starve everyone else's. Fine at one or two users; revisit beyond that.
3. Retire or relabel the legacy `seed_crawl`/`crawl_next` ARQ chain and `scripts/crawl.py`, which
   still key off the single global `BANDCAMP_FAN_URL` (documented as operator-only for now).

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
  pytest -q                                        # 142 tests as of M8
  ```
  The `.env` lives at the **repo root** (not `backend/`); config reads it via env vars, so
  `set -a && . ../.env && set +a` before running scripts that need the Nimble key.
- Frontend (separate app, own toolchain):
  ```bash
  cd frontend && npm install
  npm run dev     # http://localhost:5173, strict port — the API's CORS default expects it
  npm test        # 17 vitest tests;  npm run build / npm run lint
  ```
  `frontend/.env.local` sets `VITE_API_BASE_URL` (defaults to the local uvicorn). Running the API
  locally for the frontend also needs `AUTH_SECRET_KEY` + `AUTH_INVITE_CODE` exported.
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
