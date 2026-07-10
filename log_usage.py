"""
log_usage.py — record and review your Claude subscription usage %.

Since Anthropic exposes no API for the subscription limit, you read the
number off the app (Claude Desktop usage indicator, or `/usage` in Claude
Code) and log it here. Takes 5 seconds at end of day.

Usage:
    python log_usage.py 73              # log 73% for today (5h/session bucket)
    python log_usage.py 73 --weekly 40 # also log the weekly bucket
    python log_usage.py --show         # print history + simple trend
"""
import csv
import datetime
import os
import sys

CSV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "usage.csv")
FIELDS = ["date", "time", "session_pct", "weekly_pct", "note"]


def _read():
    if not os.path.exists(CSV_FILE):
        return []
    with open(CSV_FILE, newline="") as fh:
        return list(csv.DictReader(fh))


def _write_row(row):
    new = not os.path.exists(CSV_FILE)
    with open(CSV_FILE, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def _num(s, name):
    try:
        v = float(s)
    except (TypeError, ValueError):
        raise SystemExit(f"'{s}' is not a valid {name} percentage (0-100).")
    if not 0 <= v <= 100:
        raise SystemExit(f"{name} must be between 0 and 100, got {v}.")
    return v


def show():
    rows = _read()
    if not rows:
        print("No data yet. Log one with:  python log_usage.py 73")
        return
    print(f"{'date':<12}{'session%':>10}{'weekly%':>10}   note")
    print("-" * 48)
    for r in rows:
        s = r.get("session_pct") or ""
        w = r.get("weekly_pct") or ""
        print(f"{r['date']:<12}{s:>10}{w:>10}   {r.get('note','')}")
    vals = [float(r["session_pct"]) for r in rows if r.get("session_pct")]
    if vals:
        print("-" * 48)
        print(f"session%  avg {sum(vals)/len(vals):.1f}   "
              f"min {min(vals):.0f}   max {max(vals):.0f}   n={len(vals)}")


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("--show", "-s", "show"):
        show()
        return

    now = datetime.datetime.now()
    row = {f: "" for f in FIELDS}
    row["date"] = now.strftime("%Y-%m-%d")
    row["time"] = now.strftime("%H:%M")
    row["session_pct"] = f"{_num(args[0], 'session'):g}"

    if "--weekly" in args:
        i = args.index("--weekly")
        row["weekly_pct"] = f"{_num(args[i + 1], 'weekly'):g}"
    if "--note" in args:
        i = args.index("--note")
        row["note"] = args[i + 1]

    _write_row(row)
    print(f"logged {row['date']}: session {row['session_pct']}%"
          + (f", weekly {row['weekly_pct']}%" if row["weekly_pct"] else ""))


if __name__ == "__main__":
    main()
