"""Discord webhook output. Batches embeds and respects rate limits."""

import os
import time
import requests

MAX_EMBEDS = 10          # Discord hard limit per message
SLEEP_BETWEEN = 1.5      # stay well under ~30 messages/minute

GREEN = 0x2ECC71
YELLOW = 0xF1C40F
GREY = 0x95A5A6
RED = 0xE74C3C


def _color(score):
    if score >= 4:
        return GREEN
    if score >= 1:
        return YELLOW
    return GREY


def _embed(job):
    footer = " · ".join(job.get("tags", []))
    e = {
        "title": job["title"][:250],
        "url": job["url"],
        "description": f"**{job['company']}** — {job['location'] or 'location n/a'}",
        "color": _color(job.get("score", 0)),
    }
    if footer:
        e["footer"] = {"text": footer}
    return e


def _post(webhook, payload):
    for attempt in range(4):
        try:
            r = requests.post(webhook, json=payload, timeout=20)
        except Exception:
            time.sleep(3 * (attempt + 1))
            continue
        if r.status_code == 429:
            wait = 5.0
            try:
                wait = float(r.json().get("retry_after", 5))
            except Exception:
                pass
            time.sleep(wait + 0.5)
            continue
        if r.status_code < 300:
            return True
        time.sleep(2 * (attempt + 1))
    return False


def send_jobs(jobs, webhook=None, dry_run=False):
    webhook = webhook or os.environ.get("DISCORD_WEBHOOK", "")
    jobs = sorted(jobs, key=lambda j: -j.get("score", 0))

    if dry_run or not webhook:
        print(f"\n[notify] would post {len(jobs)} job(s):")
        for j in jobs:
            tags = ",".join(j.get("tags", []))
            print(f"  [{j.get('score',0):>2}] {j['company']:<28} "
                  f"{j['title'][:60]:<62} {tags}")
        return

    for i in range(0, len(jobs), MAX_EMBEDS):
        chunk = jobs[i:i + MAX_EMBEDS]
        _post(webhook, {"embeds": [_embed(j) for j in chunk]})
        time.sleep(SLEEP_BETWEEN)


def send_text(msg, webhook=None, dry_run=False, alert=False):
    webhook = webhook or os.environ.get("DISCORD_WEBHOOK", "")
    if dry_run or not webhook:
        print(f"[notify] {msg}")
        return
    payload = {"embeds": [{"description": msg,
                           "color": RED if alert else GREY}]}
    _post(webhook, payload)
