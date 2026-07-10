# Claude Usage Collector

Records your **Claude Pro/Max subscription usage** (the 5‑hour and 7‑day limit
percentages) once a day and stores it — locally as CSV and centrally in Supabase.

It reads the number the Claude app itself shows, straight from Claude Desktop's
own session on your machine. No browser tab, no manual copying.

> **Heads‑up / privacy:** this reads your Claude Desktop session cookie (locally,
> never uploaded) to call claude.ai's usage endpoint, and sends your account
> email + usage percentages to a shared Supabase table. Only run it on accounts
> where that's sanctioned. Uses an undocumented endpoint that could change.

---

## Quick start (download & run)

1. Download `ClaudeUsage-<version>.zip` from the [Releases](../../releases) page.
2. Unzip it anywhere, e.g. `C:\ProgramData\ClaudeUsage\`.
3. Double‑click **`install.bat`** (it asks for admin, runs a test, and schedules
   a daily run at 6 PM).

That's it. To pick a different time: `install.bat 20:30`.
To remove it: **`uninstall.bat`**.

## What it collects

| Field | Example |
|-------|---------|
| email | you@company.com |
| session_pct (5h) | 25 |
| weekly_pct (7d) | 6 |
| reset times | 2026‑07‑10T15:20:00Z |
| host / os_user | DESKTOP‑ABC / you |

Written to `usage.csv` next to the exe and inserted into Supabase on every run.

## Why it needs admin

Claude Desktop keeps its cookie database exclusively locked while running. To
read it *without closing the app*, the tool copies it via a **Volume Shadow
Copy** (`esentutl /y /vss`), which requires elevation. The scheduled task runs
elevated automatically, so there's no daily prompt.

## Command‑line flags

| Flag | Effect |
|------|--------|
| *(none)* | read usage, push to Supabase, print |
| `--log` | also append a row to `usage.csv` |
| `--no-push` | skip Supabase (local only) |
| `--install-task HH:MM` | create the daily elevated scheduled task |
| `--uninstall-task` | remove it |

## Run from source instead of the exe

```powershell
pip install supabase pycryptodome pywin32
copy .env.example .env   # then edit .env with your Supabase details
python desktop_usage.py
```

## Server setup (one time)

Create the table + insert policy in Supabase by running [`schema.sql`](schema.sql)
in the SQL editor.

## How it works

1. Locate Claude Desktop's Chromium cookie store + `Local State`.
2. Decrypt the `sessionKey` cookie (DPAPI‑unwrapped AES‑256‑GCM).
3. Resolve the active organization and call `/api/organizations/{id}/usage`.
4. Print, append CSV, and insert into Supabase.

## Caveats

- Windows + Claude **Desktop** only. Not for Claude Code or the web app.
- App‑bound `v20` cookie encryption is not supported (falls back with a message).
- If the PC is asleep at the scheduled time, that day's run is skipped.
