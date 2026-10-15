#!/usr/bin/env python3
"""Load a careers page in a real browser and report which requests returned
job data. Replaces doing this by hand in the Network tab.

Setup (once):
    pip install playwright
    python -m playwright install firefox chromium

Usage:
    python capture.py https://jobs.dana.com/
    python capture.py https://stantec.jobs/ --wait 12

For each candidate it prints the method, URL, POST body, and the top-level
shape of the response - enough to write a parser from.
"""

import argparse
import json

from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# a response is interesting if its JSON mentions these
JOB_HINTS = ("jobPostings", "jobs", "postings", "requisition", "openings",
             "results", "hits", "content", "items", "positions")


def shape(obj, depth=0):
    """One-line summary of a JSON structure."""
    pad = "  " * depth
    if isinstance(obj, dict):
        out = []
        for k, v in list(obj.items())[:12]:
            if isinstance(v, list):
                out.append(f"{pad}  {k}: list[{len(v)}]")
                if v and isinstance(v[0], dict):
                    keys = ", ".join(list(v[0].keys())[:10])
                    out.append(f"{pad}    item keys: {keys}")
            elif isinstance(v, dict):
                out.append(f"{pad}  {k}: dict({', '.join(list(v)[:6])})")
            else:
                out.append(f"{pad}  {k}: {type(v).__name__}")
        return "\n".join(out)
    if isinstance(obj, list):
        s = f"{pad}  list[{len(obj)}]"
        if obj and isinstance(obj[0], dict):
            s += f"\n{pad}    item keys: {', '.join(list(obj[0].keys())[:10])}"
        return s
    return f"{pad}  {type(obj).__name__}"


def capture(url, wait_ms, headed, engine="firefox"):
    found = []

    def on_response(resp):
        try:
            ctype = resp.headers.get("content-type", "")
            if "json" not in ctype.lower():
                return
            body = resp.text()
            if len(body) < 400:
                return
            if not any(h in body for h in JOB_HINTS):
                return
            found.append({
                "method": resp.request.method,
                "url": resp.url,
                "post_data": resp.request.post_data,
                "json": json.loads(body),
                "bytes": len(body),
            })
        except Exception:
            pass

    with sync_playwright() as p:
        browser = getattr(p, engine).launch(headless=not headed)
        ctx = (browser.new_context(user_agent=UA) if engine == "chromium"
               else browser.new_context())
        page = ctx.new_page()
        page.on("response", on_response)
        page.goto(url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(wait_ms)
        # nudge lazy-loaded boards into fetching a second page
        try:
            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(3000)
        except Exception:
            pass
        browser.close()

    if not found:
        print("  nothing matched. Try --wait 15, or --headed to watch it, or")
        print("  the board may be server-rendered HTML with no API at all.")
        return

    found.sort(key=lambda f: -f["bytes"])
    for i, f in enumerate(found[:5], 1):
        print(f"\n  [{i}] {f['method']} {f['url']}  ({f['bytes']:,} bytes)")
        if f["post_data"]:
            print(f"      body: {f['post_data'][:300]}")
        print("      response shape:")
        print(shape(f["json"], depth=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="+")
    ap.add_argument("--wait", type=int, default=8,
                    help="seconds to idle after load")
    ap.add_argument("--headed", action="store_true",
                    help="show the browser window")
    ap.add_argument("--chromium", action="store_true",
                    help="use Chromium instead of Firefox")
    a = ap.parse_args()
    for u in a.urls:
        print(f"\n=== {u}")
        capture(u, a.wait * 1000, a.headed,
                "chromium" if a.chromium else "firefox")
