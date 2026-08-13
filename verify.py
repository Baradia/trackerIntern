#!/usr/bin/env python3
"""Test every configured endpoint, including disabled ones.

Run this before trusting companies.yaml, and again any time a company
goes quiet. Prints a count per company; 0 or ERROR means the token,
tenant, or site path is wrong.

    python verify.py
    python verify.py --tier ontario
"""

import argparse
import sys
import yaml
import os

from parsers import ats
from parsers.custom import CUSTOM

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier")
    ap.add_argument("--company")
    ap.add_argument("--only-disabled", action="store_true")
    args = ap.parse_args()

    with open(os.path.join(HERE, "companies.yaml"), encoding="utf-8") as f:
        conf = yaml.safe_load(f)

    ua = conf.get("defaults", {}).get("user_agent", "coop-tracker/1.0")
    companies = conf.get("companies", [])
    if args.tier:
        companies = [c for c in companies if c.get("tier") == args.tier]
    if args.company:
        companies = [c for c in companies
                     if args.company.lower() in c["name"].lower()]
        if not companies:
            sys.exit(f"no company matching {args.company}")
    if args.only_disabled:
        companies = [c for c in companies if not c.get("enabled", True)]

    ok, bad = [], []
    for c in companies:
        name = c["name"]
        flag = "" if c.get("enabled", True) else "  (disabled)"
        try:
            if c["ats"] == "custom":
                fn = CUSTOM.get(c.get("handler"))
                if not fn:
                    raise RuntimeError("no handler written yet")
                jobs = fn(c, ua)
            else:
                jobs = ats.LISTERS[c["ats"]](c, ua)
            n = len(jobs)
            if n:
                ok.append(name)
                sample = jobs[0]["title"][:40]
                rt = jobs[0].get("_reported_total")
                extra = f" (site reports {rt})" if rt is not None and rt != n else ""
                print(f"  OK    {name:<34} {n:>5} jobs{extra}   e.g. {sample}{flag}")
            else:
                bad.append(name)
                print(f"  EMPTY {name:<38}     0 jobs{flag}")
        except Exception as e:
            bad.append(name)
            print(f"  FAIL  {name:<38} {type(e).__name__}: "
                  f"{str(e)[:110]}{flag}")

    print(f"\n{len(ok)} working, {len(bad)} need fixing")
    if bad:
        print("Fix: " + ", ".join(bad))
    return 0


if __name__ == "__main__":
    sys.exit(main())
