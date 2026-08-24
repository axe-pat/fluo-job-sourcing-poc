# Contributing

This repository is a focused research POC. Small, evidence-backed changes are preferred over broad coverage claims.

## Before opening a change

1. Keep the no-scraping and no-authenticated-session boundary intact.
2. Add provider-specific tests for any new response shape.
3. Record the canonical career page and verification date for new employer mappings.
4. Do not describe an individual job as sponsoring unless the posting itself supports that claim.
5. Treat Workday and other public-site JSON separately from vendor-documented public APIs.

## Validation

~~~bash
make test
~~~

Live feed checks are intentionally separate from deterministic CI:

~~~bash
python3 scripts/verify_feeds.py --lookup data/ats_lookup.json
~~~

Feed endpoints change over time, so a failed live check should be investigated before changing normalization logic.
