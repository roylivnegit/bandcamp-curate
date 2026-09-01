#!/bin/bash
# Entry point for the crate-digger agent team. launchd calls this every 20 minutes, but
# almost every call exits immediately and costs nothing: a cycle only starts when the
# subscription's five-hour usage window has actually turned over.
#
#   team/tools/run-cycle.sh                 # start a cycle if the window has reset
#   team/tools/run-cycle.sh --now           # start one regardless of the window
#   team/tools/run-cycle.sh --now --dry-run # ... and never push or open a PR
#   team/tools/run-cycle.sh --now --phases 1-3   # just the meeting
#
# Why a tick rather than a five-hour timer: the window is rolling, so its reset time moves
# with use. A fixed StartInterval drifts out of phase and eventually starts cycles halfway
# through a window. Polling a timestamp we already recorded is free and self-correcting.
#
# It deliberately does NOT source the repo's .env. That file holds the live Nimble key and a
# Neon connection string, and the team must never see either.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEAM="$ROOT/team"
STATE="$TEAM/memory/state.json"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$TEAM/logs/$STAMP.log"

mkdir -p "$TEAM/logs"

# ---- is the window fresh? ------------------------------------------------------------
# resets_at is written by the previous cycle from the CLI's rate_limit_event. Before it
# passes there is nothing left to spend, so exit without starting anything.
FORCE=0
ARGS=()
for arg in "$@"; do
  if [ "$arg" = "--now" ]; then FORCE=1; else ARGS+=("$arg"); fi
done

if [ "$FORCE" -eq 0 ] && [ -f "$STATE" ]; then
  RESETS_AT="$(python3 -c "import json;print(json.load(open('$STATE')).get('resets_at') or 0)")"
  NOW="$(date +%s)"
  if [ "$RESETS_AT" -gt "$NOW" ]; then
    echo "window resets in $(( (RESETS_AT - NOW) / 60 ))m — nothing to do"
    exit 0
  fi
fi

# ---- whose quota is this? ------------------------------------------------------------
# Roy moves between a personal Pro plan and Qodo's team plan during the day, and `claude`
# bills whichever is signed in. Rather than depend on which one he happens to be switched
# to, the team keeps its **own** login: CLAUDE_CONFIG_DIR gives a config directory its own
# independent auth state, so the team's account and his interactive account coexist and
# neither disturbs the other. Nothing to remember, nothing to switch back.
#
# Set it up once, in a terminal (it opens a browser):
#     CLAUDE_CONFIG_DIR=~/.claude-team claude auth login
#
# If that directory is not logged in yet we fall back to the default config, and the account
# check below is what stops a cycle from spending the wrong plan's quota.
TEAM_ACCOUNT="${TEAM_CLAUDE_ACCOUNT:-royee.livne6@gmail.com}"
TEAM_CONFIG_DIR="${TEAM_CLAUDE_CONFIG_DIR:-$HOME/.claude-team}"

account_in() {  # $1 = config dir, or empty for the default
  if [ -n "$1" ]; then
    CLAUDE_CONFIG_DIR="$1" claude auth status 2>/dev/null
  else
    claude auth status 2>/dev/null
  fi | python3 -c 'import json,sys;print(json.load(sys.stdin).get("email") or "")' 2>/dev/null || true
}

if [ "$(account_in "$TEAM_CONFIG_DIR")" = "$TEAM_ACCOUNT" ]; then
  export CLAUDE_CONFIG_DIR="$TEAM_CONFIG_DIR"
  echo "using the team's own login ($TEAM_ACCOUNT) from $TEAM_CONFIG_DIR"
else
  ACTIVE="$(account_in "")"
  if [ "$ACTIVE" != "$TEAM_ACCOUNT" ]; then
    echo "no team login in $TEAM_CONFIG_DIR, and the default config is signed in as"
    echo "${ACTIVE:-nobody} rather than $TEAM_ACCOUNT — skipping this window."
    echo "To give the team its own account:  CLAUDE_CONFIG_DIR=$TEAM_CONFIG_DIR claude auth login"
    exit 0
  fi
  echo "using the default config, signed in as $TEAM_ACCOUNT"
fi

# ---- one cycle at a time -------------------------------------------------------------
PIDFILE="$TEAM/logs/.cycle.pid"
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "a cycle is already running (pid $(cat "$PIDFILE")); exiting" | tee -a "$LOG"
  exit 0
fi
echo $$ > "$PIDFILE"

cleanup() {
  [ -x "$TEAM/tools/sandbox-db.sh" ] && "$TEAM/tools/sandbox-db.sh" down >>"$LOG" 2>&1 || true
  rm -f "$PIDFILE"
}
trap cleanup EXIT

# ---- environment: sandbox only -------------------------------------------------------
# Scrub anything inherited that could reach production or spend credits.
unset NIMBLE_API_KEY DATABASE_URL REDIS_URL BANDCAMP_FAN_URL || true

set -a
# shellcheck disable=SC1091
[ -f "$TEAM/.env.team" ] && . "$TEAM/.env.team"
set +a

if [[ "${DATABASE_URL:-}" == *neon* || "${DATABASE_URL:-}" == *render* ]]; then
  echo "REFUSING: DATABASE_URL points at a hosted database." | tee -a "$LOG"
  exit 1
fi
if [ -n "${NIMBLE_API_KEY:-}" ]; then
  echo "REFUSING: NIMBLE_API_KEY is set. The team must not be able to spend credits." | tee -a "$LOG"
  exit 1
fi

# ---- sandbox database ----------------------------------------------------------------
# Built by the team as Sprint 0 item E0-1. Until it exists, cycles still run — QA marks the
# database-backed gates `skipped` and says why, which is exactly the signal that E0-1 matters.
if [ -x "$TEAM/tools/sandbox-db.sh" ]; then
  "$TEAM/tools/sandbox-db.sh" up >>"$LOG" 2>&1 || echo "sandbox-db up failed; continuing" >>"$LOG"
fi

# ---- run -----------------------------------------------------------------------------
cd "$ROOT"
echo "=== cycle $STAMP ===" >>"$LOG"
# `caffeinate -i` holds off idle sleep for exactly as long as the cycle runs. Without it a
# cycle dies mid-response — this box sleeps after a minute idle, and an unattended run has
# nobody touching the keyboard. `-i` blocks idle sleep only; closing the lid still sleeps.
#
# `|| true` because the explicit status capture below is what decides the exit code. With
# `set -e` and pipefail, a failed cycle otherwise killed the script here — before the
# summary it had just written could be emailed.
caffeinate -i python3 "$TEAM/tools/cycle.py" ${ARGS[@]+"${ARGS[@]}"} 2>&1 | tee -a "$LOG" || true
status=${PIPESTATUS[0]}

# ---- report --------------------------------------------------------------------------
# cycle.py writes the summary in a `finally`, so there is one even when the cycle crashed or
# ran out of window. Sending it happens here, in the shell, so the SMTP credential in the
# Keychain is never reachable from an agent turn. A failed send never fails the cycle.
SUMMARY="$(ls -1t "$TEAM/logs"/*-summary.md 2>/dev/null | head -1)"
if [ -n "$SUMMARY" ]; then
  python3 "$TEAM/tools/notify.py" "$SUMMARY" 2>&1 | tee -a "$LOG" || true
fi

# Keep the last 60 logs. Transcripts are the permanent record; these are just plumbing.
ls -1t "$TEAM/logs"/*.log 2>/dev/null | tail -n +61 | xargs -r rm -f

exit "$status"
