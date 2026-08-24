# POC findings and scale plan

This note separates what the prototype measured from what still needs a larger study. It is intentionally conservative: the value of the POC is the boundary it makes visible, not an inflated coverage claim.

## What was measured

The candidate catalog contains 230 employers with H-1B LCA worksite activity in the scoped Southern California period. Thirty-one employers were manually mapped to a feed. All 31 mappings were rechecked live on August 23, 2026; the hosted 8,145-job snapshot remains the August 5 capture.

| Feed class | Employers | Evidence standard | Operational profile |
| --- | ---: | --- | --- |
| Greenhouse | 15 | Vendor-documented public Job Board API | Standard host + board slug |
| Lever | 1 | Vendor-documented Postings API | Standard host + site slug |
| Ashby | 1 | Vendor-documented public posting API | Standard host + board name |
| Workday | 14 | Unauthenticated JSON used by the public careers UI | Tenant, host, and site-specific configuration |
| **Total** | **31** |  |  |

All 31 configured sources returned complete responses in the latest health check. The hosted snapshot contains 8,145 active jobs; 30 employers had at least one job and one healthy Lever board was empty at capture time.

## What was not measured

The POC did **not** exhaustively classify the other 199 employers. Therefore:

- 31/230 is a verified coverage floor, not an estimated accessibility rate.
- It is not valid to say that 199 employers lack public feeds.
- It is not yet possible to state what percentage of relevant sponsoring jobs the system captures.
- Company-wide ATS feeds do not provide a denominator for “sponsoring jobs”; LCA evidence is company-level and the individual postings rarely state sponsorship consistently.

The next evidence-producing step is a denominator study: take a pre-declared, stratified sample of the 230 employers, classify every one, and record both employer count and observable job volume by source class.

Suggested terminal classifications:

1. documented public feed;
2. unauthenticated public-site JSON, such as Workday;
3. public feed requiring a new provider adapter;
4. custom public portal with no acceptable structured feed;
5. authentication required;
6. no careers presence or no jobs;
7. unresolved after a defined review budget.

That study turns “coverage floor” into a defensible range and prevents easy employers from biasing the estimate.

## What scales easily

- **Polling:** 300 employers once per hour is only 7,200 feed checks per day. With bounded concurrency, conditional requests where supported, jitter, backoff, and provider-specific limits, compute is not the bottleneck.
- **Normalization:** the schema and adapter boundary already accommodate additional providers.
- **Storage:** SQLite is sufficient for the prototype. A managed relational database is a straightforward production substitution.
- **De-duplication:** external source IDs are stable for the tested providers; `first_seen_at` survives re-fetches and reactivation.
- **Read UI:** the public surface is a read-only filter-and-link experience with no account or application state.

## What does not scale automatically

### Employer onboarding

Each company still needs a reviewer to:

- find the canonical careers page;
- identify the ATS and region;
- verify the exact board, tenant, or site identifier;
- confirm the response is complete and job links resolve;
- record evidence and `feed_verified_at`;
- decide whether the source meets the product’s legal standard.

The mapping is mostly static, but it is not permanent. Employers rebrand, switch ATS vendors, split regional boards, and change tenants.

### Provider variance

Greenhouse, Lever, and Ashby are low-variance integrations. Workday is higher variance: hosts, tenants, career-site identifiers, pagination, and relative-date fields need per-company verification. Other enterprise ATS products and custom portals will require separate decisions and adapters.

For authenticated or custom portals with no acceptable structured feed, “make a GET request” is not a sufficient answer. The safe options are a vendor/partner API, a company-provided feed, a licensed data provider, or leaving the employer uncovered. Logged-in scraping is outside this project’s boundary.

### Freshness operations

A refresh is valuable because it creates a stable first-observed timestamp, detects additions and removals, and measures source health. Moving from daily to hourly does not fundamentally change the application, but it adds production obligations:

- rate-limit and retry policy by provider;
- jittered schedules rather than synchronized bursts;
- alerting on feed-shape changes and repeated failures;
- an operator queue for broken mappings;
- retention and observability;
- a documented removal/contact process for source owners.

## Planning estimates

These are planning ranges, not measured throughput:

| Work | Working estimate |
| --- | ---: |
| Straightforward documented-API onboarding | 10–30 minutes per employer |
| Workday or ambiguous portal investigation | 30–90 minutes per employer |
| Initial 300-employer mapping campaign | roughly 75–200 reviewer-hours |
| Steady-state catalog/feed maintenance | roughly 2–6 hours per week at this scale |

Actual effort depends on the provider mix and the evidence standard. A 50-employer timed audit should replace these assumptions before committing a roadmap.

## Product decisions still required

1. **Freshness:** daily proves the loop; hourly better supports the “first to know” pitch.
2. **Geography:** SoCal employer seeding versus a nationwide catalog.
3. **Sponsor signal:** H-1B LCA history only versus separate, evidence-backed OPT/CPT signals.
4. **Source policy:** documented public APIs only, or a reviewed category for unauthenticated public-site JSON.
5. **Job scope:** show company-wide roles or apply a location filter after ingestion.

## Bottom line

The technical loop is buildable, inexpensive, and safe for a curated provider set. The scale risk is not fetching JSON; it is establishing and maintaining a trustworthy employer-to-feed catalog while staying honest about provider documentation, company-level sponsorship evidence, and uncovered employers.
