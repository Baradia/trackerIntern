#!/usr/bin/env python3
"""Co-op / internship posting tracker.

Fetches postings from configured company career endpoints, filters them,
and posts new ones to Discord.

Filtering is layered:
  L1  title regex          HARD KILL
  L2  location whitelist   HARD KILL
  L3  description regex    TAG ONLY (never rejects)
  L4  scoring              orders and colours the output

Usage:
    python scraper.py
    python scraper.py --dry-run
    python scraper.py --company Magna --dry-run
    python scraper.py --tier ontario
    python scraper.py --seed          # record everything, post nothing
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
import datetime as dt

import yaml

from parsers import ats
from parsers.custom import CUSTOM
import notify

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "seen_jobs.json")
REJECT_LOG = os.path.join(HERE, "rejected.log")


# ---------------------------------------------------------------- config ---
def load_yaml(name):
    with open(os.path.join(HERE, name), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_state():
    if not os.path.exists(STATE_FILE):
        return {"jobs": {}, "health": {}, "seeded": False}
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        s = json.load(f)
    s.setdefault("jobs", {})
    s.setdefault("health", {})
    s.setdefault("seeded", False)
    return s


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1, sort_keys=True)


# --------------------------------------------------------------- helpers ---
TAG_STRIP = re.compile(r"<[^>]+>")
WS = re.compile(r"\s+")


def clean(html):
    return WS.sub(" ", TAG_STRIP.sub(" ", html or "")).strip()


def norm_title(t):
    return WS.sub(" ", re.sub(r"[^a-z0-9 ]", " ", (t or "").lower())).strip()


def keys_for(company, job):
    """Primary key uses the ATS id; secondary catches delete-and-repost."""
    primary = f"{company}::{job.get('id','')}"
    secondary = "alt::" + hashlib.sha1(
        f"{company}|{norm_title(job.get('title'))}|"
        f"{(job.get('location') or '').lower()}".encode()
    ).hexdigest()[:16]
    return primary, secondary


def log_reject(company, job, rule):
    line = (f"{dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}\t"
            f"{rule}\t{company}\t{job.get('title','')}\t"
            f"{job.get('location','')}\n")
    with open(REJECT_LOG, "a", encoding="utf-8") as f:
        f.write(line)


# --------------------------------------------------------------- filters ---
class Filters:
    def __init__(self, cfg):
        t = cfg.get("title", {})
        f = lambda p: re.compile(p, re.I) if p else None
        self.inc = f(t.get("include"))
        self.exc = f(t.get("exclude"))
        self.disc = f(t.get("discipline"))
        loc = cfg.get("location", {})
        self.loc_allow = [s.lower() for s in loc.get("allow", [])]
        self.loc_unknown_ok = loc.get("allow_unknown", True)
        self.tags = {k: re.compile(v, re.I)
                     for k, v in (cfg.get("tag") or {}).items()}
        self.scores = cfg.get("score", {})

    def title_ok(self, job):
        t = job.get("title", "")
        if self.exc and self.exc.search(t):
            return "L1-exclude"
        if self.inc and not self.inc.search(t):
            return "L1-not-student-role"
        if self.disc and not self.disc.search(t):
            return "L1-wrong-discipline"
        return None

    def location_ok(self, job):
        loc = (job.get("location") or "").lower()
        if not loc:
            return None if self.loc_unknown_ok else "L2-no-location"
        if not self.loc_allow:
            return None
        if any(a in loc for a in self.loc_allow):
            return None
        return "L2-location"

    def tag(self, job):
        blob = f"{job.get('title','')} {clean(job.get('description',''))}"
        return [name for name, rx in self.tags.items() if rx.search(blob)]

    def score(self, job):
        s = int(self.scores.get("base", 0))
        blob = f"{job.get('title','')} {clean(job.get('description',''))}"
        for kw, pts in (self.scores.get("keywords") or {}).items():
            if re.search(kw, blob, re.I):
                s += int(pts)
        for tag, pts in (self.scores.get("tags") or {}).items():
            if tag in job.get("tags", []):
                s += int(pts)
        return s


# ----------------------------------------------------------------- fetch ---
def fetch_company(c, ua):
    kind = c.get("ats")
    if kind == "custom":
        fn = CUSTOM.get(c.get("handler"))
        if not fn:
            raise RuntimeError(f"no custom handler '{c.get('handler')}'")
        return fn(c, ua)
    fn = ats.LISTERS.get(kind)
    if not fn:
        raise RuntimeError(f"unknown ats '{kind}'")
    return fn(c, ua)


def add_details(c, jobs, ua, cap):
    fn = ats.DETAILERS.get(c.get("ats"))
    if not fn:
        return
    for j in jobs[:cap]:
        if j.get("description"):
            continue
        j["description"] = fn(c, j, ua)
        time.sleep(0.3)


# ------------------------------------------------------------------ main ---
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="print instead of posting; do not write state")
    ap.add_argument("--company", help="run a single company by name")
    ap.add_argument("--tier", help="run only companies in this tier")
    ap.add_argument("--seed", action="store_true",
                    help="record all current postings without notifying")
    args = ap.parse_args()

    conf = load_yaml("companies.yaml")
    filters = Filters(load_yaml("filters.yaml"))
    ua = conf.get("defaults", {}).get("user_agent", "coop-tracker/1.0")
    detail_cap = int(conf.get("defaults", {}).get("detail_cap", 25))

    companies = conf.get("companies", [])
    if args.company:
        companies = [c for c in companies
                     if c["name"].lower() == args.company.lower()]
        if not companies:
            sys.exit(f"no company named {args.company}")
    if args.tier:
        companies = [c for c in companies if c.get("tier") == args.tier]
    companies = [c for c in companies if c.get("enabled", True)]

    state = load_state()
    seeding = args.seed or not state["seeded"]
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    new_jobs, broken = [], []

    for c in companies:
        name = c["name"]
        h = state["health"].setdefault(name, {})
        try:
            raw = fetch_company(c, ua)
        except Exception as e:
            h["last_error"] = f"{now}: {type(e).__name__}: {e}"[:300]
            h["consecutive_empty"] = h.get("consecutive_empty", 0) + 1
            broken.append(f"{name}: {type(e).__name__}")
            print(f"[error] {name}: {e}")
            continue

        print(f"[ok]    {name}: {len(raw)} postings")

        if not raw:
            h["consecutive_empty"] = h.get("consecutive_empty", 0) + 1
            if h["consecutive_empty"] >= 2:
                broken.append(f"{name}: 0 postings x{h['consecutive_empty']}")
        else:
            h["consecutive_empty"] = 0
            h["last_success"] = now
            h["last_count"] = len(raw)

        # L1 + L2
        survivors = []
        for j in raw:
            r = filters.title_ok(j) or filters.location_ok(j)
            if r:
                log_reject(name, j, r)
                continue
            survivors.append(j)

        # dedup before spending requests on descriptions
        fresh = []
        for j in survivors:
            pk, sk = keys_for(name, j)
            if pk in state["jobs"] or sk in state["jobs"]:
                continue
            j["_pk"], j["_sk"] = pk, sk
            j["company"] = name
            j["tier"] = c.get("tier", "")
            fresh.append(j)

        if fresh and not seeding:
            add_details(c, fresh, ua, detail_cap)

        for j in fresh:
            j["tags"] = filters.tag(j)
            j["score"] = filters.score(j)
            state["jobs"][j["_pk"]] = now
            state["jobs"][j["_sk"]] = now
            new_jobs.append(j)

    print(f"\n{len(new_jobs)} new posting(s)")

    if seeding:
        notify.send_text(
            f"Seeded {len(new_jobs)} existing postings across "
            f"{len(companies)} companies. Alerts start next run.",
            dry_run=args.dry_run)
        state["seeded"] = True
    elif new_jobs:
        notify.send_jobs(new_jobs, dry_run=args.dry_run)

    if broken:
        notify.send_text("Scraper health: " + "; ".join(broken),
                         dry_run=args.dry_run, alert=True)

    if not args.dry_run:
        save_state(state)


if __name__ == "__main__":
    main()
