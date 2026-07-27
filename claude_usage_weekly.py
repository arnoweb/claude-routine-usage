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

    summary = {
        "generated_at": now.isoformat(),
        "window_start": starting_at,
        "window_end": ending_at,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "total_tokens": total_input_tokens + total_output_tokens,
        "total_cost_usd": round(total_cost_usd, 2),
    }

    with open(args.out, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"Wrote usage summary to {args.out}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
