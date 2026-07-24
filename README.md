# crate-digger

A personal Bandcamp discovery engine. It mines your Bandcamp collection, walks the
social graph (album **supporters** → their **collections**), and surfaces a curated,
filterable feed of tracks you don't yet own — ranked by how many "fans like you" own
them, filtered by rules and a blacklist you control.

Scraping runs **exclusively through Nimble (v2 API)** behind a pluggable provider seam,
so cheaper/fallback providers can be added later without touching call sites.

> ⚠️ Personal-use tool. Keep request rates low and cache aggressively. Respect
> Bandcamp's Terms of Service.

## Stack

- **Backend:** Python 3.12+ / FastAPI (async), SQLAlchemy 2.0 + Alembic, Postgres
- **Jobs:** Redis + ARQ workers with a token-bucket rate limiter
- **Scraping/parsing:** Nimble v2 `/extract` with server-side `parser` defs (`backend/nimble_parsers/`)
- **UI:** React + Vite (added in M5)
- **Packaging:** Docker Compose (postgres, redis, api, worker, ui)

## Quick start (local)

```bash
cp .env.example .env        # then fill in NIMBLE_API_KEY and BANDCAMP_FAN_URL
docker compose up --build   # postgres + redis + api (+ worker/ui as they land)
# API docs:   http://localhost:8000/docs
# Health:     http://localhost:8000/health
```

Run DB migrations (first boot / after model changes):

```bash
docker compose run --rm api alembic upgrade head
```

## Layout

```
backend/
  app/
    main.py            FastAPI app + routers
    config.py          pydantic-settings (reads .env)
    db/                models, session, alembic migrations
    scraping/          provider abstraction, Nimble provider, gateway, rate limiter, cache
    bandcamp/          maps parsed Nimble output → DB models
    crawl/             frontier + ARQ workers + seed ingest
    curation/          similarity/affinity scoring + rules
    api/               REST routers (feed, blacklist, rules, jobs, usage)
  nimble_parsers/      versioned Nimble parser defs (JSON)
frontend/              React + Vite SPA
```

See [the build plan](../.claude/plans/i-want-to-create-purrfect-pascal.md) for milestones (M0–M6).
