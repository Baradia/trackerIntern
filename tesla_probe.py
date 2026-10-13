#!/usr/bin/env python3
"""Check how Tesla's careers data can be reached, and what it looks like.

    python tesla_probe.py

Paste the whole output back.
"""

import json

import requests

API = "https://www.tesla.com/cua-api/apps/careers/state"
PAGE = "https://www.tesla.com/careers/search/?country=CA"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) "
      "Gecko/20100101 Firefox/128.0")


def describe(data):
    if not isinstance(data, dict):
        print("   top level is", type(data).__name__)
        return
    print("   top-level keys:", list(data)[:20])
    for k, v in data.items():
        if isinstance(v, list):
            print(f"   {k}: list[{len(v)}]")
            if v and isinstance(v[0], dict):
                print(f"      first item keys: {list(v[0])[:20]}")
                print(f"      first item: {json.dumps(v[0])[:400]}")
        elif isinstance(v, dict):
            sub = list(v)[:8]
            print(f"   {k}: dict with {len(v)} keys, e.g. {sub}")
            first = next(iter(v.values()), None)
            if first is not None:
                print(f"      e.g. {sub[0]!r}: {json.dumps(first)[:200]}")


print("=== 1. plain request")
try:
    r = requests.get(API, headers={"User-Agent": UA,
                                   "Accept": "application/json"}, timeout=30)
    print("   status", r.status_code, r.headers.get("content-type"))
    if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
        describe(r.json())
except Exception as e:
    print("   failed:", type(e).__name__, e)

print("\n=== 2. from inside Firefox")
try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.firefox.launch(headless=True)
        page = b.new_context(locale="en-CA").new_page()
        resp = page.goto(PAGE, wait_until="domcontentloaded", timeout=60000)
        print("   careers page status", resp.status if resp else "?")
        page.wait_for_timeout(5000)
        res = page.evaluate("""async (u) => {
            const r = await fetch(u, {credentials: 'include',
                                      headers: {'Accept': 'application/json'}});
            return {status: r.status, ctype: r.headers.get('content-type'),
                    body: await r.text()};
        }""", API)
        print("   API status", res["status"], res["ctype"])
        if res["status"] == 200:
            describe(json.loads(res["body"]))
        else:
            print("   body starts:", res["body"][:200])
        b.close()
except Exception as e:
    print("   failed:", type(e).__name__, str(e)[:200])
