# Deploying Claude Usage Collector via Microsoft Intune

Hand this document (and the `intune/` package folder) to your IT / endpoint team.

---

## 1. What it does (for sign-off)

A small agent that, once a day, reads the signed-in user's **Claude Pro/Max
subscription usage** (two percentages: 5‑hour and 7‑day limits) and:
- writes it to `C:\ProgramData\ClaudeUsage\usage.csv`, and
- inserts a row into a shared **Supabase** table (`email, org_id, session_pct,
  weekly_pct, reset times, host, os_user`).

**How it reads the number:** it decrypts the user's local Claude Desktop session
cookie (on-device, never uploaded) and calls the claude.ai usage endpoint. To
read Claude's locked cookie database while the app is open, it copies it via a
**Volume Shadow Copy** — which requires administrator rights.

**Data leaving the device:** account email + usage percentages + machine/user
name, sent to Supabase over HTTPS. Please confirm this is acceptable under your
data-handling policy before deploying.

---

## 2. Hard requirements

| Requirement | Why |
|-------------|-----|
| Windows 10 (1607+) / 11, x64 | ScheduledTasks + VSS |
| Claude **Desktop** installed & user signed in | The cookie source. Not Claude Code / web. |
| Outbound HTTPS to `claude.ai` and `*.supabase.co` | Read usage + push data. |

**Standard (non-admin) users are supported.** The Intune install registers a
**SYSTEM-context** scheduled task. The SYSTEM task holds the elevation needed for
the Volume Shadow Copy, and it briefly impersonates the logged-on user only to
unwrap that user's DPAPI-protected cookie key. So end users need **no admin
rights**. (One caveat: it reads the **active console session** user — designed
for 1:1 laptops/desktops, not multi-session RDS hosts.)

---

## 3. Package the Win32 app (.intunewin)

Source folder = the `intune/` folder plus the two app files, i.e. these 5 files
together in one folder:

```
ClaudeUsage.exe
.env
Install.cmd
Uninstall.cmd
Detect.ps1
```

Wrap with the [Microsoft Win32 Content Prep Tool](https://github.com/microsoft/Microsoft-Win32-Content-Prep-Tool):

```
IntuneWinAppUtil.exe -c <that folder> -s Install.cmd -o <output folder>
```

Produces `Install.intunewin`.

> A ready-made copy of that 5‑file folder is attached to the GitHub Release as
> **ClaudeUsage-Intune-vX.Y.Z.zip** — just unzip and point IntuneWinAppUtil at it.

---

## 4. Intune app configuration

**Apps → Windows → Add → Windows app (Win32)** → upload the `.intunewin`, then:

| Setting | Value |
|---------|-------|
| Install command | `Install.cmd` |
| Uninstall command | `Uninstall.cmd` |
| Install behavior | **System** |
| Device restart behavior | No specific action |
| Return codes | `0` = Success (default set is fine) |

**Detection rules → Use a custom detection script** → upload `Detect.ps1`
(Run script as 32-bit: **No**; Enforce signature check: **No**).

**Requirements:** OS architecture **x64**, Minimum OS **Windows 10 1607**.

---

## 5. Assignment

Assign as **Required** to a **device** group (pilot group first). The task runs
as SYSTEM but reads whoever is signed in at the console, so target
devices/people who actually sign in interactively.

## 6. Verify on a test device

```powershell
Get-ScheduledTaskInfo -TaskName ClaudeUsageDaily   # NextRunTime set, LastTaskResult 0 after a run
Start-ScheduledTask   -TaskName ClaudeUsageDaily   # force a run; then re-check LastTaskResult (0 = ok)
```
A new row should appear in the Supabase `claude_usage` table.

## 7. How it works for non-admin users (technical)

The scheduled task runs as **NT AUTHORITY\SYSTEM** (`--system-collect`):
1. SYSTEM finds the active console user's token (`WTSQueryUserToken`) and profile.
2. SYSTEM copies that user's locked Claude cookie DB via **Volume Shadow Copy**
   (`esentutl /y /vss`) - the step that needs elevation.
3. SYSTEM **impersonates the user's token** for a single `CryptUnprotectData`
   call to unwrap the DPAPI-protected cookie key, then reverts.
4. Back as SYSTEM: decrypt the cookie, call the usage endpoint, push to Supabase.

No end-user rights are required. If you'd rather not run as SYSTEM at all, the
alternative is deploying the browser userscript (`usage_tracker.user.js`) as a
managed Edge/Chrome extension - but only if staff use claude.ai in the browser.

## 8. Notes
- The task fires daily at **18:00** and **at logon**, catches up if the PC was
  off/asleep, and wakes the PC from sleep. Change the time by editing `18:00` in
  `Install.cmd` before packaging.
- Uses an **undocumented** claude.ai endpoint; may break if Anthropic changes it.
- The `.env` in the package contains the Supabase **publishable** (insert-only)
  key — safe to distribute, but it is public in the repo/release.
