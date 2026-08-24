# Security

## Scope

This is a research prototype. The Python service is designed for local use and binds to loopback by default. The hosted Cloudflare site is a read-only snapshot and exposes no refresh, database, or administrative endpoint.

## Data-source boundary

- Only HTTPS JSON endpoints on approved ATS hosts are fetched.
- Greenhouse, Lever, and Ashby use fixed vendor allowlists.
- Workday hosts must match the expected `*.wdN.myworkdayjobs.com` form.
- Redirect destinations are validated against the same boundary.
- Responses have a 25 MiB maximum and bounded timeouts/retries.
- Catalog fields cannot supply an arbitrary fetch URL.
- The local refresh endpoint rejects non-loopback clients.

This repository contains no LinkedIn/Indeed automation, browser driver, credential capture, authenticated third-party session, or application-submission flow.

## Secrets

The application requires no API keys or secrets for its configured feeds. Environment files, local databases, caches, deployment state, and credential-like key files are ignored by Git.

If a credential is ever committed, removing it in a later commit is insufficient: revoke or rotate it first, then clean the history.

## Supported status

This code is not a production service and does not carry an uptime or security-support SLA. For a production rollout, add authenticated administration, managed secret storage, central logging, dependency monitoring, rate-limit policy, and an owner-contact/removal process.

## Reporting

Please report a suspected vulnerability privately to the repository owner rather than opening a public issue. Include the affected surface, reproduction steps, and potential impact; do not include real credentials or personal data.
