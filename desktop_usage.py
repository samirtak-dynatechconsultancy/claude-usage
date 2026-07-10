"""
desktop_usage.py — read Claude subscription usage % headlessly, using the
session cookie that Claude Desktop already stores on THIS machine.

No browser tab needed. Runs as you, on your machine, on your own account.

What it does:
  1. locate Claude Desktop's Chromium cookie store + Local State
  2. decrypt the `sessionKey` cookie (DPAPI-wrapped AES-256-GCM, Chromium 'v10')
  3. call the claude.ai usage endpoint and report 5h / 7d utilization

Requirements (run once):
    pip install pycryptodome pywin32

Usage:
    python desktop_usage.py            # print current usage
    python desktop_usage.py --log      # also append a row to usage.csv

Caveats: undocumented endpoint; cookie may rotate (re-run picks up the new
one automatically since it re-reads the store each time); app-bound 'v20'
encryption is not supported (script tells you if it hits that).
"""
import base64
import csv
import ctypes
import datetime
import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
import tempfile
import urllib.request
import urllib.error


def app_dir():
    """Folder to read .env / write usage.csv from — next to the exe when
    frozen by PyInstaller, else next to this script."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


APPDATA = os.environ.get("APPDATA", "")
# Common Electron cookie-store locations for the Claude desktop app.
COOKIE_CANDIDATES = [
    os.path.join(APPDATA, "Claude", "Network", "Cookies"),
    os.path.join(APPDATA, "Claude", "Cookies"),
    os.path.join(APPDATA, "Claude", "Default", "Network", "Cookies"),
    os.path.join(APPDATA, "Claude", "Default", "Cookies"),
]
LOCAL_STATE_CANDIDATES = [
    os.path.join(APPDATA, "Claude", "Local State"),
]
CSV_FILE = os.path.join(app_dir(), "usage.csv")


def load_env():
    """Minimal .env reader (no extra dependency). Real env vars win."""
    env = {}
    path = os.path.join(app_dir(), ".env")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("SUPABASE_URL", "SUPABASE_KEY", "SUPABASE_TABLE"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def push_supabase(row):
    """Insert one usage row into Supabase. Never fatal — warns and returns on
    any problem so the local read/log still succeeds."""
    env = load_env()
    url, key = env.get("SUPABASE_URL"), env.get("SUPABASE_KEY")
    table = env.get("SUPABASE_TABLE", "claude_usage")
    if not url or not key:
        print("supabase: no credentials (.env missing SUPABASE_URL/KEY) - skipped")
        return False
    try:
        from supabase import create_client
    except ImportError:
        print("supabase: package not installed - run `pip install supabase`")
        return False
    try:
        create_client(url, key).table(table).insert(row).execute()
        print(f"supabase: pushed to '{table}'")
        return True
    except Exception as e:
        print(f"supabase: push failed - {e}")
        return False


def _first_existing(paths):
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None


def _aes_key_from_local_state(local_state_path):
    import win32crypt  # from pywin32
    with open(local_state_path, "r", encoding="utf-8") as fh:
        state = json.load(fh)
    enc_key_b64 = state["os_crypt"]["encrypted_key"]
    enc_key = base64.b64decode(enc_key_b64)
    if enc_key[:5] != b"DPAPI":
        raise RuntimeError("unexpected Local State key format (not DPAPI-wrapped)")
    key = win32crypt.CryptUnprotectData(enc_key[5:], None, None, None, 0)[1]
    return key


def _decrypt_cookie(encrypted_value, aes_key):
    from Crypto.Cipher import AES  # pycryptodome
    import win32crypt

    prefix = encrypted_value[:3]
    if prefix in (b"v10", b"v11"):
        nonce = encrypted_value[3:15]
        ciphertext = encrypted_value[15:-16]
        tag = encrypted_value[-16:]
        cipher = AES.new(aes_key, AES.MODE_GCM, nonce=nonce)
        plain = cipher.decrypt_and_verify(ciphertext, tag)
        # Newer Chromium prepends a 32-byte SHA256(host) to the plaintext.
        # Strip it: the real value follows. Detect by the sessionKey signature.
        for candidate in (plain, plain[32:]):
            try:
                s = candidate.decode("utf-8")
            except UnicodeDecodeError:
                continue
            if s.startswith("sk-ant"):
                return s
        return plain[32:].decode("utf-8", errors="replace")
    if prefix == b"v20":
        raise RuntimeError(
            "cookie uses app-bound 'v20' encryption, which DPAPI alone can't "
            "decrypt. Fall back to the Tampermonkey userscript, or copy the "
            "sessionKey manually from DevTools."
        )
    # legacy: whole value is a DPAPI blob
    return win32crypt.CryptUnprotectData(
        encrypted_value, None, None, None, 0)[1].decode("utf-8", errors="replace")


def _read_shared(path):
    """Read a file even while another process holds it open (share read/write/
    delete), which plain copy/open can't do -> avoids WinError 32."""
    import win32file
    handle = win32file.CreateFile(
        path,
        win32file.GENERIC_READ,
        (win32file.FILE_SHARE_READ | win32file.FILE_SHARE_WRITE
         | win32file.FILE_SHARE_DELETE),
        None,
        win32file.OPEN_EXISTING,
        0,
        None,
    )
    try:
        size = win32file.GetFileSize(handle)
        data = b""
        while len(data) < size:
            _, chunk = win32file.ReadFile(handle, min(1 << 20, size - len(data)))
            if not chunk:
                break
            data += chunk
        return data
    finally:
        handle.Close()


