# Claude Routine Usage

*[Version française](README.md)*

Automated daily tracking of Claude usage (pay-as-you-go API **and** Pro/Max
subscription), written to a single JSON file consumable over HTTP by an
external routine (e.g. a "CTO Daily Brief").

The JSON is updated by two independent runs that merge their results into
the same file:

| Source | Where it runs | Frequency | Fields written |
|---|---|---|---|
| Anthropic **Admin API** (billed usage/cost) | ☁️ GitHub Actions — independent of your Mac's power state | Daily at 06:00 UTC | `total_input_tokens`, `total_output_tokens`, `total_cost_usd` |
| **Claude Code CLI** (`claude -p "/usage"` + local transcripts) | 💻 This Mac only (launchd) | Daily at 7am local time | `session_usage`, `model_usage_7d` |

## Why two sources?

- The **Admin API** only reports usage billed through the API (an
  organization with a pay-as-you-go API key). It has no visibility into a
  Pro/Max subscription.
- **Session/weekly quotas** and the **per-model breakdown** of a Pro/Max
  subscription don't exist anywhere in the public API — this data is local
  to the machine, exposed only by the `claude` CLI and the transcripts it
  writes to disk. It can therefore only be produced **locally**, never from
  a cloud runner.

Result: the file stays up to date for the billing portion even with the Mac
off, but the session/model fields only refresh while this Mac is on and
runs at 7am.

## Output file — `claude_usage_weekly.json`

```json
{
  "generated_at": "2026-07-28T08:28:59Z",
  "window_start": "2026-07-21T08:28:59Z",
  "window_end": "2026-07-28T08:28:59Z",
  "total_input_tokens": 0,
  "total_output_tokens": 0,
  "total_tokens": 0,
  "total_cost_usd": 0.0,
  "session_usage": {
    "session_used_pct": 14,
    "session_resets_at": "Jul 28 at 2:30pm (Europe/Paris)",
    "week_used_pct": 37,
    "week_resets_at": "Jul 31 at 9pm (Europe/Paris)",
    "captured_at": "2026-07-28T08:28:59Z"
  },
  "model_usage_7d": {
    "claude-sonnet-5": {
      "display_name": "Sonnet 5",
      "input_tokens": 1494921533,
      "output_tokens": 3248424,
      "pct_of_output": 58.4
    }
  }
}
```

`pct_of_output` = this model's share of total output tokens over the
window (`--days`, default 7) — the metric closest to what Claude Code's
`/usage` screen shows.

## Repo components

- **`claude_usage_weekly.py`** — the script. Always runnable on its own; the
  parts that depend on the local CLI (`session_usage`, `model_usage_7d`) are
  best-effort and silently no-op if `claude` isn't present (the GitHub
  Actions runner case), without overwriting the last known value in the
  JSON.
- **`.github/workflows/usage-report.yml`** — scheduled workflow (cron
  `0 6 * * *` = 06:00 UTC) plus manual trigger (`workflow_dispatch`).
  Commits the updated JSON back to the repo on every run.
- **`run_local.sh`** — wrapper invoked by launchd: `git pull --rebase`, runs
  the script, then commits + pushes if the file changed.
- **`.env`** (not committed) — `ANTHROPIC_ADMIN_API_KEY`, used by the local
  run. The cloud run uses a GitHub secret of the same name.

## Requirements

- An Anthropic **Admin API key** (`sk-ant-admin-...`), created at
  console.anthropic.com → Settings → Admin API keys (requires the admin role
  in the organization).
- For `session_usage` / `model_usage_7d`: being logged in locally to Claude
  Code with a Pro/Max subscription (`claude login`).
- Python 3.8+ with `requests` (`pip install -r requirements.txt`).

## Manual usage

```bash
export ANTHROPIC_ADMIN_API_KEY="sk-ant-admin-..."
python3 claude_usage_weekly.py            # writes claude_usage_weekly.json
python3 claude_usage_weekly.py --days 14  # custom lookback window
```

## Setting up the automation

Two mechanisms to configure separately — one cloud (GitHub Actions), one
local (launchd) — because neither can cover all the data on its own.

### 1. Cloud side — GitHub Actions

The workflow (`.github/workflows/usage-report.yml`) is already in the repo;
all that's missing is the secret:

1. On the repo page → **Settings → Secrets and variables → Actions**
2. **New repository secret** → name `ANTHROPIC_ADMIN_API_KEY` → paste the key
3. The job then runs automatically every day at 06:00 UTC (see the `cron`
   in the workflow file). To test without waiting: **Actions** tab → select
   the workflow → **Run workflow**.

The job checks out the repo, installs `requirements.txt`, runs the script
with the key as an environment variable, then commits+pushes the JSON if it
changed (`permissions: contents: write` in the workflow authorizes that
push).

### 2. Local side — launchd (macOS)

`session_usage` and `model_usage_7d` can only be produced on the machine
where `claude login` runs — so you need a **local** scheduler that triggers
`run_local.sh` every day. launchd is macOS's equivalent of cron, but able to
catch up on a missed run once the machine wakes up.

**a) Create the plist file**, e.g.
`~/Library/LaunchAgents/com.<you>.claude-usage-local.plist` (replace
`<you>` with an identifier of your choice — it's just a local label, not
tied to the repo):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.<you>.claude-usage-local</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>/absolute/path/to/this/repo/run_local.sh</string>
    </array>

    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>7</integer>
        <key>Minute</key><integer>0</integer>
    </dict>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>

    <key>StandardOutPath</key>
    <string>/absolute/path/to/this/repo/launchd.log</string>
    <key>StandardErrorPath</key>
    <string>/absolute/path/to/this/repo/launchd.error.log</string>

    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
```

> ⚠️ The `PATH` entry must list the directories containing your `python3`,
> `git`, and `claude` binaries — launchd does **not** inherit your
> interactive shell's `PATH`. Check with `which python3 git claude` and add
> the matching directories if needed.

**b) Load and test the job:**

```bash
launchctl load ~/Library/LaunchAgents/com.<you>.claude-usage-local.plist

# Confirm it's registered (status 0 = OK)
launchctl list | grep claude-usage

# Trigger an immediate run without waiting for 7am
launchctl start com.<you>.claude-usage-local

# Follow the logs
cat launchd.log launchd.error.log
```

The job stays loaded across Mac restarts. If the Mac is off/asleep at 7am,
that day's run is simply skipped — only `session_usage` /
`model_usage_7d` are affected; the Admin API portion stays current via the
cloud.

**To disable the local job:**

```bash
launchctl unload ~/Library/LaunchAgents/com.<you>.claude-usage-local.plist
```

## Known limitations

- `claude -p "/usage"` and the transcript format
  (`~/.claude/projects/*.jsonl`) are not documented/stable interfaces — a
  future Claude Code release could break the parsing without notice.
- `session_usage` and `model_usage_7d` only reflect activity **on this
  machine** — not claude.ai, not other devices.
- The GitHub Actions cron is fixed in UTC (no timezone/DST handling):
  06:00 UTC = 7am Paris in winter, 8am in summer.
