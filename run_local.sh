#!/bin/bash
# Runs claude_usage_weekly.py locally (so it can capture Claude Code's
# session/week usage via the `claude` CLI, which only exists on this
# machine) and pushes the resulting JSON back to the repo. Scheduled daily
# at 7h local time via a launchd job (see README.md for the plist setup).
set -euo pipefail
cd "$(dirname "$0")"

set -a
source .env
set +a

git pull --rebase --autostash origin main

PYTHON3="/Library/Frameworks/Python.framework/Versions/3.11/bin/python3"
"$PYTHON3" claude_usage_weekly.py

git add claude_usage_weekly.json
if ! git diff --cached --quiet; then
  git commit -m "chore: update usage report (local run)"
  git push
fi
