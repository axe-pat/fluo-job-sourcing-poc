from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fluo.ats import NormalizedJob
from fluo.catalog import Catalog, Company
from fluo.db import Database


def employer() -> Company:
    return Company.from_dict(
        {
            "name": "Example",
            "legal_name": "Example, Inc.",
            "ats_type": "greenhouse",
            "ats_slug": "example",
            "approval_count": 2,
            "approval_rate": 1,
            "certified_positions": 3,
            "industry": "Information",
            "hq_location": "Los Angeles, CA",
            "socal_worksites": ["Los Angeles"],
            "feed_url": "https://boards-api.greenhouse.io/v1/boards/example/jobs",
            "feed_verified_at": "2026-08-05",
        }
    )


class DatabaseTests(unittest.TestCase):
    def test_upsert_preserves_first_seen_and_tracks_active_state(self) -> None:
        company = employer()
        job = NormalizedJob(
            external_id="job-1",
            title="Product Manager",
            location="Los Angeles",
            department="Product",
            external_url="https://job-boards.greenhouse.io/example/jobs/job-1",
            posted_date="2026-08-01T00:00:00Z",
            date_provenance="updated_at",
        )
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "jobs.sqlite")
            database.initialize()
            database.sync_catalog(Catalog((company,), {}, {}), "2026-08-05T00:00:00Z")
            self.assertEqual(database.store_company_jobs(company, [job], "2026-08-05T01:00:00Z"), (1, 1))
            changed = NormalizedJob(**{**job.to_dict(), "title": "Senior Product Manager"})
            self.assertEqual(database.store_company_jobs(company, [changed], "2026-08-05T02:00:00Z"), (1, 0))
            row = database.query_jobs()["jobs"][0]
            self.assertEqual(row["title"], "Senior Product Manager")
            self.assertEqual(row["first_seen_at"], "2026-08-05T01:00:00Z")
            self.assertEqual(row["last_seen_at"], "2026-08-05T02:00:00Z")

            database.store_company_jobs(company, [], "2026-08-05T03:00:00Z")
            self.assertEqual(database.query_jobs()["total"], 0)
            database.store_company_jobs(company, [changed], "2026-08-05T04:00:00Z")
            restored = database.query_jobs()["jobs"][0]
            self.assertEqual(restored["first_seen_at"], "2026-08-05T01:00:00Z")


if __name__ == "__main__":
    unittest.main()
