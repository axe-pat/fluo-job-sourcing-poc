# Fluo Job Sourcing POC

[![CI](https://github.com/axe-pat/fluo-job-sourcing-poc/actions/workflows/ci.yml/badge.svg)](https://github.com/axe-pat/fluo-job-sourcing-poc/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Node 22+](https://img.shields.io/badge/Node-22%2B-339933?logo=nodedotjs&logoColor=white)](https://nodejs.org/)
[![Sources](https://img.shields.io/badge/sources-JSON%20feeds%20only-173D2A)](#source-and-safety-boundary)
[![Scraping](https://img.shields.io/badge/LinkedIn%20scraping-none-C8F45B)](#source-and-safety-boundary)

**Can Fluo become “first to know” when sponsor-relevant employers publish jobs—without scraping LinkedIn or automating logged-in sessions?**

This repository is the working proof of concept: it ranks a Southern California employer seed from public U.S. Department of Labor LCA disclosure data, maps a reviewed subset to their hiring systems, normalizes their job feeds, preserves when each role was first observed, and serves a filterable dashboard.

**[Open the hosted demo →](https://fluo-job-sourcing-poc.fluo-job-sourcing.workers.dev/)**

> The public demo is a fixed, verified snapshot captured on August 5, 2026. The Python service in this repository owns live refreshes; an always-on refresh schedule is intentionally not claimed.

## What the POC established

| Measure | Verified result |
| --- | ---: |
| DOL-derived SoCal candidate employers | **230** |
| Manually mapped and feed-verified employers | **31** |
| Vendor-documented public API feeds | **17** |
| Workday stretch feeds | **14** |
| Successful feeds in the latest health check | **31 / 31** |
| Active openings in the hosted snapshot | **8,145** |
| Employers with at least one opening | **30** |

The **31 of 230** result is a coverage floor, not a claim that only 13.5% of the candidate set is accessible. The remaining 199 employers were not exhaustively classified. A defensible coverage percentage requires completing that audit against a pre-declared sample.

The 17/14 split matters:

- **17 core feeds** use vendor-documented job-board APIs: 15 Greenhouse, 1 Lever, and 1 Ashby.
- **14 stretch feeds** use unauthenticated Workday JSON endpoints called by the employers’ public career sites. They require more company-specific configuration and do not have the same third-party documentation posture. They are isolated in the adapter and can be excluded if the product standard is “documented API only.”

## Architecture

~~~mermaid
flowchart LR
    DOL["DOL FY2026 Q2 LCA disclosure"] --> C["230-company SoCal candidate catalog"]
    C --> M["Manual ATS + board-ID verification"]
    M --> W["31-company reviewed watchlist"]
    W --> A["Greenhouse / Lever / Ashby adapters"]
    W --> X["Workday stretch adapter"]
    A --> N["Normalized job records"]
    X --> N
    N --> S["SQLite upsert + first_seen_at"]
    S --> API["Loopback JSON API"]
    API --> UI["Local live dashboard"]
    S --> E["Snapshot export"]
    E --> WEB["Public read-only demo"]
~~~

The fetch path is deliberately boring: HTTPS JSON requests, provider-specific normalizers, stable IDs, SQLite upserts, and a read-only list UI. There is no ranking model, application automation, browser driver, or authenticated third-party session.

## Run it from a clean clone

The ingestion service has **no third-party runtime dependencies**; Python’s standard library is enough.

~~~bash
git clone https://github.com/axe-pat/fluo-job-sourcing-poc.git
cd fluo-job-sourcing-poc

# Verify the deterministic backend suite.
python3 -W error::ResourceWarning -m unittest discover -s tests -v

# Fetch all configured feeds and build local SQLite state.
python3 -m fluo refresh

# Serve the live local dashboard without a background refresh thread.
python3 -m fluo serve --no-auto-refresh
~~~

Open [http://127.0.0.1:8876](http://127.0.0.1:8876).

To refresh immediately and then every 24 hours while the process is running:

~~~bash
python3 -m fluo serve --refresh-hours 24
~~~

For cron or another scheduler:

~~~bash
./scripts/run_daily.sh
~~~

### Run the shareable snapshot UI

The exact frontend deployed to Cloudflare lives in `web/`. Its dependencies are locked in `web/package-lock.json`.

~~~bash
cd web
npm ci
npm test
npm run dev
~~~

After refreshing the Python service locally, regenerate the hosted snapshot with:

~~~bash
cd web
npm run snapshot:export
~~~

## What refresh actually does

Every refresh re-fetches the same reviewed company-to-feed mappings:

1. Normalize each provider response into one schema.
2. Upsert by company plus external job ID.
3. Preserve the original `first_seen_at` when a job is seen again.
4. Add genuinely new IDs as new roles.
5. Mark missing roles inactive **only when that company’s full feed completed successfully**.
6. Leave prior jobs untouched when a feed fails, avoiding false “closed” roles.

Companies do not fall out of the curated watchlist just because they have no openings. Their job rows disappear from the active-job view after a successful refresh; new or returning roles appear on subsequent runs.

## Sponsor-signal methodology

The seed uses **DOL LCA Disclosure Data FY2026 Q2**, covering determinations from **October 1, 2025 through March 31, 2026**. It keeps H-1B worksite rows in ten Southern California counties, groups employer records, and ranks them by scoped filing activity.

An **LCA** (Labor Condition Application) is a filing an employer submits to the U.S. Department of Labor before an H-1B petition. It is evidence of employer-level H-1B activity—not USCIS petition approval and not proof that a particular open role offers sponsorship.

In the UI, **“100% · 10 LCA”** means the company had ten approved LCA cases and no denied cases in this scoped DOL period. It is a company-level historical signal. Withdrawn-only cases are excluded from the approval-rate denominator.

Other field definitions:

- `approval_count`: cases whose status begins with `Certified`, including `Certified - Withdrawn`.
- `approval_rate`: approved divided by approved plus denied.
- `certified_positions`: worker positions across approved cases.
- `hq_location`: the most frequent employer city/state in the disclosure records; a filing-location proxy, not verified headquarters.

Rebuild the catalog from a newly downloaded official workbook:

~~~bash
python3 -m pip install -e '.[dol-import]'
python3 scripts/build_company_catalog.py \
  --input /path/to/LCA_Disclosure_Data.xlsx \
  --output-dir data \
  --limit 230
python3 scripts/build_curated_catalog.py
~~~

## Source and safety boundary

The recurring product path does not fetch HTML:

- no LinkedIn or Indeed integration;
- no Playwright, browser automation, CAPTCHA bypass, or logged-in session;
- no general-purpose URL input;
- no job-application automation;
- no LLM matching or ranking.

Greenhouse, Lever, and Ashby calls are constrained to fixed vendor hosts. Workday hosts must match a strict `*.wdN.myworkdayjobs.com` pattern. Redirect targets are revalidated, responses are size-limited, and the write-triggering refresh endpoint accepts loopback clients only.

“No scraping” does **not** mean “no operational or legal review.” Workday remains the greyest source class here. Production rollout should confirm provider terms, use conservative polling, identify itself, respect rate limits, and remove any source whose owner objects.

## Repository map

~~~text
fluo/                 Python feed adapters, refresh orchestration, DB, API
scripts/              Catalog builders, live-feed verifier, scheduled entrypoint
static/               Lightweight local live dashboard
tests/                Deterministic backend tests
data/                 Reviewed mappings, DOL-derived catalog, source manifest
web/                  Exact hosted snapshot UI and Cloudflare build
docs/FINDINGS.md      Scale, coverage, effort, and maintenance conclusions
SECURITY.md           Security boundary and disclosure guidance
~~~

## Scaling conclusion

Polling and storage are the easy part. At 300 companies, hourly JSON polling is still modest infrastructure. The dominant work is company onboarding and maintenance: identifying the ATS, verifying the exact board identifier, documenting evidence, monitoring failures, and handling migrations or employers with no acceptable public feed.

Planning estimates and the proposed coverage study are in **[docs/FINDINGS.md](docs/FINDINGS.md)**.

## Current limitations

- The public site is a snapshot, not an always-on refresh service.
- Candidate employers are based on SoCal worksites, while ATS feeds are company-wide and include global roles.
- The POC uses H-1B LCA history only; it does not model OPT/CPT friendliness.
- All 31 mappings were rechecked live on August 23, 2026; feed health remains point-in-time.
- No claim is made that every captured job sponsors or that every relevant job is captured.

## References

- [DOL OFLC disclosure data](https://www.dol.gov/agencies/eta/foreign-labor/performance)
- [Greenhouse Job Board API](https://developers.greenhouse.io/job-board.html)
- [Lever Postings API](https://github.com/lever/postings-api)
- [Ashby public job posting API](https://developers.ashbyhq.com/docs/public-job-posting-api)

---

Built as a standalone Fluo research prototype. It is not yet integrated with the production Fluo product.
