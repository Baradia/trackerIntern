#!/usr/bin/env python3
"""Guess which ATS sits behind a careers page.

    python sniff.py https://jobs.dana.com/

Fetches the page and looks for known vendor fingerprints in the HTML and any
inline JS. Catches vanity domains that are really Workday/Greenhouse/etc.

A miss does not mean "custom" - it usually means the board is rendered by
JavaScript after load, in which case fall back to the network tab:
  F12 -> Network -> XHR -> reload -> find the request returning job JSON.
"""

import re
import sys
import requests

UA = "UW-CoopTracker/1.0 (+a2baradi@uwaterloo.ca)"

SIGNATURES = [
    ("workday",         r"myworkdayjobs\.com|myworkdaysite\.com|wday/cxs"),
    ("greenhouse",      r"greenhouse\.io|boards-api\.greenhouse"),
    ("lever",           r"jobs\.lever\.co|api\.lever\.co"),
    ("ashby",           r"ashbyhq\.com"),
    ("bamboohr",        r"bamboohr\.com/careers"),
    ("smartrecruiters", r"smartrecruiters\.com"),
    ("oracle",          r"oraclecloud\.com|CandidateExperience|hcmRestApi"),
    ("successfactors",  r"successfactors|sapsf\.com|/go/[A-Za-z-]+/\d+"),
    ("icims",           r"icims\.com"),
    ("taleo",           r"taleo\.net"),
    ("dayforce",        r"dayforcehcm\.com"),
    ("workable",        r"workable\.com"),
    ("jobvite",         r"jobvite\.com"),
    ("phenom",          r"phenompeople|phApp\."),
    ("radancy",         r"radancy|talentbrew"),
    ("adp",             r"myjobs\.adp\.com|workforcenow"),
    ("ukg",             r"ultipro\.com|ukg\.com"),
    ("prevue",          r"prevueaps\.com"),
]


def sniff(url):
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=30,
                         allow_redirects=True)
    except Exception as e:
        print(f"  fetch failed: {type(e).__name__}: {e}")
        return

    body = r.text
    print(f"  final url : {r.url}")
    print(f"  status    : {r.status_code}   {len(body):,} bytes")

    hits = [name for name, rx in SIGNATURES if re.search(rx, body, re.I)
            or re.search(rx, r.url, re.I)]
    if hits:
        print(f"  ATS       : {', '.join(hits)}")
    else:
        print("  ATS       : no fingerprint found (likely JS-rendered)")

    # surface any absolute URLs that smell like a job API
    apis = sorted(set(re.findall(
        r"https?://[\w.-]+/[\w/.-]*(?:job|career|search|posting|requisition)"
        r"[\w/.-]*", body, re.I)))[:12]
    if apis:
        print("  candidate endpoints:")
        for a in apis:
            print(f"    {a}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python sniff.py <careers-url> [more urls...]")
    for u in sys.argv[1:]:
        print(f"\n=== {u}")
        sniff(u)