def _is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _vss_copy(src, dst):
    """Copy a locked file via a Volume Shadow Copy snapshot (needs admin).
    Uses the built-in esentutl, so no extra dependencies."""
    if os.path.exists(dst):
        try:
            os.remove(dst)
        except OSError:
            pass
    proc = subprocess.run(
        ["esentutl.exe", "/y", "/vss", src, "/d", dst],
        capture_output=True, text=True,
    )
    if proc.returncode != 0 or not os.path.exists(dst):
        raise RuntimeError(
            f"VSS copy failed (esentutl exit {proc.returncode}). "
            "Run elevated (admin).\n" + (proc.stdout or "") + (proc.stderr or "")
        )


def _snapshot_db(src, tmp):
    """Copy the SQLite DB (+ WAL/SHM sidecars). Tries a plain shared read first
    (works when Claude is closed); falls back to VSS when the app holds the
    deny-read lock. Returns the method used ('shared' or 'vss')."""
    sidecars = [ext for ext in ("-wal", "-shm") if os.path.exists(src + ext)]

    # Fast path: app closed / file readable.
    try:
        with open(tmp, "wb") as fh:
            fh.write(_read_shared(src))
        for ext in sidecars:
            try:
                with open(tmp + ext, "wb") as fh:
                    fh.write(_read_shared(src + ext))
            except Exception:
                pass
        return "shared"
    except Exception:
        pass  # locked -> VSS

    # Locked path: Volume Shadow Copy (elevated).
    if not _is_admin():
        raise SystemExit(
            "Claude Desktop has the cookie DB locked, so reading it needs a "
            "Volume Shadow Copy - which requires admin.\n"
            "Run this from an ELEVATED PowerShell (Run as administrator), or "
            "let the scheduled task (created with --install-task) run it "
            "elevated for you."
        )
    _vss_copy(src, tmp)
    for ext in sidecars:
        try:
            _vss_copy(src + ext, tmp + ext)
        except Exception:
            pass  # sidecar optional
    return "vss"


def get_session_key():
    cookie_db = _first_existing(COOKIE_CANDIDATES)
    if not cookie_db:
        raise SystemExit(
            "Could not find Claude Desktop's cookie store. Looked in:\n  "
            + "\n  ".join(COOKIE_CANDIDATES)
            + "\nIs Claude Desktop installed and have you signed in?"
        )
    local_state = _first_existing(LOCAL_STATE_CANDIDATES)
    if not local_state:
        raise SystemExit("Could not find Claude Desktop 'Local State' file.")

    aes_key = _aes_key_from_local_state(local_state)

    # Snapshot the DB (shared read if free, else VSS). Handles its own errors.
    tmp = os.path.join(tempfile.gettempdir(), "claude_cookies_copy.db")
    _snapshot_db(cookie_db, tmp)
    try:
        con = sqlite3.connect(f"file:{tmp}?immutable=1", uri=True)
        rows = con.execute(
            "SELECT host_key, name, encrypted_value FROM cookies "
            "WHERE host_key LIKE '%claude.ai%'"
        ).fetchall()
        con.close()
    finally:
        for p in (tmp, tmp + "-wal", tmp + "-shm"):
            try:
                os.remove(p)
            except OSError:
                pass

    for host, name, enc in rows:
        if name == "sessionKey":
            return _decrypt_cookie(enc, aes_key)
    raise SystemExit(
        "No 'sessionKey' cookie found for claude.ai. Sign in to Claude Desktop "
        "first, then re-run."
    )


