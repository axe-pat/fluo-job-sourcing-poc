#!/usr/bin/env python3
"""Verify configured lookup entries against their reviewed ATS JSON feeds."""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fluo.ats import build_feed_url, fetch_company_jobs  # noqa: E402
from fluo.catalog import Company  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def probe(raw: dict, timeout: float) -> dict:
    company = Company.from_dict(
        {
            **raw,
            "legal_name": raw.get("lca_names", [raw["name"]])[0],
            "approval_count": 0,
            "approval_rate": 0,
            "certified_positions": 0,
            "industry": "Unknown",
            "hq_location": "Unknown",
            "socal_worksites": [],
            "feed_url": "",
            "feed_verified_at": raw.get("feed_verified_at", "pending"),
        }
    )
    started = time.perf_counter()
    try:
        jobs = fetch_company_jobs(company, timeout=timeout)
        sample = jobs[0].to_dict() if jobs else None
        return {
            "name": company.name,
            "ats_type": company.ats_type,
            "ats_slug": company.ats_slug,
            "feed_url": build_feed_url(company),
            "status": "ok",
            "job_count": len(jobs),
            "sample": sample,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }
    except Exception as exc:
        return {
            "name": company.name,
            "ats_type": company.ats_type,
            "ats_slug": company.ats_slug,
            "feed_url": build_feed_url(company),
            "status": "error",
            "job_count": 0,
            "error": str(exc),
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lookup", type=Path, default=PROJECT_ROOT / "data" / "ats_lookup.json")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "data" / "feed_verification.json")
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--only", action="append", default=[], help="Company name to verify; repeatable")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    raw = json.loads(args.lookup.read_text(encoding="utf-8"))
    only = {name.casefold() for name in args.only}
    entries = [entry for entry in raw["companies"] if not only or entry["name"].casefold() in only]
    indexed_results: dict[int, dict] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 8))) as pool:
        futures = {pool.submit(probe, entry, args.timeout): index for index, entry in enumerate(entries)}
        for future in as_completed(futures):
            indexed_results[futures[future]] = future.result()
    results = [indexed_results[index] for index in range(len(entries))]
    payload = {"verified_at": utc_now(), "results": results}
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    for result in results:
        print(f"{result['status']:5} {result['job_count']:4} {result['ats_type']:10} {result['name']}")
    failures = sum(result["status"] != "ok" for result in results)
    print(f"Verified {len(results) - failures}/{len(results)} feeds; report: {args.output}")
    return 0 if failures == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
