"""
costs.py — API cost tracking and monthly spend report

Reads from /logs/api-costs.jsonl (written by run.py after each pipeline run).

Usage:
    python analyzer/costs.py --month 2026-04
    python analyzer/costs.py --all
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict

ROOT = Path(__file__).parent.parent
COST_LOG = ROOT / "logs" / "api-costs.jsonl"


def load_entries(month_filter: str | None = None) -> list[dict]:
    if not COST_LOG.exists():
        return []

    entries = []
    with open(COST_LOG, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if month_filter:
                    ts = entry.get("timestamp", "")
                    if not ts.startswith(month_filter):
                        continue
                entries.append(entry)
            except json.JSONDecodeError:
                continue
    return entries


def print_report(entries: list[dict], label: str) -> None:
    if not entries:
        print(f"\nNo cost data found for: {label}")
        return

    total_whisper = 0.0
    total_analyze = 0.0
    total_generate = 0.0
    total_all = 0.0

    brand_totals = defaultdict(float)
    run_rows = []

    for e in entries:
        costs = e.get("costs", {})
        w = costs.get("whisper_usd", 0)
        a = costs.get("claude_analyze_usd", 0)
        g = costs.get("claude_generate_usd", 0)
        t = costs.get("total_usd", 0)

        total_whisper += w
        total_analyze += a
        total_generate += g
        total_all += t
        brand_totals[e.get("brand", "unknown")] += t

        run_rows.append({
            "date": e.get("timestamp", "")[:10],
            "brand": e.get("brand", "?"),
            "video_id": e.get("video_id", "?")[:30],
            "whisper": w,
            "analyze": a,
            "generate": g,
            "total": t,
        })

    print(f"\n{'='*65}")
    print(f"  ContentEngine Cost Report — {label}")
    print(f"  Runs: {len(entries)}")
    print(f"{'='*65}")
    print(f"  {'Date':<12} {'Brand':<22} {'Whisper':>8} {'Analyze':>8} {'Gen':>8} {'Total':>8}")
    print(f"  {'─'*60}")
    for r in run_rows:
        print(f"  {r['date']:<12} {r['brand']:<22} ${r['whisper']:>6.4f} ${r['analyze']:>6.4f} ${r['generate']:>6.4f} ${r['total']:>6.4f}")

    print(f"  {'─'*60}")
    print(f"  {'TOTALS':<35} ${total_whisper:>6.4f} ${total_analyze:>6.4f} ${total_generate:>6.4f} ${total_all:>6.4f}")

    print(f"\n  API Breakdown:")
    print(f"    OpenAI Whisper:  ${total_whisper:.4f}")
    print(f"    Claude (analyze+generate): ${total_analyze + total_generate:.4f}")
    print(f"    TOTAL:           ${total_all:.4f}")

    print(f"\n  By Brand:")
    for brand, amt in sorted(brand_totals.items()):
        print(f"    {brand:<30} ${amt:.4f}")

    print(f"{'='*65}\n")


def main():
    parser = argparse.ArgumentParser(description="ContentEngine API cost report")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--month", help="Month to report on, format YYYY-MM (e.g. 2026-04)")
    group.add_argument("--all", action="store_true", help="Show all-time cost report")

    args = parser.parse_args()

    if args.all:
        entries = load_entries()
        print_report(entries, "All Time")
    else:
        # Validate month format
        try:
            datetime.strptime(args.month, "%Y-%m")
        except ValueError:
            print(f"Invalid month format '{args.month}'. Use YYYY-MM, e.g. 2026-04")
            sys.exit(1)
        entries = load_entries(month_filter=args.month)
        print_report(entries, args.month)


if __name__ == "__main__":
    main()
