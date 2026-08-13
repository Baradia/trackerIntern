# Co-op Posting Tracker

Polls company career endpoints, filters for mechanical co-op roles, posts new
ones to Discord. Runs free on GitHub Actions.

## Files

| File | Purpose |
|---|---|
| `scraper.py` | main run loop, filtering, dedup, state |
| `verify.py` | tests every endpoint in the config |
| `notify.py` | Discord webhook output |
| `companies.yaml` | which companies, which ATS, which tier |
| `filters.yaml` | all filtering and scoring rules |
| `parsers/ats.py` | Greenhouse / Lever / SmartRecruiters / Workday |
| `parsers/custom/` | in-house portals (phase 2) |
| `seen_jobs.json` | state, committed by the workflow |
| `rejected.log` | every killed posting and the rule that killed it |

## Filtering

- **L1 title regex** — hard kill
- **L2 location whitelist** — hard kill
- **L3 description regex** — tags only, never rejects
- **L4 score** — orders output, colours the embed (green ≥4, yellow ≥1, grey below)

Sponsorship language, year requirements, and term length are **tagged, not
killed**. They show up in the embed footer so you decide.

Descriptions are only fetched for postings that are new *and* survived L1/L2,
so it stays cheap.

## Commands

```bash
python verify.py                          # test all endpoints
python verify.py --only-disabled          # test the ones not yet confirmed
python scraper.py --dry-run               # print, don't post, don't save
python scraper.py --company Linamar --dry-run
python scraper.py --tier ontario
python scraper.py --seed                  # record everything, notify nothing
```

First run auto-seeds so you don't get 400 embeds at once.

## Adding a company

Greenhouse / Lever / SmartRecruiters — the token is in the careers page URL:

```yaml
- name: Rivian
  ats: greenhouse
  token: rivian
  tier: california
```

Workday — F12 → Network → click page 2 of results → find the POST to
`.../wday/cxs/<tenant>/<site>/jobs`:

```yaml
- name: Magna International
  ats: workday
  tenant: magna
  wd: wd1
  site: Careers
  tier: ontario
```

Then `python verify.py --company ...` before committing.

## Phase 2: in-house portals

Copy `parsers/custom/_example.py`, map their JSON into
`{id, title, location, url, description}`, register it in
`parsers/custom/__init__.py`, set `ats: custom` + `handler: <name>`.
Nothing else in the pipeline changes.

## Health

Any company returning zero postings twice in a row, or erroring, triggers a red
Discord alert. This is the thing that stops silent failure — a parser breaking
looks identical to "no new jobs" otherwise.

GitHub disables scheduled workflows after 60 days of repo inactivity. Push
something occasionally or trigger a manual run.
