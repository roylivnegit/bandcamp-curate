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

## Status (as of 2026-07-24)
- **M0 Scaffold** ✅ committed (`da93068`) — FastAPI skeleton, 15-table schema, Alembic
  baseline (builds from ORM metadata), docker-compose, health endpoints.
- **M1 Nimble waterfall** ✅ committed (`25443bb`) — `ScraperProvider` ABC, `NimbleProvider`
  (v2 `/extract`, Bearer, maps 401/402/429/5xx → `data.parsing.entities`), `ScraperGateway`
  (priority fallback, quota→circuit-open, 429→backoff, auth→fail-fast), rate limiter, cache,
  `provider_usage` logging. **Live smoke test passed (HTTP 200).** Also updated the
  `nimble-webit-api` skill in ~/Downloads to v2 and scrubbed the leaked key from it.
- **M2 Parsers + mappers** 🔨 in progress (NOT yet committed):
  - ✅ `fan_collection`: `parse_fan_page()` + `ingest_fan_collection()` mapper, 23 tests pass
    (incl. in-memory SQLite mapper tests, idempotency, is_me→follows rule).
  - ✅ `album_page`: structure confirmed (`data-tralbum` id/url/`current.title`/`trackinfo[]`,
    `data-band` id+name, tags via `<a class="tag">`). Parser/mapper **not written yet**.
  - 🔨 `album_supporters`: supporters are in the album **HTML DOM** (`<a class="fan pic"
    href="https://bandcamp.com/<user>?from=fanthanks">`), NOT in any JSON blob; only ~first
    page embedded, rest via a collectors API. Parser **not written yet**.
- **M3–M6** pending (crawl workers, curation, API+UI, deploy).

## Immediate next steps
1. Write `parse_album_page()` (album/tracks/band/tags) + `parse_album_supporters()` (regex/DOM
   for `class="fan pic" href="https://bandcamp.com/<user>"`), add mappers + fixture tests.
2. Commit M2.
3. M3: seed ingest from `BANDCAMP_FAN_URL`, ARQ crawl workers over the supporter→collection
   frontier (use the `collection_items` API for full pagination — item objects share the shape
   `parse_collection_item()` already handles).

## Open decision (flag to the user)
The plan chose Nimble **server-side parsit-ai** parsing, but the data turned out to be clean
embedded JSON and the exact v2 `parser` def format is unconfirmed (would cost credits to
iterate). We're parsing **locally** instead (free, robust). Swapping to parsit-ai later is a
thin adapter. Confirm this is acceptable or revisit.

## Dev workflow
- Secrets live only in gitignored `.env` (`NIMBLE_API_KEY` as raw token — code adds `Bearer `;
  `BANDCAMP_FAN_URL=https://bandcamp.com/guron`). **Never commit the key or print it.** The key
  was exposed in plaintext in the Nimble skill file + likely `~/Downloads/nimnim.docx` — user
  should rotate it.
- Set up env & tests (no global venv persists between sessions):
  ```bash
  cd backend
  python3.12 -m venv .venv && . .venv/bin/activate
  pip install -e ".[dev]" aiosqlite
  pytest -q
  ```
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
