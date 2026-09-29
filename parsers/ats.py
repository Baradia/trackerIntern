"""Parsers for the standard applicant tracking systems.

Every parser returns a list of dicts with this exact shape:

    {"id", "title", "location", "url", "description"}

`description` may be "" if the ATS does not include it in the listing
response; scraper.py will then call the matching *_detail() function only
for jobs that are new and have already survived the title/location filters.
"""

import re
import time
import requests

TIMEOUT = 30
RETRIES = 3


def _retry(fn):
    """Transient timeouts are common on big boards; one blip should not take
    a whole company out for the run."""
    last = None
    for attempt in range(RETRIES):
        try:
            r = fn()
            r.raise_for_status()
            return r.json()
        except requests.exceptions.HTTPError:
            raise
        except Exception as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise last


def _get(url, ua, **kw):
    return _retry(lambda: requests.get(
        url, headers={"User-Agent": ua}, timeout=TIMEOUT, **kw))


def _post(url, ua, payload):
    return _retry(lambda: requests.post(
        url,
        headers={"User-Agent": ua, "Content-Type": "application/json",
                 "Accept": "application/json"},
        json=payload,
        timeout=TIMEOUT,
    ))


# --------------------------------------------------------------------------
# Greenhouse   careers page: job-boards.greenhouse.io/<token>
# --------------------------------------------------------------------------
def greenhouse(cfg, ua):
    url = ("https://boards-api.greenhouse.io/v1/boards/"
           f"{cfg['token']}/jobs?content=true")
    data = _get(url, ua)
    out = []
    for j in data.get("jobs", []):
        out.append({
            "id": str(j.get("id", "")),
            "title": j.get("title", ""),
            "location": (j.get("location") or {}).get("name", ""),
            "url": j.get("absolute_url", ""),
            "description": j.get("content", "") or "",
        })
    return out


# --------------------------------------------------------------------------
# Lever   careers page: jobs.lever.co/<token>
# --------------------------------------------------------------------------
def lever(cfg, ua):
    url = f"https://api.lever.co/v0/postings/{cfg['token']}?mode=json"
    data = _get(url, ua)
    out = []
    for j in data:
        cats = j.get("categories") or {}
        out.append({
            "id": str(j.get("id", "")),
            "title": j.get("text", ""),
            "location": cats.get("location", "") or "",
            "url": j.get("hostedUrl", ""),
            "description": j.get("descriptionPlain", "") or "",
        })
    return out


# --------------------------------------------------------------------------
# SmartRecruiters   careers page: careers.smartrecruiters.com/<token>
# --------------------------------------------------------------------------
def smartrecruiters(cfg, ua):
    token = cfg["token"]
    out, offset = [], 0
    while True:
        url = (f"https://api.smartrecruiters.com/v1/companies/{token}"
               f"/postings?limit=100&offset={offset}")
        data = _get(url, ua)
        items = data.get("content", [])
        for j in items:
            loc = j.get("location") or {}
            city = loc.get("city", "")
            region = loc.get("region", "")
            out.append({
                "id": str(j.get("id", "")),
                "title": j.get("name", ""),
                "location": ", ".join(x for x in (city, region) if x),
                "url": (f"https://careers.smartrecruiters.com/{token}/"
                        f"{j.get('id','')}"),
                "description": "",
            })
        offset += len(items)
        if not items or offset >= data.get("totalFound", 0) or offset > 1000:
            break
        time.sleep(0.4)
    return out


def smartrecruiters_detail(cfg, job, ua):
    url = (f"https://api.smartrecruiters.com/v1/companies/{cfg['token']}"
           f"/postings/{job['id']}")
    try:
        data = _get(url, ua)
    except Exception:
        return ""
    parts = []
    sections = ((data.get("jobAd") or {}).get("sections") or {})
    for sec in sections.values():
        if isinstance(sec, dict):
            parts.append(str(sec.get("text", "")))
    return " ".join(parts)


# --------------------------------------------------------------------------
# Workday   careers page: <tenant>.<wd>.myworkdayjobs.com/<site>
# --------------------------------------------------------------------------
def _wd_base(cfg):
    """Two Workday host patterns exist:
       classic:  <tenant>.<wd>.myworkdayjobs.com/<site>
       shared:   wd<N>.myworkdaysite.com/en-US/recruiting/<tenant>/<site>
    Set `host:` in the config for the shared pattern."""
    if cfg.get("host"):
        h = cfg["host"].replace("https://", "").rstrip("/")
        return f"https://{h}/wday/cxs/{cfg['tenant']}/{cfg['site']}"
    return (f"https://{cfg['tenant']}.{cfg['wd']}.myworkdayjobs.com"
            f"/wday/cxs/{cfg['tenant']}/{cfg['site']}")


