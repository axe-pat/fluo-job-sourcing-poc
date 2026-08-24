#!/usr/bin/env python3
"""Join verified ATS lookups to the ranked DOL-derived employer catalog."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold().replace("&", " and "))


def feed_url(
    ats_type: str,
    slug: str,
    region: str = "global",
    *,
    ats_host: str = "",
    workday_site: str = "",
) -> str:
    if ats_type == "greenhouse":
        return f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    if ats_type == "lever":
        host = "api.eu.lever.co" if region == "eu" else "api.lever.co"
        return f"https://{host}/v0/postings/{slug}?mode=json"
    if ats_type == "ashby":
        return f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    if ats_type == "workday":
        return f"https://{ats_host}/wday/cxs/{slug}/{workday_site}/jobs"
    raise ValueError(f"Unsupported ATS type: {ats_type}")


def load_candidates(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return dict(raw["manifest"]), list(raw["companies"])


def match_candidate(lookup: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    targets = {normalized(name) for name in lookup.get("lca_names", [])}
    matches = []
    for candidate in candidates:
        names = {normalized(candidate["legal_name"]), *(normalized(name) for name in candidate.get("aliases", []))}
        if targets & names:
            matches.append(candidate)
    if len(matches) != 1:
        raise ValueError(f"Expected one DOL match for {lookup['name']!r}, found {len(matches)}")
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, default=Path("data/socal_lca_companies.json"))
    parser.add_argument("--lookup", type=Path, default=Path("data/ats_lookup.json"))
    parser.add_argument("--output", type=Path, default=Path("data/companies.json"))
    args = parser.parse_args()
    manifest, candidates = load_candidates(args.candidates)
    lookup_payload = json.loads(args.lookup.read_text(encoding="utf-8"))
    companies = []
    for lookup in lookup_payload["companies"]:
        if not lookup.get("feed_verified_at"):
            continue
        candidate = match_candidate(lookup, candidates)
        ats_type = lookup["ats_type"].lower()
        region = lookup.get("ats_region", "global").lower()
        ats_host = lookup.get("ats_host", "").lower()
        workday_site = lookup.get("workday_site", "")
        companies.append(
            {
                "name": lookup["name"],
                "legal_name": candidate["legal_name"],
                "ats_type": ats_type,
                "ats_slug": lookup["ats_slug"],
                "ats_region": region,
                "ats_host": ats_host,
                "workday_site": workday_site,
                "approval_count": candidate["approval_count"],
                "approval_rate": candidate["approval_rate"],
                "certified_positions": candidate["certified_positions"],
                "industry": candidate["industry"],
                "hq_location": candidate["hq_location"],
                "socal_worksites": candidate["socal_worksites"],
                "feed_url": feed_url(
                    ats_type,
                    lookup["ats_slug"],
                    region,
                    ats_host=ats_host,
                    workday_site=workday_site,
                ),
                "feed_verified_at": lookup["feed_verified_at"],
                "lca_rank": candidate["rank"],
                "job_board_url": lookup.get("job_board_url", ""),
            }
        )
    companies.sort(key=lambda item: (-item["approval_count"], item["name"].casefold()))
    output = {
        "schema_version": 1,
        "source": manifest["source"],
        "prototype_decisions": {
            "refresh_frequency": "daily (24 hours) for v1; requester confirmation pending",
            "geographic_scope": "H-1B cases with a worksite in the 10 Southern California counties",
            "sponsor_signal": "H-1B LCA history only; OPT/CPT signals are not included",
            "posted_date_policy": "Ashby publishedAt; Greenhouse updated_at; Workday relative posted labels; Lever uses first_seen_at",
        },
        "companies": companies,
    }
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(companies)} verified ATS companies to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
