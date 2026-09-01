#!/bin/bash
# Runs the E2E suite (E0-4) against a fresh sandbox database. One command for QA to invoke —
# same sandbox-lifecycle shape as run-cycle.sh already uses.
#
#   team/tools/e2e.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

cleanup() { "$ROOT/team/tools/sandbox-db.sh" down; }
trap cleanup EXIT

"$ROOT/team/tools/sandbox-db.sh" up

set -a
TEAM_API_PORT=58000
TEAM_WEB_PORT=55173
VITE_API_BASE_URL="http://localhost:58000"
set +a

cd "$ROOT/frontend" && npx playwright test
