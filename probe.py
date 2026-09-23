#!/usr/bin/env python3
"""Guess which self-serve ATS a company uses by trying slug variants.

Greenhouse / Lever / Ashby / BambooHR tokens are nearly always the company
name slugified, and a wrong guess just 404s. So try them all in parallel.

    python probe.py "Formlabs" "Verkada" "Seasats"
    python probe.py --file companies_to_check.txt

Prints ready-to-paste companies.yaml blocks for every hit.
Enterprises on Workday/SuccessFactors/Taleo will NOT be found here - those
need sniff.py against their careers URL instead.
"""

import argparse
import re
import sys
from concurrent.futures import ThreadPoolExecutor

import requests

UA = "UW-CoopTracker/1.0 (+a2baradi@uwaterloo.ca)"
TIMEOUT = 12


def slugs(name):
    base = name.lower().strip()
    base = re.sub(r"\b(inc|corp|corporation|ltd|limited|llc|co|company|"
                  r"technologies|technology|systems|industries|group)\b", "", base)
    base = base.strip()
    compact = re.sub(r"[^a-z0-9]", "", base)
    hyphen = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    first = compact.split()[0] if compact else compact
    out = [compact, hyphen, re.sub(r"[^a-z0-9]", "", name.lower()), first]
    seen, uniq = set(), []
    for s in out:
        if s and s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


def probes(token):
    return [
        ("greenhouse", f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
         lambda d: len(d.get("jobs", []))),
        ("lever", f"https://api.lever.co/v0/postings/{token}?mode=json",
         lambda d: len(d) if isinstance(d, list) else 0),
        ("ashby", f"https://api.ashbyhq.com/posting-api/job-board/{token}",
         lambda d: len(d.get("jobs", []))),
        ("bamboohr", f"https://{token}.bamboohr.com/careers/list",
         lambda d: len(d.get("result", []))),
    ]


def try_one(args):
    company, token, ats, url, count = args
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        n = count(r.json())
        return (company, ats, token, n) if n else None
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    ap.add_argument("--file", help="text file, one company per line")
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args()

    names = list(a.names)
    if a.file:
        with open(a.file, encoding="utf-8") as f:
            names += [ln.strip() for ln in f
                      if ln.strip() and not ln.lower().startswith("companies")]
    if not names:
        sys.exit("give company names or --file")

    tasks = []
    for nm in names:
        for tok in slugs(nm):
            for ats, url, count in probes(tok):
                tasks.append((nm, tok, ats, url, count))

    print(f"probing {len(names)} companies / {len(tasks)} combinations...\n")
    hits = {}
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for res in ex.map(try_one, tasks):
            if res:
                company, ats, token, n = res
                if company not in hits or n > hits[company][2]:
                    hits[company] = (ats, token, n)

    for nm in names:
        if nm in hits:
            ats, token, n = hits[nm]
            print(f"  FOUND  {nm:<32} {ats:<16} {token:<24} {n} jobs")
        else:
            print(f"  ----   {nm:<32} not on a self-serve ATS - use sniff.py")

    if hits:
        print("\n--- paste into companies.yaml ---\n")
        for nm, (ats, token, n) in hits.items():
            print(f"  - name: {nm}\n    ats: {ats}\n    token: {token}\n"
                  f"    tier: watchlist\n")


if __name__ == "__main__":
    main()
