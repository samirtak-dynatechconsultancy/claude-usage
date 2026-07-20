# Build Prompt — Claude Desktop Usage Collector

You are building a small Windows tool that reports a user's **Claude Pro/Max
subscription usage** (the 5‑hour and 7‑day limit percentages) and stores the
history locally and in Supabase. Below is the full functional + technical spec,
including the non‑obvious gotchas already solved. Target: **Windows + Claude
Desktop**, Python 3.13.

---

## 1. Functional goal

- Report the same two numbers the Claude app shows: **5‑hour (session)** and
  **7‑day (weekly)** usage as percentages (0–100), plus their reset times.
- Read them for the **currently signed‑in user, on their own machine, for their
  own account** — no browser tab, no manual copying.
- On each run: print the numbers, append a row to `usage.csv`, and insert a row
  into a shared **Supabase** table.
- Run automatically once a day (end of day, default 18:00), catching up if the
  PC was off/asleep.
- Ship as a single `.exe` plus one‑click install/uninstall, distributed via a
  GitHub Release, and optionally via Intune for a managed fleet.

### Non‑goals / hard boundary
- **Do NOT** build a silent, fleet‑wide SYSTEM service that impersonates other
  users to decrypt their session cookies and centralize them. Session cookies
  are bearer credentials; harvesting them across a fleet without per‑user
  consent is out of scope. For **org‑level** usage visibility, use Anthropic's
  **Team/Enterprise admin usage reporting (Console + Admin API)** instead.
- Windows + Claude **Desktop** only (not Claude Code, not the web app).

---

## 2. How to read the usage number (core technique)

There is **no official public API** for subscription usage. The Claude apps call
an **internal, undocumented** endpoint:

```
GET https://claude.ai/api/organizations/{ORG_UUID}/usage
```

Authenticated by the browser/app **session cookie** (`sessionKey`, value starts
`sk-ant-sid…`). Response (relevant fields):

```json
{
  "five_hour":  { "utilization": 25, "resets_at": "2026-07-10T15:20:00Z" },
  "seven_day":  { "utilization": 6,  "resets_at": "2026-07-17T04:00:00Z" },
  "limits": [ { "kind": "session", "severity": "normal" }, ... ]
}
```

- `five_hour.utilization` → session %; `seven_day.utilization` → weekly %.
- `limits[].severity` ∈ {normal, warning, critical} → status color.

