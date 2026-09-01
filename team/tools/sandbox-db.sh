#!/bin/bash
# The team's sandbox database (E0-1). A real, isolated Postgres + Redis so cycles can run
# tests against something real instead of touching production or the SQLite-in-memory
# fixtures the existing pytest suite uses.
#
#   team/tools/sandbox-db.sh up     # bring it up, migrate to head, load the seed, curate it
#   team/tools/sandbox-db.sh down   # tear it down completely (drops the volume too)
#
# Ephemeral by design: `down` always drops the volume, so every `up` starts from a clean,
# freshly-migrated, freshly-seeded database. That's what lets QA trust what it finds there.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEAM="$ROOT/team"
COMPOSE_FILE="$TEAM/tools/docker-compose.sandbox.yml"
PROJECT="crate-team"

# Never trust an inherited DATABASE_URL/REDIS_URL — construct our own local ones explicitly,
# the same way run-cycle.sh scrubs the environment before loading team/.env.team. If either
# of these doesn't say localhost, something is wrong and we refuse rather than guess.
unset DATABASE_URL REDIS_URL
export DATABASE_URL="postgresql+asyncpg://crate:crate@localhost:55432/crate_team"
export REDIS_URL="redis://localhost:56379/0"

for url in "$DATABASE_URL" "$REDIS_URL"; do
  case "$url" in
    *localhost*|*127.0.0.1*) ;;
    *) echo "REFUSING: $url is not local. Sandbox must never point elsewhere." >&2; exit 1 ;;
  esac
done

cmd="${1:-}"

case "$cmd" in
  up)
    docker compose -p "$PROJECT" -f "$COMPOSE_FILE" up -d
    echo "waiting for postgres..."
    for _ in $(seq 1 30); do
      if docker compose -p "$PROJECT" -f "$COMPOSE_FILE" exec -T postgres pg_isready -U crate -d crate_team >/dev/null 2>&1; then
        break
      fi
      sleep 1
    done

    echo "migrating to head..."
    (cd "$ROOT/backend" && DATABASE_URL="$DATABASE_URL" .venv/bin/python3 -m alembic upgrade head)

    echo "loading seed data..."
    docker compose -p "$PROJECT" -f "$COMPOSE_FILE" exec -T postgres \
      psql -U crate -d crate_team -v ON_ERROR_STOP=1 < "$TEAM/fixtures/seed.sql"

    echo "computing recommendations for the seed..."
    (cd "$ROOT/backend" && DATABASE_URL="$DATABASE_URL" .venv/bin/python3 "$TEAM/tools/curate_seed.py")

    echo "sandbox ready: $DATABASE_URL"
    ;;
  down)
    docker compose -p "$PROJECT" -f "$COMPOSE_FILE" down -v
    ;;
  *)
    echo "usage: sandbox-db.sh {up|down}" >&2
    exit 2
    ;;
esac
