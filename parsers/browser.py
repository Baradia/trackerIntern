"""Real-browser fetching for career sites that block plain HTTP requests.

Uses Playwright's headless Chromium. Only imported when a company in
companies.yaml has `browser: true` (iCIMS, Eightfold) or `ats: browser`,
so the rest of the tracker runs without Playwright installed.

Setup:
    pip install playwright
    python -m playwright install firefox chromium
"""

import json
import os
import re
import time
from contextlib import contextmanager

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
NAV_TIMEOUT = 45_000  # ms


@contextmanager
def open_page(engine="firefox"):
    """engine: 'firefox' (default; gets past iCIMS bot checks that block
    every Chromium mode) or 'chromium'. Set per company with `engine:`."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        ctx_opts = dict(locale="en-CA", timezone_id="America/Toronto",
                        viewport={"width": 1366, "height": 900})
        if engine == "chromium":
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"])
            ctx_opts["user_agent"] = UA
        else:
            browser = p.firefox.launch(headless=True)
        ctx = browser.new_context(**ctx_opts)
        # hide the most common automation giveaway
        ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = ctx.new_page()
        page.set_default_timeout(NAV_TIMEOUT)
        try:
            yield page
        finally:
            browser.close()


_REDIRECT_ERRORS = ("NS_BINDING_ABORTED", "frame was detached",
                    "net::ERR_ABORTED", "Navigation interrupted",
                    "interrupted by another navigation")


def _goto(page, url):
    try:
        resp = page.goto(url, wait_until="domcontentloaded")
    except Exception as e:
        # the page redirected itself mid-load (iCIMS wrapper pages do this);
        # carry on with wherever it ended up
        if not any(k in str(e) for k in _REDIRECT_ERRORS):
            raise
        resp = None
        try:
            page.wait_for_load_state("domcontentloaded", timeout=20_000)
        except Exception:
            pass
    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except Exception:
        pass  # some sites never go idle; what loaded is enough
    page.wait_for_timeout(2500)  # let bot-check interstitials clear
    if resp is not None and resp.status >= 400:
        raise RuntimeError(f"HTTP {resp.status} in browser for {url}")
    return resp


# --------------------------------------------------------------------------
# iCIMS: same search pages as the plain parser, loaded in a real browser
# --------------------------------------------------------------------------
def _icims_html(page):
    """iCIMS sometimes serves an outer wrapper page with the job list inside
    an <iframe name="icims_content_iframe">. Return the frame's HTML when
    it's there, else the page's."""
    fr = page.frame(name="icims_content_iframe")
    if fr is None:
        for f in page.frames:
            if "in_iframe=1" in (f.url or "") and f is not page.main_frame:
                fr = f
                break
    if fr is not None:
        try:
            fr.wait_for_load_state("domcontentloaded", timeout=15_000)
        except Exception:
            pass
        try:
            return fr.content()
        except Exception:
            pass
    return page.content()


def icims_browser(cfg):
    from .ats import _icims_parse

    host = cfg["host"].replace("https://", "").rstrip("/")
    out, seen = [], set()
    with open_page(cfg.get("engine", "firefox")) as page:
        try:
            _goto(page, f"https://{host}/jobs/intro?in_iframe=1")
        except Exception:
            pass
        for n in range(40):
            _goto(page, f"https://{host}/jobs/search?ss=1&pr={n}&in_iframe=1")
            html = _icims_html(page)
            if os.environ.get("BROWSER_DEBUG"):
                fn = f"debug_{host.split('.')[0]}_page{n}.html"
                with open(fn, "w", encoding="utf-8") as f:
                    f.write(html)
                print(f"    [debug] saved {fn} ({len(html):,} bytes)")
            if not _icims_parse(html, host, seen, out):
                break
            time.sleep(1.0)
    return out


# --------------------------------------------------------------------------
# Eightfold: load the careers page so the browser holds the session, then
# call the job API from inside that page, where the cookies are valid.
# --------------------------------------------------------------------------
_EF_FETCH = """
async ({url}) => {
  const r = await fetch(url, {credentials: 'include',
                              headers: {'Accept': 'application/json'}});
  return {status: r.status, body: await r.text()};
}
"""


def eightfold_browser(cfg):
    from .ats import _ef_row

    host = cfg["host"].replace("https://", "").rstrip("/")
    domain = cfg.get("domain") or host.replace("jobs.", "")
    endpoints = [
        (f"https://{host}/api/apply/v2/jobs?domain={domain}"
         "&start={start}&num=100&query=&sort_by=relevance", ("positions",), 100),
        (f"https://{host}/api/pcsx/search?domain={domain}"
         "&query=&location=&start={start}&sort_by=relevance",
         ("data", "positions"), 10),
    ]
    with open_page(cfg.get("engine", "firefox")) as page:
        _goto(page, f"https://{host}/careers?domain={domain}")
        last = None
        for tmpl, keys, per_page in endpoints:
            out, start = [], 0
            while start < 3000:
                res = page.evaluate(_EF_FETCH, {"url": tmpl.format(start=start)})
                if res["status"] != 200:
                    last = f"HTTP {res['status']} from Eightfold API in browser"
                    break
                data = json.loads(res["body"])
                node = data
                for k in keys:
                    node = node.get(k) if isinstance(node, dict) else None
                items = node or []
                out.extend(_ef_row(j, host, domain) for j in items)
                start += len(items)
                if len(items) < per_page:
                    break
                time.sleep(0.4)
            if out:
                return out
    if last:
        raise RuntimeError(last)
    return []


# --------------------------------------------------------------------------
# Generic: for sites with no known platform. Load the page, keep every JSON
# response, and pick the one that looks most like a list of jobs. Falls
# back to job-looking links in the rendered page. Best-effort by design.
# --------------------------------------------------------------------------
TITLE_KEYS = ("title", "jobTitle", "job_title", "name", "Title",
              "positionTitle", "requisitionTitle")
ID_KEYS = ("id", "jobId", "job_id", "reqId", "requisitionId", "jobReqId",
           "Id", "ref", "slug")
URL_KEYS = ("url", "jobUrl", "applyUrl", "absolute_url", "link", "href",
            "detailUrl", "canonicalUrl")
LOC_KEYS = ("location", "locations", "city", "jobLocation", "locationName",
            "primaryLocation", "Location")


def _first(d, keys):
    for k in keys:
        v = d.get(k)
        if v:
            if isinstance(v, list):
                v = ", ".join(x if isinstance(x, str) else
                              str(x.get("name") or x.get("city") or "")
                              for x in v[:3])
            elif isinstance(v, dict):
                v = v.get("name") or v.get("city") or v.get("text") or ""
            return str(v)
    return ""


def _job_lists(obj, depth=0):
    """Yield every list of dicts that looks like job postings."""
    if depth > 6:
        return
    if isinstance(obj, list):
        dicts = [x for x in obj if isinstance(x, dict)]
        if dicts and sum(1 for d in dicts[:10]
                         if any(k in d for k in TITLE_KEYS)) >= min(3, len(dicts)):
            yield dicts
        for x in obj[:50]:
            yield from _job_lists(x, depth + 1)
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _job_lists(v, depth + 1)


def generic_browser(cfg):
    from urllib.parse import urljoin

    url = cfg["url"]
    link_rx = re.compile(cfg.get("link_pattern",
                                 r"/(job|jobs|careers?/job|position)s?/"), re.I)
    captured = []

    def on_response(resp):
        try:
            if "json" in resp.headers.get("content-type", "").lower():
                captured.append(resp.json())
        except Exception:
            pass

    with open_page(cfg.get("engine", "firefox")) as page:
        page.on("response", on_response)
        _goto(page, url)
        # nudge lazy loaders and "load more" buttons
        for _ in range(int(cfg.get("load_more_clicks", 8))):
            page.mouse.wheel(0, 6000)
            page.wait_for_timeout(1200)
            btn = page.locator(
                "button:has-text('Load more'), button:has-text('Show more'), "
                "a:has-text('Load more'), a:has-text('Show more')")
            try:
                if btn.count() and btn.first.is_visible():
                    btn.first.click()
                    page.wait_for_timeout(2000)
                else:
                    break
            except Exception:
                break
        html = page.content()
        base = page.url

    # 1. JSON responses: take the biggest job-like list across all of them
    best = []
    for blob in captured:
        for lst in _job_lists(blob):
            if len(lst) > len(best):
                best = lst
    out, seen = [], set()
    for j in best:
        title = _first(j, TITLE_KEYS)
        if not title:
            continue
        link = _first(j, URL_KEYS)
        jid = _first(j, ID_KEYS) or link or title
        if jid in seen:
            continue
        seen.add(jid)
        out.append({"id": jid, "title": title,
                    "location": _first(j, LOC_KEYS),
                    "url": urljoin(base, link) if link else base,
                    "description": ""})
    if out:
        return out

    # 2. fallback: job-looking links in the rendered page
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not link_rx.search(href):
            continue
        title = a.get_text(" ", strip=True)
        if not title or len(title) < 4 or title.lower() in (
                "apply", "apply now", "view", "view job", "learn more"):
            continue
        link = urljoin(base, href.split("#")[0])
        if link in seen:
            continue
        seen.add(link)
        out.append({"id": link, "title": title, "location": "",
                    "url": link, "description": ""})
    return out


# --------------------------------------------------------------------------
# iCIMS Jibe: call the JSON API from inside the page; if that fails, read
# the rendered job cards page by page.
# --------------------------------------------------------------------------
_FETCH_JSON = """
async ({url}) => {
  const r = await fetch(url, {credentials: 'include',
                              headers: {'Accept': 'application/json'}});
  return {status: r.status, body: await r.text()};
}
"""


def jibe_browser(cfg):
    from .ats import _jibe_collect, _jibe_parse_html

    host = cfg["host"].replace("https://", "").rstrip("/")
    path = cfg.get("path", "careers-home").strip("/")
    with open_page(cfg.get("engine", "firefox")) as page:
        _goto(page, f"https://{host}/{path}/jobs")

        def fetch_json(url):
            res = page.evaluate(_FETCH_JSON, {"url": url})
            if res["status"] != 200:
                raise RuntimeError(f"HTTP {res['status']} from Jibe API in browser")
            return json.loads(res["body"])

        try:
            out = _jibe_collect(fetch_json, host, path)
            if out:
                return out
        except Exception as e:
            print(f"    [jibe] API unavailable ({e}); reading job cards instead")

        out, seen = [], set()
        for n in range(1, int(cfg.get("max_pages", 100)) + 1):
            if n > 1:
                _goto(page, f"https://{host}/{path}/jobs?page={n}")
            if not _jibe_parse_html(page.content(), host, seen, out):
                break
            time.sleep(0.5)
        return out
