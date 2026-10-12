#!/usr/bin/env python3
"""Try each browser setup against a URL and report which ones get through.

    python browser_probe.py "https://us-careers-rivian.icims.com/jobs/search?ss=1&pr=0&in_iframe=1"
Needs: python -m playwright install chromium firefox
"""

import sys
from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

SETUPS = [
    ("chromium, default headless", "chromium", dict(headless=True)),
    ("chromium, new headless",     "chromium", dict(headless=True, channel="chromium")),
    ("firefox, headless",          "firefox",  dict(headless=True)),
    ("chromium, visible window",   "chromium", dict(headless=False)),
    ("firefox, visible window",    "firefox",  dict(headless=False)),
]

url = sys.argv[1]
with sync_playwright() as p:
    for label, engine, opts in SETUPS:
        try:
            if engine == "chromium":
                opts = {**opts, "args": ["--disable-blink-features=AutomationControlled"]}
            browser = getattr(p, engine).launch(**opts)
            ctx_opts = dict(locale="en-CA", timezone_id="America/Toronto")
            if engine == "chromium":
                ctx_opts["user_agent"] = UA
            ctx = browser.new_context(**ctx_opts)
            ctx.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            page = ctx.new_page()
            resp = page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(3000)
            jobs = page.locator("a[href*='/jobs/']").count()
            status = resp.status if resp else "?"
            verdict = "OK" if status == 200 and jobs else "BLOCKED"
            print(f"  {verdict:<8} {label:<30} status {status}, {jobs} job links")
            browser.close()
        except Exception as e:
            print(f"  ERROR    {label:<30} {type(e).__name__}: {str(e).splitlines()[0][:80]}")
