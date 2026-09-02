#!/bin/bash
# Pings crate-digger-api's /health every 10 minutes (via the launchd job below) so
# Render's free plan doesn't spin the service down between visits. See CLAUDE.md's
# "M6 cloud deploy" section for why the API sleeps, and ai.crate-digger.keepalive.plist
# for install/uninstall.
set -uo pipefail

URL="https://crate-digger-api-ojvi.onrender.com/health"
LOG_DIR="/Users/roylivne/crate-digger/ops/logs"
LOG="$LOG_DIR/keepalive.log"
mkdir -p "$LOG_DIR"

ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
result="$(curl -s -o /dev/null -w '%{http_code} %{time_total}s' --max-time 60 "$URL")"
if [ -z "$result" ]; then
  result="000 -"
fi
echo "$ts $result" >> "$LOG"

# Keep the log from growing forever over months of 10-minute pings.
tail -n 1000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