# ---------------------------------------------------------------------------
def _get(path, cookie):
    req = urllib.request.Request(
        f"https://claude.ai{path}",
        headers={
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/126.0.0.0 Safari/537.36"),
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://claude.ai/",
            "Cookie": f"sessionKey={cookie}",
        },
    )
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        return resp.status, resp.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _find_email(obj):
    """Recursively find the first email address in a JSON structure,
    preferring explicit email-ish keys."""
    if isinstance(obj, dict):
        for k in ("email", "email_address", "emailAddress"):
            v = obj.get(k)
            if isinstance(v, str):
                m = EMAIL_RE.search(v)
                if m:
                    return m.group(0)
        for v in obj.values():
            r = _find_email(v)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_email(v)
            if r:
                return r
    elif isinstance(obj, str):
        m = EMAIL_RE.search(obj)
        if m:
            return m.group(0)
    return None


def get_email(cookie):
    """Account email for the session. Tries account endpoints, then falls back
    to the personal org's name (which is '<email>'s Organization')."""
    for path in ("/api/bootstrap", "/api/account", "/api/organizations"):
        st, bd = _get(path, cookie)
        if st == 200:
            try:
                em = _find_email(json.loads(bd))
            except Exception:
                em = None
            if em:
                return em
    return None


def _is_uuid(v):
    return isinstance(v, str) and len(v) >= 32 and all(
        c in "0123456789abcdef-" for c in v.lower())


def resolve_and_fetch(cookie):
    status, body = _get("/api/organizations", cookie)
    if status != 200:
        raise SystemExit(
            f"/api/organizations returned {status}. "
            + ("Cloudflare/anti-bot likely blocked the raw request; use the "
               "userscript instead.\n" if status == 403 else "")
            + body[:300]
        )
    orgs = json.loads(body)
    ids = [o.get("uuid") for o in orgs if _is_uuid(o.get("uuid"))]
    if not ids:
        ids = [o.get("id") for o in orgs if _is_uuid(o.get("id"))]

    best = None
    for oid in ids:
        st, bd = _get(f"/api/organizations/{oid}/usage", cookie)
        if st != 200:
            continue
        data = json.loads(bd)
        util = (data.get("five_hour") or {}).get("utilization")
        if isinstance(util, (int, float)):
            return oid, data           # real subscription data
        best = best or (oid, data)
    if best:
        return best
    raise SystemExit("No org returned usage data.")


TASK_NAME = "ClaudeUsageDaily"


def _task_action_parts():
    """(execute, argument) for the scheduled-task action."""
    if getattr(sys, "frozen", False):
        return sys.executable, "--log"
    py = sys.executable
    pyw = os.path.join(os.path.dirname(py), "pythonw.exe")
    exe = pyw if os.path.exists(pyw) else py
    return exe, f'"{os.path.abspath(__file__)}" --log'


