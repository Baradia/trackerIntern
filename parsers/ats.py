"""Parsers for the standard applicant tracking systems.

Every parser returns a list of dicts with this exact shape:

    {"id", "title", "location", "url", "description"}

`description` may be "" if the ATS does not include it in the listing
response; scraper.py will then call the matching *_detail() function only
for jobs that are new and have already survived the title/location filters.
"""

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


LISTERS = {
    "greenhouse": greenhouse,
    "ashby": ashby,
    "bamboohr": bamboohr,
    "successfactors": successfactors,
    "lever": lever,
    "smartrecruiters": smartrecruiters,
    "workday": workday,
    "oracle": oracle,
}

DETAILERS = {
    "smartrecruiters": smartrecruiters_detail,
    "workday": workday_detail,
}
