# Claude Usage Collector — deployment

Reads each user's Claude Desktop subscription usage (5h + 7d %) headlessly and
pushes it to Supabase once a day. Works while Claude Desktop stays open (uses a
Volume Shadow Copy to read the locked cookie DB), so it needs to run elevated.

## Components
- `desktop_usage.py` — the collector (source).
- `ClaudeUsage.exe` — packaged build (from `build.ps1`), for machines without Python.
- `.env` — Supabase URL/key, sits next to the exe.
- `schema.sql` — one-time Supabase table setup.

---

## 1. One-time: create the Supabase table
Supabase dashboard → SQL editor → paste `schema.sql` → Run.

## 2. One-time: build the exe (on a dev machine with Python)
```powershell
cd C:\Workspace\Claude-Usage-Analyzer
.\build.ps1
```
Output: `dist\ClaudeUsage.exe`.

## 3. Per user machine
Copy **two files** into a folder, e.g. `C:\ProgramData\ClaudeUsage\`:
- `ClaudeUsage.exe`
- `.env`

Then, from an **elevated** PowerShell (Run as administrator):
```powershell
cd C:\ProgramData\ClaudeUsage
.\ClaudeUsage.exe                       # test: prints usage + "supabase: pushed"
.\ClaudeUsage.exe --install-task 18:00  # daily run at 6 PM, elevated, hidden
```
Done. Every day at 18:00 it reads usage (Claude can stay open), appends
`usage.csv` locally, and inserts a row into Supabase.

Remove later with: `.\ClaudeUsage.exe --uninstall-task`

---

## Flags
| Flag | Effect |
|------|--------|
| *(none)* | read usage, push to Supabase, print |
| `--log` | also append a row to `usage.csv` |
| `--no-push` | skip Supabase (local only) |
| `--install-task HH:MM` | create the daily elevated scheduled task |
| `--uninstall-task` | remove it |

## Notes / caveats
- **Elevation is required** while Claude Desktop is open (VSS needs admin). The
  scheduled task runs with highest privileges, so no daily UAC prompt.
- The `.env` key is the **publishable/anon** key — safe to distribute. RLS lets
  it INSERT only; it cannot read others' rows.
- Undocumented `/usage` endpoint; if Anthropic changes fields the script prints
  an error and pushes nulls — check `five_hour.utilization` mapping if so.
- If the machine is asleep at the scheduled time the run is missed; add
  `/RU` catch-up handling if you need guaranteed capture.
