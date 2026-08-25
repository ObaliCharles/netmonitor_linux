#!/usr/bin/env python3
"""
cli.py — query and manage the network usage stats collected by monitor.py.

Examples:
    python3 cli.py summary                  # today / 7d / 30d / lifetime overview
    python3 cli.py apps --period today       # per-app breakdown for today
    python3 cli.py apps --period 7d          # per-app breakdown for last 7 days
    python3 cli.py apps --period lifetime --sort up
    python3 cli.py export --period 30d --out usage.csv
    python3 cli.py reset                     # wipe stored stats (asks to confirm)
"""

import argparse
import csv
import sys
import time
from datetime import datetime, timedelta

import db

PERIODS = {
    "today": lambda: _start_of_today(),
    "7d": lambda: time.time() - 7 * 86400,
    "30d": lambda: time.time() - 30 * 86400,
    "lifetime": lambda: None,
}


def _start_of_today() -> float:
    now = datetime.now()
    start = datetime(now.year, now.month, now.day)
    return start.timestamp()


def human_bytes(n: int) -> str:
    """Format bytes as a human-readable string, e.g. 3.42 GB."""
    n = float(n)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024:
            return f"{n:.2f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.2f} PB"


def cmd_summary(args):
    with db.connect() as conn:
        print("NETWORK DATA MONITOR")
        print("─" * 38)
        for label, key in [("Today", "today"), ("This 7 days", "7d"), ("This 30 days", "30d"), ("Lifetime", "lifetime")]:
            since = PERIODS[key]()
            t = db.totals_since(conn, since)
            print(f"{label.upper()}")
            print(f"  ↓ {human_bytes(t['down'])}")
            print(f"  ↑ {human_bytes(t['up'])}")


def cmd_apps(args):
    if args.period not in PERIODS:
        sys.exit(f"Unknown period '{args.period}'. Choose from: {', '.join(PERIODS)}")
    since = PERIODS[args.period]()
    with db.connect() as conn:
        rows = db.per_app_since(conn, since, limit=args.limit)

    if not rows:
        print("No data recorded yet for this period.")
        return

    sort_key = {"total": "total", "down": "down", "up": "up"}[args.sort]
    rows.sort(key=lambda r: r[sort_key], reverse=True)

    print(f"APPLICATION USAGE ({args.period})")
    print("─" * 50)
    print(f"{'App':<20} {'Down':>10} {'Up':>10} {'Total':>10}")
    for r in rows:
        print(f"{r['process']:<20} {human_bytes(r['down']):>10} {human_bytes(r['up']):>10} {human_bytes(r['total']):>10}")


def cmd_export(args):
    since = PERIODS.get(args.period, lambda: None)()
    with db.connect() as conn:
        rows = db.all_rows_for_export(conn, since)

    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp_utc", "date", "process", "interface", "down_bytes", "up_bytes"])
        for ts, day, process, interface, down, up in rows:
            w.writerow([ts, day, process, interface or "", down, up])

    print(f"Exported {len(rows)} rows to {args.out}")


def cmd_reset(args):
    if not args.yes:
        confirm = input("This will permanently delete all recorded stats. Type 'yes' to continue: ")
        if confirm.strip().lower() != "yes":
            print("Aborted.")
            return
    with db.connect() as conn:
        db.reset_stats(conn)
    print("Stats reset.")


def main():
    ap = argparse.ArgumentParser(description="View network usage stats collected by monitor.py.")
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("summary", help="Show today / 7d / 30d / lifetime totals.")

    p_apps = sub.add_parser("apps", help="Show per-application breakdown.")
    p_apps.add_argument("--period", default="today", choices=list(PERIODS.keys()))
    p_apps.add_argument("--sort", default="total", choices=["total", "down", "up"])
    p_apps.add_argument("--limit", type=int, default=20)

    p_export = sub.add_parser("export", help="Export raw samples to CSV.")
    p_export.add_argument("--period", default="lifetime", choices=list(PERIODS.keys()))
    p_export.add_argument("--out", default="netmonitor_export.csv")

    p_reset = sub.add_parser("reset", help="Delete all recorded stats.")
    p_reset.add_argument("--yes", action="store_true", help="Skip confirmation prompt.")

    args = ap.parse_args()
    {
        "summary": cmd_summary,
        "apps": cmd_apps,
        "export": cmd_export,
        "reset": cmd_reset,
    }[args.command](args)


if __name__ == "__main__":
    main()
