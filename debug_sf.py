#!/usr/bin/env python3
"""Diagnose a SuccessFactors career site the parser reads as empty.

    python debug_sf.py https://jobs.opg.com "Winter 2027"

Prints what the raw HTML and the JSON endpoint actually contain, so the
parser can be fixed against the real structure. Paste the whole output.
"""

import json
import re
import sys

import requests

base = sys.argv[1].rstrip("/")
needle = sys.argv[2] if len(sys.argv) > 2 else "Co-Op"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

s = requests.Session()
s.headers.update({"User-Agent": UA})

print("=== 1. HTML search page")
r = s.get(f"{base}/search/?q=&startrow=0", timeout=30)
html = r.text
print(f"status {r.status_code}, {len(html):,} bytes")
hits = [m.start() for m in re.finditer(re.escape(needle), html, re.I)]
print(f"'{needle}' appears {len(hits)} time(s) in the raw HTML")
for pos in hits[:2]:
    print("--- context ---")
    print(html[max(0, pos - 600):pos + 300])
print("job-link hrefs:", sorted(set(re.findall(r'href="(/job/[^"]+)"', html)))[:5])
tok = re.search(r"CSRFToken\s*[=:]\s*['\"]([^'\"]+)['\"]", html)
print("CSRF token found:", bool(tok))

print("\n=== 2. JSON endpoint")
headers = {"Content-Type": "application/json", "Accept": "application/json",
           "Referer": f"{base}/search/"}
if tok:
    headers["X-CSRF-Token"] = tok.group(1)
body = {"locale": "en_US", "pageNumber": 0, "sortBy": "", "keywords": "",
        "location": "", "facetFilters": {}, "brand": "", "skills": [],
        "categoryId": 0, "alertId": "", "rcmCandidateId": ""}
for loc in ["en_CA", "en_US", "en_GB"]:
    body["locale"] = loc
    try:
        t = s.post(f"{base}/services/recruiting/v1/jobs", json=body,
                   headers=headers, timeout=30).json()
        print(f"  locale {loc}: totalJobs={t.get('totalJobs')}, keys={list(t)[:6]}")
    except Exception as e:
        print(f"  locale {loc}: failed {type(e).__name__}")
body["locale"] = "en_CA"
print("locale hints in page:",
      sorted(set(re.findall(r"locale['\"]?\s*[:=]\s*['\"]([a-z]{2}_[A-Z]{2})", html)))[:5],
      re.findall(r'<html[^>]*lang="([^"]+)"', html)[:1])
try:
    j = s.post(f"{base}/services/recruiting/v1/jobs", json=body,
               headers=headers, timeout=30)
    print(f"status {j.status_code}, content-type {j.headers.get('content-type')}")
    try:
        data = j.json()
        print("top-level keys:", list(data)[:15] if isinstance(data, dict) else type(data))
        print(json.dumps(data, indent=1)[:1500])
    except Exception:
        print("not JSON; first 600 chars:")
        print(j.text[:600])
except Exception as e:
    print("request failed:", type(e).__name__, e)
