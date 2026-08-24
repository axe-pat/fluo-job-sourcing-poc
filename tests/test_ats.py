from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from fluo.ats import (
    FeedError,
    build_feed_url,
    fetch_workday_jobs,
    normalize_ashby,
    normalize_greenhouse,
    normalize_lever,
    normalize_workday,
)
from fluo.catalog import Company


def company(ats_type: str = "greenhouse", **overrides) -> Company:
    raw = {
        "name": "Example",
        "legal_name": "Example, Inc.",
        "ats_type": ats_type,
        "ats_slug": "example",
        "approval_count": 3,
        "approval_rate": 1,
        "certified_positions": 4,
        "industry": "Information",
        "hq_location": "Los Angeles, CA",
        "socal_worksites": ["Los Angeles"],
        "feed_url": "",
        "feed_verified_at": "2026-08-05",
    }
    raw.update(overrides)
    return Company.from_dict(raw)


class NormalizerTests(unittest.TestCase):
    def test_greenhouse_normalization(self) -> None:
        jobs = normalize_greenhouse(
            {
                "jobs": [
                    {
                        "id": 42,
                        "title": " Product Manager ",
                        "absolute_url": "https://job-boards.greenhouse.io/example/jobs/42",
                        "updated_at": "2026-08-04T12:30:00-07:00",
                        "location": {"name": "Los Angeles"},
                        "departments": [{"name": "Product"}],
                    }
                ]
            }
        )
        self.assertEqual(jobs[0].external_id, "42")
        self.assertEqual(jobs[0].department, "Product")
        self.assertEqual(jobs[0].posted_date, "2026-08-04T19:30:00Z")
        self.assertEqual(jobs[0].date_provenance, "updated_at")

    def test_lever_has_honest_first_seen_provenance(self) -> None:
        jobs = normalize_lever(
            [
                {
                    "id": "abc",
                    "text": "Designer",
                    "hostedUrl": "https://jobs.lever.co/example/abc",
                    "categories": {"location": "Remote", "team": "Design"},
                }
            ]
        )
        self.assertIsNone(jobs[0].posted_date)
        self.assertEqual(jobs[0].date_provenance, "first_seen")

    def test_ashby_published_date(self) -> None:
        jobs = normalize_ashby(
            {
                "jobs": [
                    {
                        "id": "ash-1",
                        "title": "Engineer",
                        "jobUrl": "https://jobs.ashbyhq.com/example/ash-1",
                        "location": "San Diego",
                        "department": "Engineering",
                        "publishedAt": "2026-08-01T09:00:00Z",
                        "isListed": True,
                    }
                ]
            }
        )
        self.assertEqual(jobs[0].posted_date, "2026-08-01T09:00:00Z")
        self.assertEqual(jobs[0].date_provenance, "published_at")

    def test_workday_relative_date_and_url(self) -> None:
        employer = company(
            "workday",
            ats_slug="exampletenant",
            ats_host="exampletenant.wd1.myworkdayjobs.com",
            workday_site="External",
        )
        jobs = normalize_workday(
            {
                "jobPostings": [
                    {
                        "title": "Analyst",
                        "externalPath": "/job/Los-Angeles/Analyst_REQ-7",
                        "locationsText": "Los Angeles",
                        "postedOn": "Posted 2 Days Ago",
                        "bulletFields": ["REQ-7"],
                    }
                ]
            },
            employer,
            now=datetime(2026, 8, 5, 15, tzinfo=timezone.utc),
        )
        self.assertEqual(jobs[0].posted_date, "2026-08-03T00:00:00Z")
        self.assertEqual(jobs[0].date_provenance, "relative_posted")
        self.assertEqual(
            jobs[0].external_url,
            "https://exampletenant.wd1.myworkdayjobs.com/en-US/External/job/Los-Angeles/Analyst_REQ-7",
        )

    def test_workday_paginates_using_first_page_total(self) -> None:
        employer = company(
            "workday",
            ats_slug="exampletenant",
            ats_host="exampletenant.wd1.myworkdayjobs.com",
            workday_site="External",
        )

        def payload(start: int, count: int, total: int) -> dict:
            return {
                "total": total,
                "jobPostings": [
                    {
                        "title": f"Role {index}",
                        "externalPath": f"/job/Remote/Role-{index}_REQ-{index}",
                        "locationsText": "Remote",
                        "postedOn": "Posted Today",
                        "bulletFields": [f"REQ-{index}"],
                    }
                    for index in range(start, start + count)
                ],
            }

        pages = [payload(0, 20, 45), payload(20, 20, 0), payload(40, 5, 0)]
        with patch("fluo.ats.fetch_json", side_effect=pages) as mocked:
            jobs = fetch_workday_jobs(employer)
        self.assertEqual(len(jobs), 45)
        self.assertEqual([call.kwargs["json_body"]["offset"] for call in mocked.call_args_list], [0, 20, 40])

    def test_provider_urls_are_fixed_to_allowlisted_hosts(self) -> None:
        self.assertEqual(
            build_feed_url(company()),
            "https://boards-api.greenhouse.io/v1/boards/example/jobs?content=true",
        )
        with self.assertRaises(ValueError):
            company(
                "workday",
                ats_slug="safe",
                ats_host="evil.wd1.myworkdayjobs.com.attacker.example",
                workday_site="External",
            )

    def test_invalid_shape_fails_closed(self) -> None:
        with self.assertRaises(FeedError):
            normalize_greenhouse([])


if __name__ == "__main__":
    unittest.main()
