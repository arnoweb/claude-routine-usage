#!/usr/bin/env python3
"""
claude_usage_weekly.py

Pulls the last 7 days of Claude API usage (tokens) and cost from Anthropic's
Admin API and writes a small JSON summary to disk.

Requirements:
  - An Admin API key (starts with "sk-ant-admin...") from
    console.anthropic.com -> Settings -> Admin API keys.
    Only org members with the admin role can create one.
  - This key must be set as an environment variable, never hardcoded:
      export ANTHROPIC_ADMIN_API_KEY="sk-ant-admin-..."
  - Python 3.8+, `requests` (pip install requests)

Usage:
  python3 claude_usage_weekly.py
  (writes to the default path below unless --out overrides it)

Run this manually each Monday morning before 8h04 (or via a local cron job/
launchd task). The default output folder is already connected to Cowork, so
the "CTO Daily Brief" scheduled task can read the file and fold the numbers
into the report without any extra setup.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

try:
    import requests
except ImportError:
    sys.exit("Missing dependency: run `pip install requests` first.")

API_BASE = "https://api.anthropic.com/v1/organizations"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_OUT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "claude_usage_weekly.json"
)

MODEL_DISPLAY_NAMES = {
    "claude-fable-5": "Fable 5",
    "claude-mythos-5": "Mythos 5",
    "claude-opus-4-8": "Opus 4.8",
    "claude-opus-4-7": "Opus 4.7",
    "claude-opus-4-6": "Opus 4.6",
    "claude-opus-4-5": "Opus 4.5",
    "claude-opus-4-1": "Opus 4.1",
    "claude-opus-4-0": "Opus 4",
    "claude-sonnet-5": "Sonnet 5",
    "claude-sonnet-4-6": "Sonnet 4.6",
    "claude-sonnet-4-5": "Sonnet 4.5",
    "claude-sonnet-4-0": "Sonnet 4",
    "claude-haiku-4-5": "Haiku 4.5",
    "claude-3-haiku": "Haiku 3",
}


def _display_name(model_id: str) -> str:
    for prefix, name in MODEL_DISPLAY_NAMES.items():
        if model_id.startswith(prefix):
            return name
    return model_id


def fetch_report(endpoint: str, api_key: str, starting_at: str, ending_at: str) -> dict:
    url = f"{API_BASE}/{endpoint}"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
    }
    params = {
        "starting_at": starting_at,
        "ending_at": ending_at,
        "bucket_width": "1d",
    }
    results = []
    page = None
    while True:
        if page:
            params["page"] = page
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        results.extend(data.get("data", []))
        if data.get("has_more") and data.get("next_page"):
            page = data["next_page"]
        else:
            break
    return results


def get_session_usage() -> dict | None:
    """Best-effort: capture Claude Pro/Max session+week quota via the local
    Claude Code CLI (`claude -p "/usage"`). Only works on a machine that is
    logged into Claude Code with a Pro/Max subscription (OAuth) - returns
    None (and the caller keeps whatever was last recorded) if the CLI isn't
    installed, isn't authenticated, or the output format doesn't match.
    Undocumented CLI behavior - may break on a future Claude Code release.
    """
    try:
        result = subprocess.run(
            ["claude", "-p", "/usage"],
            capture_output=True, text=True, timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None

    text = result.stdout
    session_match = re.search(r"Current session:\s*(\d+)% used\s*\S\s*resets (.+)", text)
    week_match = re.search(r"Current week \(all models\):\s*(\d+)% used\s*\S\s*resets (.+)", text)
    if not session_match or not week_match:
        return None

    return {
        "session_used_pct": int(session_match.group(1)),
        "session_resets_at": session_match.group(2).strip(),
        "week_used_pct": int(week_match.group(1)),
        "week_resets_at": week_match.group(2).strip(),
    }


def get_model_usage_breakdown(days: int = 7) -> dict:
    """Best-effort: aggregate per-model input/output token usage from local
    Claude Code session transcripts (~/.claude/projects/**/*.jsonl) over the
    last `days`. Local-machine only, same caveat as get_session_usage() -
    only reflects Claude Code sessions run on this machine, not claude.ai or
    other devices. Returns {} if the transcripts directory doesn't exist or
    nothing matches, so the caller can leave a previous value untouched.
    """
    projects_dir = os.path.expanduser("~/.claude/projects")
    if not os.path.isdir(projects_dir):
        return {}

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    per_model = {}

    for root, _dirs, files in os.walk(projects_dir):
        for name in files:
            if not name.endswith(".jsonl"):
                continue
            path = os.path.join(root, name)
            try:
                with open(path, "r", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        msg = entry.get("message") or {}
                        usage = msg.get("usage")
                        model = msg.get("model")
                        ts = entry.get("timestamp")
                        if not (usage and model and ts):
                            continue
                        if model == "<synthetic>":
                            continue
                        try:
                            ts_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        except ValueError:
                            continue
                        if ts_dt < cutoff:
                            continue
                        bucket = per_model.setdefault(
                            model, {"input_tokens": 0, "output_tokens": 0}
                        )
                        bucket["input_tokens"] += (
                            (usage.get("input_tokens") or 0)
                            + (usage.get("cache_creation_input_tokens") or 0)
                            + (usage.get("cache_read_input_tokens") or 0)
                        )
                        bucket["output_tokens"] += usage.get("output_tokens") or 0
            except OSError:
                continue

    total_output = sum(m["output_tokens"] for m in per_model.values())
    result = {}
    for model, tok in sorted(
        per_model.items(), key=lambda kv: kv[1]["output_tokens"], reverse=True
    ):
        pct = round(tok["output_tokens"] / total_output * 100, 1) if total_output else 0.0
        result[model] = {
            "display_name": _display_name(model),
            "input_tokens": tok["input_tokens"],
            "output_tokens": tok["output_tokens"],
            "pct_of_output": pct,
        }
    return result


def main():
    parser = argparse.ArgumentParser(description="Fetch weekly Claude API usage/cost.")
    parser.add_argument("--out", default=DEFAULT_OUT, help=f"Output JSON file path (default: {DEFAULT_OUT}).")
    parser.add_argument("--days", type=int, default=7, help="Lookback window in days (default 7).")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_ADMIN_API_KEY")
    if not api_key:
        sys.exit("Set ANTHROPIC_ADMIN_API_KEY in your environment first (do not hardcode it).")

    now = datetime.now(timezone.utc)
    ending_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    starting_at = (now - timedelta(days=args.days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    usage_buckets = fetch_report("usage_report/messages", api_key, starting_at, ending_at)
    cost_buckets = fetch_report("cost_report", api_key, starting_at, ending_at)

    total_input_tokens = 0
    total_output_tokens = 0
    for bucket in usage_buckets:
        for row in bucket.get("results", []):
            total_input_tokens += row.get("uncached_input_tokens", 0) or 0
            total_output_tokens += row.get("output_tokens", 0) or 0

    total_cost_usd = 0.0
    for bucket in cost_buckets:
        for row in bucket.get("results", []):
            amt = row.get("amount", {})
            total_cost_usd += float(amt.get("value", 0) or 0)

    # Start from whatever is already on disk so a cloud run (no local `claude`
    # CLI) doesn't wipe out session_usage written by the last local run.
    summary = {}
    if os.path.exists(args.out):
        try:
            with open(args.out) as f:
                summary = json.load(f)
        except (json.JSONDecodeError, OSError):
            summary = {}

    summary.update({
        "generated_at": now.isoformat(),
        "window_start": starting_at,
        "window_end": ending_at,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "total_tokens": total_input_tokens + total_output_tokens,
        "total_cost_usd": round(total_cost_usd, 2),
    })

    session_usage = get_session_usage()
    if session_usage:
        summary["session_usage"] = {**session_usage, "captured_at": now.isoformat()}

    model_usage = get_model_usage_breakdown(days=args.days)
    if model_usage:
        summary["model_usage_7d"] = model_usage

    with open(args.out, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"Wrote usage summary to {args.out}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
