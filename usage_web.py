"""
usage_web.py — call the claude.ai internal usage endpoint with YOUR browser
session cookie and dump whatever it returns.

This is the same authenticated request the web/desktop app makes. It is
undocumented and may break or be Cloudflare-blocked. Uses your own session
only. The cookie is read from an env var and never printed.

Setup:
    # get sessionKey from DevTools -> Application -> Cookies -> claude.ai
    $env:CLAUDE_SESSION_KEY = "sk-ant-sid..."
    # optional: override the org id (defaults to the one below)
    $env:CLAUDE_ORG_ID = "f8b62e2b-a052-47e6-8964-ff4841d6795d"

Run:
    python usage_web.py
    python usage_web.py --path /api/bootstrap   # try a different path
"""
import json
import os
import sys
import urllib.request
import urllib.error

DEFAULT_ORG = "f8b62e2b-a052-47e6-8964-ff4841d6795d"


def get(path, cookie):
    url = f"https://claude.ai{path}"
    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            # Look like the browser as much as possible to clear Cloudflare.
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/126.0.0.0 Safari/537.36"),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://claude.ai/",
            "Origin": "https://claude.ai",
            "Cookie": f"sessionKey={cookie}",
        },
    )
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        return resp.status, resp.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
    except urllib.error.URLError as e:
        return None, f"URLError: {e}"


def main():
    cookie = os.environ.get("CLAUDE_SESSION_KEY")
    if not cookie:
        raise SystemExit(
            "Set your session cookie first:\n"
            '  $env:CLAUDE_SESSION_KEY = "sk-ant-sid..."\n'
            "Get it from DevTools -> Application -> Cookies -> claude.ai -> sessionKey"
        )
    org = os.environ.get("CLAUDE_ORG_ID", DEFAULT_ORG)
    print(f"cookie: present (len {len(cookie)}), org: {org}")

    if "--path" in sys.argv:
        paths = [sys.argv[sys.argv.index("--path") + 1]]
    else:
        # A few candidate endpoints; the first that returns usable JSON wins.
        paths = [
            f"/api/organizations/{org}/usage",
            f"/api/organizations/{org}/rate_limit",
            f"/api/organizations/{org}",
            "/api/bootstrap",
        ]

    for path in paths:
        status, body = get(path, cookie)
        print(f"\n===== GET {path} -> {status} =====")
        # Pretty-print JSON if we got it; else show a snippet (Cloudflare HTML etc.)
        try:
            print(json.dumps(json.loads(body), indent=2)[:4000])
        except (ValueError, TypeError):
            print(body[:600])


if __name__ == "__main__":
    main()
