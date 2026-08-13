"""Parsers for the standard applicant tracking systems.

Every parser returns a list of dicts with this exact shape:

    {"id", "title", "location", "url", "description"}

`description` may be "" if the ATS does not include it in the listing
response; scraper.py will then call the matching *_detail() function only
for jobs that are new and have already survived the title/location filters.
"""

import time
import requests

TIMEOUT = 20


def _get(url, ua, **kw):
    r = requests.get(url, headers={"User-Agent": ua}, timeout=TIMEOUT, **kw)
    r.raise_for_status()
    return r.json()


def _post(url, ua, payload):
    r = requests.post(
        url,
        headers={"User-Agent": ua, "Content-Type": "application/json",
                 "Accept": "application/json"},
        json=payload,
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


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
    return (f"https://{cfg['tenant']}.{cfg['wd']}.myworkdayjobs.com"
            f"/wday/cxs/{cfg['tenant']}/{cfg['site']}")


def workday(cfg, ua):
    base = _wd_base(cfg)
    host = (f"https://{cfg['tenant']}.{cfg['wd']}.myworkdayjobs.com"
            f"/en-US/{cfg['site']}")
    out, offset = [], 0
    while True:
        payload = {"appliedFacets": {}, "limit": 20,
                   "offset": offset, "searchText": cfg.get("search", "")}
        data = _post(f"{base}/jobs", ua, payload)
        items = data.get("jobPostings", [])
        for j in items:
            path = j.get("externalPath", "")
            out.append({
                "id": str(j.get("bulletFields", [path])[0] or path),
                "title": j.get("title", ""),
                "location": j.get("locationsText", "") or "",
                "url": host + path,
                "description": "",
                "_path": path,
            })
        offset += len(items)
        if not items or offset >= data.get("total", 0) or offset > 600:
            break
        time.sleep(0.4)
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


LISTERS = {
    "greenhouse": greenhouse,
    "lever": lever,
    "smartrecruiters": smartrecruiters,
    "workday": workday,
}

DETAILERS = {
    "smartrecruiters": smartrecruiters_detail,
    "workday": workday_detail,
}
