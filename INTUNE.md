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

## 2. Hard requirements ⚠️

| Requirement | Why |
|-------------|-----|
| Windows 10 (1607+) / 11, x64 | ScheduledTasks + VSS |
| **Users are LOCAL ADMINS** | VSS needs elevation; a "Run with highest privileges" task only elevates if the user can. **If your users are standard (non-admin), this method will NOT work** — see §7. |
| Claude **Desktop** installed & user signed in | The cookie source. Not Claude Code / web. |
| Outbound HTTPS to `claude.ai` and `*.supabase.co` | Read usage + push data. |

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

Assign as **Required** to a **device** or **user** group (pilot group first).
Because the task runs as the logged-on user, target users/devices where people
actually sign in interactively.

## 6. Verify on a test device

```powershell
Get-ScheduledTaskInfo -TaskName ClaudeUsageDaily   # NextRunTime set, LastTaskResult 0 after a run
Start-ScheduledTask   -TaskName ClaudeUsageDaily   # force a run; then re-check LastTaskResult (0 = ok)
```
A new row should appear in the Supabase `claude_usage` table.

## 7. If users are NOT local admins

VSS (and therefore this Desktop-cookie method) won't work. Options:
- Deploy the **browser userscript** (`usage_tracker.user.js`) as a managed
  **Edge/Chrome extension** via Intune — only works if staff use **claude.ai in
  the browser**, not the Desktop app.
- Or grant the collector's task a managed admin context another way (out of
  scope here; discuss with IT).

## 8. Notes
- The task fires daily at **18:00** and **at logon**, catches up if the PC was
  off/asleep, and wakes the PC from sleep. Change the time by editing `18:00` in
  `Install.cmd` before packaging.
- Uses an **undocumented** claude.ai endpoint; may break if Anthropic changes it.
- The `.env` in the package contains the Supabase **publishable** (insert-only)
  key — safe to distribute, but it is public in the repo/release.
