# Hosted snapshot UI

This directory contains the exact read-only frontend deployed at:

**https://fluo-job-sourcing-poc.fluo-job-sourcing.workers.dev/**

It intentionally serves a checked-in snapshot rather than making third-party ATS calls from visitors’ browsers. The Python service at the repository root owns feed refreshes, normalized state, and `first_seen_at`.

## Local development

~~~bash
npm ci
npm test
npm run dev
~~~

Requirements: Node.js 22 or newer. All npm dependencies are pinned by `package-lock.json`.

## Update the snapshot

Start the local Python service, then export its complete state:

~~~bash
# Repository root
python3 -m fluo refresh
python3 -m fluo serve --no-auto-refresh

# In a second terminal
cd web
npm run snapshot:export
npm test
~~~

Override the defaults with `FLUO_LOCAL_URL` or `FLUO_SNAPSHOT_PATH` if needed.

## Deployment

~~~bash
npm run deploy
~~~

Cloudflare credentials are account-local and are never stored in this repository. The deployment has no database binding or write endpoint.

## Boundary

- The hosted page is a fixed research snapshot.
- Application links go directly to each employer’s ATS.
- Company LCA history does not establish sponsorship for an individual role.
- The Workday subset is labeled as a stretch source class; see the root README for the documentation distinction.
