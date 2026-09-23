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

# common places a careers page lives, tried in order
GUESS_PATHS = ["/careers", "/careers/", "/jobs", "/jobs/", "/company/careers",
               "/about/careers", "/en/careers", "/careers/open-positions",
               "/careers/jobs"]
GUESS_HOSTS = ["careers.{d}", "jobs.{d}", "www.{d}", "{d}"]


def guess_urls(domain):
    d = domain.replace("https://", "").replace("http://", "").strip("/")
    d = d.replace("www.", "")
    urls = []
    for h in GUESS_HOSTS[:2]:
        urls.append(f"https://{h.format(d=d)}/")
    for p in GUESS_PATHS:
        urls.append(f"https://www.{d}{p}")
    return urls


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


def guess(domain):
    """Try common careers URLs for a bare domain, stop at the first that
    fingerprints an ATS."""
    print(f"\n=== {domain}  (guessing careers URL)")
    best = None
    for u in guess_urls(domain):
        try:
            r = requests.get(u, headers={"User-Agent": UA}, timeout=15,
                             allow_redirects=True)
        except Exception:
            continue
        if r.status_code != 200 or len(r.text) < 2000:
            continue
        hits = [n for n, rx in SIGNATURES
                if re.search(rx, r.text, re.I) or re.search(rx, r.url, re.I)]
        if hits:
            print(f"  {u}")
            print(f"  final url : {r.url}")
            print(f"  ATS       : {', '.join(hits)}")
            return
        best = best or (u, r.url)
    if best:
        print(f"  reachable but no fingerprint: {best[1]}")
        print("  -> JS-rendered; try capture.py on that URL")
    else:
        print("  no careers page found at the usual paths - find it manually")


if __name__ == "__main__":
    ap = __import__("argparse").ArgumentParser()
    ap.add_argument("targets", nargs="+",
                    help="full careers URLs, or bare domains with --guess")
    ap.add_argument("--guess", action="store_true",
                    help="treat targets as domains and try common careers paths")
    a = ap.parse_args()
    for t in a.targets:
        if a.guess:
            guess(t)
        else:
            print(f"\n=== {t}")
            sniff(t)