def _wd_host(cfg):
    if cfg.get("host"):
        h = cfg["host"].replace("https://", "").rstrip("/")
        return f"https://{h}/en-US/recruiting/{cfg['tenant']}/{cfg['site']}"
    return (f"https://{cfg['tenant']}.{cfg['wd']}.myworkdayjobs.com"
            f"/en-US/{cfg['site']}")


def workday(cfg, ua):
    """If `search_terms` is set, run one small query per term instead of
    downloading the whole board. Far faster for large employers, at the cost
    of missing postings whose text contains none of the terms."""
    base, host = _wd_base(cfg), _wd_host(cfg)
    terms = cfg.get("search_terms") or [cfg.get("search", "")]
    # Some tenants use searchText only for relevance ordering, not filtering.
    # max_pages_per_term caps how deep to go; matches rank first, so the top
    # few pages hold what you want. Leave unset to page the whole board.
    max_pages = cfg.get("max_pages_per_term")
    seen, out = set(), []
    limit = 20

    for term in terms:
        offset, reported, page = 0, None, 0
        while True:
            page += 1
            payload = {"appliedFacets": {}, "limit": limit,
                       "offset": offset, "searchText": term}
            data = _post(f"{base}/jobs", ua, payload)
            if reported is None:
                reported = data.get("total") or 0
            items = data.get("jobPostings", [])
            for j in items:
                path = j.get("externalPath", "")
                jid = str((j.get("bulletFields") or [path])[0] or path)
                if jid in seen:
                    continue
                seen.add(jid)
                out.append({
                    "id": jid,
                    "title": j.get("title", ""),
                    "location": j.get("locationsText", "") or "",
                    "url": host + path,
                    "description": "",
                    "_path": path,
                })
            offset += len(items)
            if (len(items) < limit or (reported and offset >= reported)
                    or offset >= 2500 or (max_pages and page >= max_pages)):
                break
            time.sleep(0.3)

    if out:
        out[0]["_reported_total"] = None if len(terms) > 1 else reported
    return out


def workday_detail(cfg, job, ua):
    path = job.get("_path")
    if not path:
        return ""
    try:
        data = _get(_wd_base(cfg) + path, ua)
    except Exception:
        return ""
    info = data.get("jobPostingInfo") or {}
    return str(info.get("jobDescription", ""))


# --------------------------------------------------------------------------
# Oracle Recruiting Cloud
# careers page: <host>/hcmUI/CandidateExperience/en/sites/<site>
# e.g. host = fa-epmd-saasfaprod1.fa.ocs.oraclecloud.com, site = CX_3001
# --------------------------------------------------------------------------
def oracle(cfg, ua):
    host = cfg["host"].replace("https://", "").rstrip("/")
    site = cfg["site"]
    out, offset = [], 0
    while True:
        finder = (f"findReqs;siteNumber={site},limit=200,"
                  f"offset={offset},sortBy=POSTING_DATES_DESC")
        url = (f"https://{host}/hcmRestApi/resources/latest/"
               f"recruitingCEJobRequisitions?onlyData=true"
               f"&expand=requisitionList.secondaryLocations"
               f"&finder={finder}")
        data = _get(url, ua)
        items = (data.get("items") or [{}])[0].get("requisitionList", [])
        for j in items:
            jid = str(j.get("Id", ""))
            out.append({
                "id": jid,
                "title": j.get("Title", ""),
                "location": (j.get("PrimaryLocation")
                             or j.get("Location") or ""),
                "url": (f"https://{host}/hcmUI/CandidateExperience/en/"
                        f"sites/{site}/job/{jid}"),
                "description": j.get("ShortDescriptionStr", "") or "",
            })
        offset += len(items)
        if not items or offset > 1000:
            break
        time.sleep(0.4)
    return out


# --------------------------------------------------------------------------
# Ashby   careers page: jobs.ashbyhq.com/<token>
# --------------------------------------------------------------------------
def ashby(cfg, ua):
    url = ("https://api.ashbyhq.com/posting-api/job-board/"
           f"{cfg['token']}?includeCompensation=false")
    data = _get(url, ua)
    out = []
    for j in data.get("jobs", []):
        out.append({
            "id": str(j.get("id", "")),
            "title": j.get("title", ""),
            "location": j.get("location", "") or "",
            "url": j.get("jobUrl", ""),
            "description": j.get("descriptionPlain",
                                 j.get("descriptionHtml", "")) or "",
        })
    return out


