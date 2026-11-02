#!/bin/bash
# Runs claude_usage_weekly.py locally (so it can capture Claude Code's
# session/week usage via the `claude` CLI, which only exists on this
# machine) and pushes the resulting JSON back to the repo. Scheduled daily
# at 7h local time via a launchd job (see README.md for the plist setup).
#
# claude_usage_weekly.json is a generated file also committed by GitHub
# Actions: it is never merged. Each attempt restarts from origin/main (the
# script keeps the cloud fields already in the file) and retries if the
# push loses a race. Local edits to tracked files are discarded: commit
# them before the next 7h run.
set -euo pipefail
cd "$(dirname "$0")"

set -a
source .env
set +a

PYTHON3="/Library/Frameworks/Python.framework/Versions/3.11/bin/python3"

# Leftover from an interrupted run: never stay stuck on it.
git rebase --abort 2>/dev/null || true
git merge --abort 2>/dev/null || true

for attempt in 1 2 3; do
  git fetch origin main
  git checkout -q main
  git reset --hard origin/main
  "$PYTHON3" claude_usage_weekly.py
  git add claude_usage_weekly.json
  if git diff --cached --quiet; then
    exit 0
  fi
  git commit -m "chore: update usage report (local run)"
  if git push origin HEAD:main; then
    exit 0
  fi
  echo "push rejected (attempt $attempt), retrying from origin/main" >&2
  sleep 15
done
echo "ERROR: could not push after 3 attempts" >&2
exit 1
