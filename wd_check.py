#!/usr/bin/env python3
"""Check whether intern_only is safe for each Workday company.

For every Workday company in companies.yaml (or the ones named), it reads
the WHOLE board once, picks out postings whose title looks like a student
role, then reads the board again with the automatic intern/co-op filter,
and reports any student-titled posting the filter would miss.

    python wd_check.py
    python wd_check.py Stryker Magna

Run it from your PC (it reads full boards, so it takes a few minutes).
"""

import re
import sys

import yaml

from parsers import ats

STUDENT_TITLE = re.compile(r"intern|co-?op|coop|student|stagiaire", re.I)

conf = yaml.safe_load(open("companies.yaml", encoding="utf-8"))
ua = conf.get("defaults", {}).get("user_agent", "coop-tracker/1.0")
names = [n.lower() for n in sys.argv[1:]]

for c in conf["companies"]:
    if c.get("ats") != "workday" or not c.get("enabled", True):
        continue
    if names and not any(n in c["name"].lower() for n in names):
        continue
    if c.get("filter_values") or c.get("countries"):
        print(f"  SKIP  {c['name']:<36} already uses filter_values")
        continue

    full_cfg = {k: v for k, v in c.items() if k != "intern_only"}
    try:
        full = ats.workday(full_cfg, ua)
        students = {j["id"]: j["title"] for j in full
                    if STUDENT_TITLE.search(j["title"])}
        filt = ats.workday({**full_cfg, "intern_only": True}, ua)
    except Exception as e:
        print(f"  FAIL  {c['name']:<36} {type(e).__name__}: {str(e)[:60]}")
        continue

    got = {j["id"] for j in filt}
    missed = {i: t for i, t in students.items() if i not in got}
    if len(filt) == len(full):
        verdict = "NO FILTER (board has no intern option; leave intern_only off)"
    elif not missed:
        verdict = "SAFE - add intern_only: true"
    else:
        verdict = f"WOULD MISS {len(missed)} - leave intern_only off"
    print(f"  {c['name']:<36} full {len(full):>5} | filtered {len(filt):>4} | "
          f"student titles {len(students):>3} | {verdict}")
    for t in list(missed.values())[:5]:
        print(f"        missed: {t}")
