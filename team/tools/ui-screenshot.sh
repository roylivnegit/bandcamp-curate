#!/bin/bash
# Captures real screenshots of the current UI (sandbox + seed data, same visual code as
# production) into team/artifacts/screenshots/, so a design or build turn can Read them
# before touching UI/UX work. Same sandbox-lifecycle shape as team/tools/e2e.sh.
#
#   team/tools/ui-screenshot.sh

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

cd "$ROOT/frontend" && npx playwright test capture-screenshots.spec.ts