# --------------------------------------------------------------------------
# BambooHR   careers page: <token>.bamboohr.com/careers
# --------------------------------------------------------------------------
def bamboohr(cfg, ua):
    token = cfg["token"]
    data = _get(f"https://{token}.bamboohr.com/careers/list", ua)
    out = []
    for j in data.get("result", []):
        loc = j.get("location") or {}
        city = loc.get("city", "") or ""
        state = loc.get("state", "") or ""
        jid = str(j.get("id", ""))
        out.append({
            "id": jid,
            "title": j.get("jobOpeningName", ""),
            "location": ", ".join(x for x in (city, state) if x),
            "url": f"https://{token}.bamboohr.com/careers/{jid}",
            "description": "",
        })
    return out



# --------------------------------------------------------------------------
# SAP SuccessFactors career sites (server-rendered HTML, no JSON API)
#   base:   https://jobs.dana.com
#   prefix: optional sub-path, e.g. /dofasco for ArcelorMittal
# --------------------------------------------------------------------------
def _sf_locales(html, cfg):
    """Candidate locales: config override, anything the page advertises,
    then common defaults."""
    cands = [cfg.get("locale")] if cfg.get("locale") else []
    cands += re.findall(r"locale['\"]?\s*[:=]\s*['\"]([a-z]{2}_[A-Z]{2})", html)
    m = re.search(r'<html[^>]*lang="([a-z]{2})-([A-Za-z]{2})"', html)
    if m:
        cands.append(f"{m.group(1)}_{m.group(2).upper()}")
    cands += ["en_CA", "en_US", "en_GB"]
    seen, out = set(), []
    for c in cands:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _sf_unify(cfg, ua):
    """Newer SuccessFactors 'Unify' career sites render the job list with
    JavaScript from a JSON endpoint instead of serving HTML rows."""
    base = cfg["base"].rstrip("/")
    browser = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
    sess = requests.Session()
    sess.headers.update({"User-Agent": browser})

    page = sess.get(f"{base}/search/?q=&startrow=0", timeout=TIMEOUT)
    m = re.search(r"CSRFToken\s*[=:]\s*['\"]([^'\"]+)['\"]", page.text)
    headers = {"Content-Type": "application/json",
               "Accept": "application/json",
               "Referer": f"{base}/search/"}
    if m:
        headers["X-CSRF-Token"] = m.group(1)

    def fetch(locale, pnum):
        body = {"locale": locale, "pageNumber": pnum, "sortBy": "",
                "keywords": "", "location": "", "facetFilters": {},
                "brand": "", "skills": [], "categoryId": 0,
                "alertId": "", "rcmCandidateId": ""}
        r = sess.post(f"{base}/services/recruiting/v1/jobs",
                      json=body, headers=headers, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()

    # find the locale the site actually answers to
    locale, first = None, None
    for cand in _sf_locales(page.text, cfg):
        data = fetch(cand, 0)
        if data.get("totalJobs") or data.get("jobSearchResult"):
            locale, first = cand, data
            break
        time.sleep(0.3)
    if not locale:
        return []

    out, pnum, data = [], 0, first
    while pnum < 60:
        items = data.get("jobSearchResult") or []
        for it in items:
            j = it.get("response", it)
            jid = str(j.get("id", ""))
            title = (j.get("unifiedStandardTitle") or j.get("title")
                     or j.get("jobTitle") or "")
            locs = (j.get("jobLocationShort") or j.get("jobLocation")
                    or j.get("location") or [])
            if isinstance(locs, str):
                locs = [locs]
            slug = j.get("urlTitle") or ""
            url = (f"{base}/job/{slug}/{jid}-{locale}" if slug
                   else f"{base}/job/{jid}")
            out.append({"id": jid, "title": title,
                        "location": "; ".join(str(x) for x in locs),
                        "url": url, "description": ""})
        total = data.get("totalJobs") or 0
        pnum += 1
        if not items or (total and len(out) >= total):
            break
        time.sleep(0.4)
        data = fetch(locale, pnum)
    return out


def successfactors(cfg, ua):
    from bs4 import BeautifulSoup

    base = cfg["base"].rstrip("/")
    prefix = cfg.get("prefix", "").rstrip("/")
    step = int(cfg.get("step", 25))
    out, startrow, pages = [], 0, 0

    while pages < 40:
        url = f"{base}{prefix}/search/?q=&startrow={startrow}"
        r = requests.get(url, headers={"User-Agent": ua}, timeout=TIMEOUT)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        rows = soup.select("tr.data-row") or soup.select("li.job-tile")
        if not rows:
            if startrow == 0:
                # page shell with no rows: the JS-rendered 'Unify' template
                return _sf_unify(cfg, ua)
            break

        for row in rows:
            a = row.select_one("a.jobTitle-link") or row.select_one("a")
            if not a or not a.get("href"):
                continue
            href = a["href"]
            link = href if href.startswith("http") else base + href
            locs = [e.get_text(" ", strip=True)
                    for e in row.select(".jobLocation, .job-location")]
            out.append({
                "id": link.rstrip("/").split("/")[-1] or link,
                "title": a.get_text(" ", strip=True),
                "location": "; ".join(l for l in locs if l),
                "url": link,
                "description": "",
            })

        if len(rows) < step:
            break
        startrow += step
        pages += 1
        time.sleep(0.4)

    return out



# --------------------------------------------------------------------------
# Eightfold AI   careers page: jobs.<company>.com/careers?query=&pid=...
#   host:   jobs.arcadis.com
#   domain: arcadis.com   (the 'domain' query param, usually the corp domain)
# --------------------------------------------------------------------------
def eightfold(cfg, ua):
    host = cfg["host"].replace("https://", "").rstrip("/")
    domain = cfg.get("domain") or host.replace("jobs.", "")
    browser = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
    sess = requests.Session()
    sess.headers.update({"User-Agent": browser,
                         "Accept": "application/json, text/plain, */*",
                         "Accept-Language": "en-CA,en;q=0.9",
                         "Referer": f"https://{host}/careers?domain={domain}"})
    # warm the session: the careers page sets the cookies the API checks
    try:
        sess.get(f"https://{host}/careers?domain={domain}", timeout=TIMEOUT)
    except Exception:
        pass

    def row(j):
        jid = str(j.get("id") or j.get("pid") or "")
        loc = (j.get("location")
               or ", ".join(j.get("locations") or [])
               or ", ".join(j.get("standardizedLocations") or []) or "")
        return {"id": jid,
                "title": j.get("name") or j.get("title", ""),
                "location": loc,
                "url": (j.get("canonicalPositionUrl") or j.get("positionUrl")
                        or f"https://{host}/careers?pid={jid}&domain={domain}"),
                "description": j.get("job_description", "") or ""}

    endpoints = [
        # (url template, list key path, page size)
        (f"https://{host}/api/apply/v2/jobs?domain={domain}"
         "&start={start}&num={num}&query=&sort_by=relevance", ("positions",), 100),
        (f"https://{host}/api/pcsx/search?domain={domain}"
         "&query=&location=&start={start}&sort_by=relevance", ("data", "positions"), 10),
    ]

    last_err = None
    for tmpl, keypath, num in endpoints:
        out, start = [], 0
        try:
            while start < 3000:
                r = sess.get(tmpl.format(start=start, num=num), timeout=TIMEOUT)
                r.raise_for_status()
                data = r.json()
                node = data
                for k in keypath:
                    node = (node or {}).get(k) if isinstance(node, dict) else None
                items = node or data.get("jobs") or []
                out.extend(row(j) for j in items)
                total = (data.get("count") or data.get("total")
                         or (data.get("data") or {}).get("count") or 0)
                start += len(items)
                if not items or (total and start >= total) or len(items) < num:
                    break
                time.sleep(0.4)
            if out:
                return out
        except Exception as e:
            last_err = e
            continue
    if last_err:
        raise last_err
    return []


# --------------------------------------------------------------------------
# iCIMS   careers page: careers-<token>.icims.com/jobs/...
#   host: careers-hexagonpositioning.icims.com
# No public JSON API; the search page renders HTML when in_iframe=1.
# Parsing is deliberately tolerant: any link to /jobs/<id>/ is a posting.
# --------------------------------------------------------------------------
def icims(cfg, ua):
    from bs4 import BeautifulSoup

    host = cfg["host"].replace("https://", "").rstrip("/")
    out, seen = [], set()
    browser = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

    sess = requests.Session()
    sess.headers.update({
        "User-Agent": browser,
        "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                   "image/avif,image/webp,*/*;q=0.8"),
        "Accept-Language": "en-CA,en;q=0.9",
        "Referer": f"https://{host}/jobs/intro",
        "Upgrade-Insecure-Requests": "1",
    })
    # warm the session so any cookies the site sets are sent on the search
    try:
        sess.get(f"https://{host}/jobs/intro?in_iframe=1", timeout=TIMEOUT)
    except Exception:
        pass

    for page in range(40):
        url = f"https://{host}/jobs/search?ss=1&pr={page}&in_iframe=1"
        r = sess.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        new_here = 0
        for a in soup.find_all("a", href=True):
            m = re.search(r"/jobs/(\d+)/", a["href"])
            if not m:
                continue
            jid = m.group(1)
            if jid in seen:
                continue
            title = a.get_text(" ", strip=True)
            h = a.find(["h2", "h3"])
            if h:
                title = h.get_text(" ", strip=True)
            if not title or title.lower() in ("apply", "view", "login"):
                continue
            seen.add(jid)
            new_here += 1

            row = a.find_parent("div", class_=re.compile("row")) or a.parent
            text = row.get_text(" | ", strip=True) if row else ""
            loc = ""
            lm = re.search(r"(?:Job )?Locations?\s*\|?\s*([^|]+)", text, re.I)
            if lm:
                loc = lm.group(1).strip()

            link = a["href"].split("?")[0]
            if not link.startswith("http"):
                link = f"https://{host}{link}"
            out.append({"id": jid, "title": title, "location": loc,
                        "url": link, "description": ""})

        if not new_here:
            break
        time.sleep(0.5)
    return out



# --------------------------------------------------------------------------
# Phenom People   careers page: <host>/<country>/<lang>, e.g.
#   host: www.pgcareers.com   path: global/en
# Jobs come from POST <host>/widgets (ddoKey=refineSearch). If that fails,
# fall back to the phApp.ddo JSON embedded in the search page (page 1 only).
# --------------------------------------------------------------------------
def _phenom_jobs(data):
    for key in ("refineSearch", "eagerLoadRefineSearch"):
        node = data.get(key) if isinstance(data, dict) else None
        if node:
            d = node.get("data") or {}
            return d.get("jobs") or [], node.get("totalHits") or d.get("totalHits") or 0
    return [], 0


def _phenom_row(j, host, path):
    jid = str(j.get("jobId") or j.get("reqId") or j.get("jobSeqNo") or "")
    loc = (j.get("location") or j.get("cityStateCountry")
           or ", ".join(x for x in (j.get("city"), j.get("state"),
                                    j.get("country")) if x) or "")
    return {"id": jid,
            "title": j.get("title", ""),
            "location": loc,
            "url": f"https://{host}/{path}/job/{jid}",
            "description": j.get("descriptionTeaser", "") or ""}


def phenom(cfg, ua):
    import json as _json

    host = cfg["host"].replace("https://", "").rstrip("/")
    path = cfg.get("path", "global/en").strip("/")
    country, lang = (path.split("/") + ["en"])[:2]
    browser = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
    sess = requests.Session()
    sess.headers.update({"User-Agent": browser})
    page = sess.get(f"https://{host}/{path}/search-results", timeout=TIMEOUT)

    out, seen, size, frm = [], set(), 50, 0
    try:
        while frm < 3000:
            body = {"lang": f"{lang}_{country}", "deviceType": "desktop",
                    "country": country, "pageName": "search-results",
                    "ddoKey": "refineSearch", "sortBy": "", "subsearch": "",
                    "from": frm, "jobs": True, "counts": True,
                    "all_fields": [], "size": size, "clearAll": False,
                    "jdsource": "facets", "isSliderEnable": False,
                    "pageId": "page20", "siteType": "external",
                    "keywords": "", "global": True, "selected_fields": {},
                    "locationData": {}}
            r = sess.post(f"https://{host}/widgets", json=body,
                          headers={"Content-Type": "application/json",
                                   "Referer": page.url}, timeout=TIMEOUT)
            r.raise_for_status()
            jobs, total = _phenom_jobs(r.json())
            for j in jobs:
                row = _phenom_row(j, host, path)
                if row["id"] and row["id"] not in seen:
                    seen.add(row["id"])
                    out.append(row)
            frm += len(jobs)
            if not jobs or (total and frm >= total):
                break
            time.sleep(0.4)
    except Exception:
        out = []

    if out:
        return out

    # fallback: first page embedded in the HTML
    m = re.search(r"phApp\.ddo\s*=\s*(\{.*?\});\s*phApp", page.text, re.S)
    if m:
        try:
            jobs, _ = _phenom_jobs(_json.loads(m.group(1)))
            return [_phenom_row(j, host, path) for j in jobs]
        except Exception:
            pass
    return []


LISTERS = {
    "greenhouse": greenhouse,
    "ashby": ashby,
    "bamboohr": bamboohr,
    "successfactors": successfactors,
    "eightfold": eightfold,
    "icims": icims,
    "phenom": phenom,
    "lever": lever,
    "smartrecruiters": smartrecruiters,
    "workday": workday,
    "oracle": oracle,
}

DETAILERS = {
    "smartrecruiters": smartrecruiters_detail,
    "workday": workday_detail,
}