def install_task(time_str, all_users=False):
    """Create a daily, elevated scheduled task that logs usage via VSS.

    all_users=False -> task runs as the current user (interactive per-user install).
    all_users=True  -> task runs as whichever member of BUILTIN\\Users is logged
                       on (for Intune/SYSTEM-context deploys), and also fires at
                       logon. Requires that logged-on user to be a local admin,
                       since VSS needs elevation.

    Uses PowerShell's ScheduledTasks module for StartWhenAvailable (catch up a
    missed run after the PC was off) + WakeToRun, which schtasks.exe can't set.
    """
    if not _is_admin():
        raise SystemExit("Run install elevated (admin) or in SYSTEM context.")
    execute, argument = _task_action_parts()

    if all_users:
        principal = ("$p=New-ScheduledTaskPrincipal -GroupId 'BUILTIN\\Users' "
                     "-RunLevel Highest;")
        trigger = (f"$t=@((New-ScheduledTaskTrigger -Daily -At '{time_str}'),"
                   "(New-ScheduledTaskTrigger -AtLogOn));")
    else:
        principal = (
            "$u=[System.Security.Principal.WindowsIdentity]::GetCurrent().Name;"
            "$p=New-ScheduledTaskPrincipal -UserId $u -LogonType Interactive "
            "-RunLevel Highest;")
        trigger = f"$t=New-ScheduledTaskTrigger -Daily -At '{time_str}';"

    ps = (
        "$ErrorActionPreference='Stop';"
        f"$a=New-ScheduledTaskAction -Execute '{execute}' -Argument '{argument}';"
        + trigger +
        "$s=New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun "
        "-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
        "-ExecutionTimeLimit (New-TimeSpan -Hours 1);"
        + principal +
        f"Register-ScheduledTask -TaskName '{TASK_NAME}' -Action $a -Trigger $t "
        "-Settings $s -Principal $p -Force | Out-Null;"
        "Write-Output 'ok'"
    )
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        capture_output=True, text=True,
    )
    if proc.returncode != 0 or "ok" not in (proc.stdout or ""):
        raise SystemExit(
            "task registration failed:\n"
            + (proc.stdout or "") + (proc.stderr or "")
        )
    who = "logged-on user (all-users)" if all_users else "current user"
    print(f"Installed '{TASK_NAME}' -> daily at {time_str}, runs as {who}. "
          f"Catches up at next wake/login if the PC was off. Logs to {CSV_FILE}")


def uninstall_task():
    proc = subprocess.run(
        ["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
        capture_output=True, text=True,
    )
    print(proc.stdout.strip() or proc.stderr.strip())


def main():
    if "--install-task-allusers" in sys.argv:
        i = sys.argv.index("--install-task-allusers")
        time_str = sys.argv[i + 1] if i + 1 < len(sys.argv) else "18:00"
        install_task(time_str, all_users=True)
        return
    if "--install-task" in sys.argv:
        i = sys.argv.index("--install-task")
        time_str = sys.argv[i + 1] if i + 1 < len(sys.argv) else "18:00"
        install_task(time_str)
        return
    if "--uninstall-task" in sys.argv:
        uninstall_task()
        return

    cookie = get_session_key()
    email = get_email(cookie)
    org, data = resolve_and_fetch(cookie)
    five = (data.get("five_hour") or {}).get("utilization")
    seven = (data.get("seven_day") or {}).get("utilization")
    resets = (data.get("five_hour") or {}).get("resets_at")
    now = datetime.datetime.now()
    print(f"[{now:%Y-%m-%d %H:%M}] {email or 'unknown'}  org {org[:8]}..  "
          f"5h: {five}%  7d: {seven}%"
          + (f"  (5h resets {resets})" if resets else ""))

    # Push to Supabase on every execution (unless explicitly disabled).
    if "--no-push" not in sys.argv:
        push_supabase({
            "email": email,
            "org_id": org,
            "session_pct": five,
            "weekly_pct": seven,
            "five_hour_resets_at": resets,
            "seven_day_resets_at": (data.get("seven_day") or {}).get("resets_at"),
            "host": socket.gethostname(),
            "os_user": os.environ.get("USERNAME") or os.environ.get("USER"),
        })

    if "--log" in sys.argv:
        try:
            new = not os.path.exists(CSV_FILE)
            with open(CSV_FILE, "a", newline="") as fh:
                w = csv.writer(fh)
                if new:
                    w.writerow(["date", "time", "email",
                                "session_pct", "weekly_pct"])
                w.writerow([now.strftime("%Y-%m-%d"), now.strftime("%H:%M"),
                            email or "", five, seven])
            print(f"logged -> {CSV_FILE}")
        except OSError as e:
            # Non-fatal: Supabase already has the row; CSV is a local convenience.
            print(f"csv log skipped ({e})")


if __name__ == "__main__":
    main()
