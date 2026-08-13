"""Template for an in-house careers portal parser.

Workflow for finding the endpoint:
  1. Open the company careers page.
  2. F12 -> Network tab -> filter XHR/Fetch -> reload the page.
  3. Look for a request returning a large JSON blob of job data.
  4. Right-click -> Copy as cURL to get the exact headers/body.
  5. Reproduce it below and map the fields into the normalized shape.

Copy this file, rename it, and register it in __init__.py.
"""

import requests

TIMEOUT = 20


def fetch(cfg, ua):
    url = cfg["url"]  # put the endpoint in companies.yaml
    r = requests.get(url, headers={"User-Agent": ua}, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()

    out = []
    for j in data.get("listings", []):          # <-- adjust to their shape
        out.append({
            "id": str(j["id"]),
            "title": j["title"],
            "location": j.get("city", ""),
            "url": cfg.get("url_prefix", "") + str(j["id"]),
            "description": j.get("description", "") or "",
        })
    return out
