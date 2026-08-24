from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fluo.catalog import load_catalog


class CatalogTests(unittest.TestCase):
    def test_duplicate_feed_is_rejected(self) -> None:
        company = {
            "name": "One",
            "ats_type": "greenhouse",
            "ats_slug": "same",
            "approval_rate": 1,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(
                json.dumps({"companies": [company, {**company, "name": "Two"}]}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate ATS feeds"):
                load_catalog(path)

    def test_checked_in_catalog_is_valid_and_has_31_companies(self) -> None:
        catalog = load_catalog(Path(__file__).parents[1] / "data" / "companies.json")
        self.assertEqual(len(catalog.companies), 31)
        self.assertEqual({company.ats_type for company in catalog.companies}, {"greenhouse", "lever", "ashby", "workday"})


if __name__ == "__main__":
    unittest.main()