**Dead ends (already proven, don't retry):**
- OAuth token from Claude Code (`sk-ant-oat…`) against `api.anthropic.com` →
  hard `401` (gated to Anthropic's own client).
- Standalone HTTP with the cookie from outside the app → likely Cloudflare 403;
  an **in‑page** `fetch` (userscript) avoids it. A native process using the
  decrypted cookie works because it's a normal HTTPS request with the cookie.

---

## 3. Getting the sessionKey from Claude Desktop (native path)

Claude Desktop is Electron/Chromium. Cookie store + key:

- Cookie DB: `%APPDATA%\Claude\Network\Cookies` (SQLite). Table `cookies`,
  columns `host_key, name, encrypted_value`; filter `host_key LIKE '%claude.ai%'`,
  `name = 'sessionKey'`.
- Key: `%APPDATA%\Claude\Local State` → JSON `os_crypt.encrypted_key`, base64,
  strip the leading `DPAPI` 5 bytes, then **DPAPI `CryptUnprotectData`** (runs in
  the user's context) → 32‑byte AES key.

**Decrypt `encrypted_value`:**
- Prefix `v10`/`v11`: `nonce = bytes[3:15]`, `ciphertext = bytes[15:-16]`,
  `tag = bytes[-16:]`, AES‑256‑**GCM** decrypt+verify.
- **Gotcha:** newer Chromium prepends a **32‑byte `SHA256(host)`** to the
  plaintext. Strip it; the real value follows and starts with `sk-ant`.
- Prefix `v20` (app‑bound): **not supported** — DPAPI alone can't unwrap it;
  detect and fall back with a clear message.

**Gotcha — the cookie DB is locked:** while Claude Desktop runs it holds the
SQLite file with a **deny‑read exclusive lock**. Plain copy and even a
shared‑read `CreateFile` fail (`WinError 32`). Two ways to read it:
1. **App closed** → normal shared read works. (Note: closing the window only
   hides to tray — ~12 `claude.exe` processes remain; must fully quit.)
2. **App open** → copy via **Volume Shadow Copy**: `esentutl.exe /y /vss <src>
   /d <dst>` (built‑in, **needs admin**). Then open the copy with
   `sqlite3 …?immutable=1`. Implement snapshot as: try shared read, on failure
   fall back to VSS (and require admin, else print a clear message).

---

## 4. Organization resolution (multi‑org safe)

`GET /api/organizations` returns the user's orgs. Each object has **both** a
numeric `id` and a **`uuid`**.

- **Gotcha:** the `/usage` endpoint requires the **UUID**; the numeric `id`
  returns `400`. Always use the uuid.
- Multi‑org: prefer the **active** org (its uuid appears in `document.cookie` in
  the browser path), then pick the first org whose `/usage` returns a numeric
  `five_hour.utilization`. An org without a subscription returns `403` or nulls —
  skip it.

**Account email:** try `/api/bootstrap`, then `/api/account`, then fall back to
parsing an email out of the org list (the personal org is named
`"<email>'s Organization"`). Report it with the usage.

---

## 5. Data + Supabase

Insert one row per run (`.env` next to the exe holds credentials):

```
.env:
  SUPABASE_URL=https://<project>.supabase.co
  SUPABASE_KEY=sb_publishable_...        # publishable (anon) key
  SUPABASE_TABLE=claude_usage
```

Table (`schema.sql`):
```sql
create table public.claude_usage (
  id bigint generated always as identity primary key,
  captured_at timestamptz not null default now(),
  email text, org_id text,
  session_pct numeric, weekly_pct numeric,
  five_hour_resets_at timestamptz, seven_day_resets_at timestamptz,
  host text, os_user text
);
alter table public.claude_usage enable row level security;
create policy "anyone can insert usage" on public.claude_usage
  for insert with check (true);          -- NOTE: no `to` clause
grant insert on public.claude_usage to anon, authenticated;
```

- **Gotcha:** with the new `sb_publishable_` keys, a policy `... for insert to
  anon` fails with `42501`. Use a policy with **no `to` clause** (applies to
  `public`) + the grants above. Table must exist first (else `PGRST205`).
- Insert‑only RLS: the client key can write but not read others' rows.
- Supabase push and CSV write must be **non‑fatal** (warn, continue) so a
  network/permission hiccup never fails the scheduled run.

---

## 6. Scheduling (Windows Task Scheduler)

Register via **PowerShell `Register-ScheduledTask`** (schtasks.exe can't set the
catch‑up flags):

- Triggers: daily at `HH:MM` (default 18:00). 
- Settings: `-StartWhenAvailable` (run ASAP if the scheduled time was missed
  while off/hibernated), `-WakeToRun`, `-AllowStartIfOnBatteries`,
  `-DontStopIfGoingOnBatteries`, `ExecutionTimeLimit 1h`.
- Principal (per‑user install): current user, `LogonType Interactive`,
  `RunLevel Highest` (elevated so VSS works; no daily UAC prompt).
- Task name `ClaudeUsageDaily`.

---

## 7. CLI + packaging

Flags:
| Flag | Effect |
|------|--------|
| *(none)* | read usage, push to Supabase, print |
| `--log` | also append to `usage.csv` |
| `--no-push` | skip Supabase (local only) |
| `--install-task HH:MM` | create the daily elevated task (current user) |
| `--uninstall-task` | remove it |

- Package with **PyInstaller** `--onefile` (`ClaudeUsage.exe`). Hidden imports:
  `win32crypt, win32file, win32timezone`; `--collect-all supabase` (+ its stack:
  postgrest, gotrue, realtime, storage3, supafunc, httpx, httpcore).
- Use an `app_dir()` that returns the exe's folder when frozen
  (`sys.frozen`) so `.env`/`usage.csv` sit next to the exe, not in `_MEIPASS`.
- Console output must be **ASCII** (Windows cp1252 consoles turn `— … •` into
  mojibake).

---

## 8. Deliverables (file inventory)

- `desktop_usage.py` — the collector (all of the above).
- `log_usage.py` — manual fallback: `python log_usage.py 73` appends to CSV;
  `--show` prints a trend. (For when you'd rather read the number off the app.)
- `usage_tracker.user.js` — Tampermonkey userscript: in‑page `fetch` of the
  usage endpoint, live badge (5h/7d %), daily‑max log, CSV export, dynamic org
  resolution. No admin, no native code — the browser alternative.
- `schema.sql`, `.env.example`, `build.ps1`.
- `install.bat` / `uninstall.bat` — self‑elevating wrappers around the task.
- `README.md`, `DEPLOY.md` — user + admin docs.
- GitHub Release with `ClaudeUsage.exe` + a zip bundle (exe + .env + bats +
  README + schema).

---

## 9. Tech stack
Python 3.13; `pycryptodome` (AES‑GCM), `pywin32` (DPAPI/file/VSS), `supabase`;
PyInstaller. Windows‑only. Userscript needs Tampermonkey.

## 10. Acceptance
Running `ClaudeUsage.exe` (elevated, Claude Desktop open) prints e.g.
`[2026-07-10 18:00] user@corp.com org f8b62e2b… 5h: 25% 7d: 6%`, appends a CSV
row, and inserts a matching row into `claude_usage`. Missed runs (PC off at
18:00) fire at next wake/login.
