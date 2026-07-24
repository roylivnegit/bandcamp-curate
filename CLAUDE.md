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
- **M3 Crawl workers** 🔨 in progress (committed): `app/crawl/` = frontier repo (`crawl_frontier`,
  idempotent enqueue/claim/complete) + `service` (`crawl_fan_collection`→enqueue owned albums;
  `crawl_album`→ingest supporters, enqueue their collections) + `runner` (Redis-free driver) +
  `seed`. `app/worker.py` = ARQ adaptor (`seed_crawl`/`crawl_next` self-perpetuating chain).
  `scripts/crawl.py` = in-process CLI (`seed`/`run`/`status`). All crawl logic unit-tested with a
  fake fetcher over the fixtures (no credits). **Not yet run against live infra** (needs Postgres+Redis).
- **Collection pagination = mimic the XHR, not render+scroll.** `app/bandcamp/collection_api.py`
  (`CollectionApiClient`) POSTs Bandcamp's public `api/fancollection/1/collection_items`
  (`{fan_id, older_than_token, count}` → `{items, last_token, more_available}`) directly and
  pages via `last_token`. The fan page is rendered once (for fan_id + first page + token); the
  rest comes from the API. Items share the shape `parse_collection_item()` already handles.
  Endpoint is public/no-auth; direct httpx now, swap transport to route via Nimble if IP-throttled.
- **M4–M6** pending (curation, API+UI, deploy).

## Immediate next steps
1. Stand up Postgres+Redis (docker-compose), `alembic upgrade head`, then
   `python -m scripts.crawl seed && python -m scripts.crawl run 3` for a live smoke test.
2. Live-verify one `collection_items` POST against the real API (confirm body/`last_token`/
   `more_available` field names for `guron`'s fan_id) — the client is unit-tested vs a
   `MockTransport` but hasn't hit Bandcamp yet.
3. Supporter deep-pagination: the album's `#collectors-data` blob gives the first page +
   `more_thumbs_available` + a `token`; add the analogous thumbs-XHR client (needs one live
   sample to confirm the endpoint/shape).
4. Add crawl bounds (depth/budget caps) before a wide run — the frontier only dedups by
   (url,kind); it doesn't yet cap fan-out.

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
  pytest -q                                        # 38 tests as of M3 start
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
