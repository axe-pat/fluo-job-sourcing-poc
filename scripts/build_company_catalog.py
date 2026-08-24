#!/usr/bin/env python3
"""Build a ranked Southern California H-1B employer catalog from DOL LCA XLSX."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DOL_SOURCE_URL = "https://www.dol.gov/media/LCA_Dislclosure_Data_FY2026_Q2.xlsx"
DOL_CATALOG_URL = "https://www.dol.gov/agencies/eta/foreign-labor/performance"
SOUTHERN_CALIFORNIA_COUNTIES = {
    "IMPERIAL",
    "KERN",
    "LOS ANGELES",
    "ORANGE",
    "RIVERSIDE",
    "SAN BERNARDINO",
    "SAN DIEGO",
    "SAN LUIS OBISPO",
    "SANTA BARBARA",
    "VENTURA",
}
USE_COLUMNS = [
    "CASE_STATUS",
    "VISA_CLASS",
    "TOTAL_WORKER_POSITIONS",
    "EMPLOYER_NAME",
    "EMPLOYER_CITY",
    "EMPLOYER_STATE",
    "EMPLOYER_FEIN",
    "NAICS_CODE",
    "WORKSITE_CITY",
    "WORKSITE_COUNTY",
    "WORKSITE_STATE",
]


NAICS_SECTORS = {
    "11": "Agriculture, forestry, fishing & hunting",
    "21": "Mining, quarrying & oil and gas",
    "22": "Utilities",
    "23": "Construction",
    "31": "Manufacturing",
    "32": "Manufacturing",
    "33": "Manufacturing",
    "42": "Wholesale trade",
    "44": "Retail trade",
    "45": "Retail trade",
    "48": "Transportation & warehousing",
    "49": "Transportation & warehousing",
    "51": "Information",
    "52": "Finance & insurance",
    "53": "Real estate & rental",
    "54": "Professional, scientific & technical services",
    "55": "Management of companies",
    "56": "Administrative & support services",
    "61": "Educational services",
    "62": "Health care & social assistance",
    "71": "Arts, entertainment & recreation",
    "72": "Accommodation & food services",
    "81": "Other services",
    "92": "Public administration",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() == "nan":
        return ""
    return " ".join(text.split())


def normalize_name(value: Any) -> str:
    text = clean_text(value).casefold()
    text = text.replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", "", text)


def normalize_fein(value: Any) -> str:
    return re.sub(r"\D", "", clean_text(value))


def stable_entity_key(fein: Any, employer_name: Any) -> str:
    normalized_fein = normalize_fein(fein)
    raw = f"fein:{normalized_fein}" if normalized_fein else f"name:{normalize_name(employer_name)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def mode(values: Iterable[Any]) -> str:
    cleaned = [clean_text(value) for value in values]
    cleaned = [value for value in cleaned if value]
    if not cleaned:
        return ""
    counts = Counter(cleaned)
    return sorted(counts, key=lambda item: (-counts[item], item.casefold()))[0]


def industry_from_naics(value: Any) -> str:
    digits = re.sub(r"\D", "", clean_text(value))
    return NAICS_SECTORS.get(digits[:2], "Unknown")


def build_catalog(input_path: Path, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        import pandas as pd
    except ImportError as exc:
        raise SystemExit(
            "DOL import requires pandas and openpyxl. Install with: pip install -e '.[dol-import]'"
        ) from exc

    frame = pd.read_excel(input_path, usecols=USE_COLUMNS)
    total_rows = len(frame)
    visa = frame["VISA_CLASS"].fillna("").astype(str).str.upper().str.strip()
    state = frame["WORKSITE_STATE"].fillna("").astype(str).str.upper().str.strip()
    county = frame["WORKSITE_COUNTY"].fillna("").astype(str).str.upper().str.strip()
    scoped = frame[(visa == "H-1B") & (state == "CA") & county.isin(SOUTHERN_CALIFORNIA_COUNTIES)].copy()
    scoped["_entity_key"] = [
        stable_entity_key(fein, name)
        for fein, name in zip(scoped["EMPLOYER_FEIN"], scoped["EMPLOYER_NAME"], strict=False)
    ]
    scoped["_approved"] = scoped["CASE_STATUS"].fillna("").astype(str).str.upper().str.startswith("CERTIFIED")
    scoped["_denied"] = scoped["CASE_STATUS"].fillna("").astype(str).str.upper().str.strip().eq("DENIED")
    scoped["_positions"] = pd.to_numeric(scoped["TOTAL_WORKER_POSITIONS"], errors="coerce").fillna(0)

    records: list[dict[str, Any]] = []
    for _, group in scoped.groupby("_entity_key", sort=False):
        approved = int(group["_approved"].sum())
        denied = int(group["_denied"].sum())
        determined = approved + denied
        aliases = sorted(
            {clean_text(name) for name in group["EMPLOYER_NAME"] if clean_text(name)},
            key=lambda item: (item.casefold(), item),
        )
        legal_name = mode(group["EMPLOYER_NAME"])
        employer_city = mode(group["EMPLOYER_CITY"])
        employer_state = mode(group["EMPLOYER_STATE"])
        naics = mode(group["NAICS_CODE"])
        cities = sorted(
            {clean_text(city) for city in group["WORKSITE_CITY"] if clean_text(city)},
            key=str.casefold,
        )
        certified_positions = int(group.loc[group["_approved"], "_positions"].sum())
        records.append(
            {
                "legal_name": legal_name,
                "aliases": aliases,
                "approval_count": approved,
                "approval_rate": round(approved / determined, 4) if determined else 0.0,
                "case_count": int(len(group)),
                "denied_count": denied,
                "certified_positions": certified_positions,
                "industry": industry_from_naics(naics),
                "naics_code": clean_text(naics),
                "hq_location": ", ".join(part for part in (employer_city, employer_state) if part) or "Unknown",
                "socal_worksites": cities,
            }
        )

    records.sort(
        key=lambda item: (
            -item["approval_count"],
            -item["approval_rate"],
            -item["certified_positions"],
            item["legal_name"].casefold(),
        )
    )
    records = records[:limit]
    for rank, record in enumerate(records, start=1):
        record["rank"] = rank

    manifest = {
        "generated_at": utc_now(),
        "source": {
            "publisher": "U.S. Department of Labor, Office of Foreign Labor Certification",
            "dataset": "LCA Disclosure Data FY2026 Q2",
            "period": "2025-10-01 through 2026-03-31",
            "download_url": DOL_SOURCE_URL,
            "catalog_url": DOL_CATALOG_URL,
            "input_file": input_path.name,
            "input_rows": total_rows,
        },
        "scope": {
            "visa_class": "H-1B",
            "worksite_state": "CA",
            "southern_california_counties": sorted(SOUTHERN_CALIFORNIA_COUNTIES),
            "matched_rows": int(len(scoped)),
            "distinct_employers_before_limit": int(scoped["_entity_key"].nunique()),
            "output_limit": limit,
        },
        "definitions": {
            "approval_count": "Count of LCA cases whose status begins with Certified, including Certified - Withdrawn.",
            "approval_rate": "approval_count divided by approval_count plus Denied; Withdrawn is excluded from the denominator.",
            "certified_positions": "Sum of TOTAL_WORKER_POSITIONS on approved LCA cases.",
            "entity_deduplication": "Rows are grouped by FEIN when present, otherwise normalized employer name. FEIN values are not exported.",
            "hq_location": "Most frequent employer city/state in the disclosure file; this may be a filing address, not corporate headquarters.",
        },
    }
    return records, manifest


def write_outputs(records: list[dict[str, Any]], manifest: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "socal_lca_companies.json"
    csv_path = output_dir / "socal_lca_companies.csv"
    manifest_path = output_dir / "source_manifest.json"
    json_path.write_text(json.dumps({"manifest": manifest, "companies": records}, indent=2) + "\n", encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    fieldnames = [
        "rank",
        "legal_name",
        "approval_count",
        "approval_rate",
        "case_count",
        "denied_count",
        "certified_positions",
        "industry",
        "naics_code",
        "hq_location",
        "socal_worksites",
        "aliases",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            row = dict(record)
            row["approval_rate"] = f"{record['approval_rate']:.4f}"
            row["socal_worksites"] = " | ".join(record["socal_worksites"])
            row["aliases"] = " | ".join(record["aliases"])
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True, help="Official DOL LCA disclosure .xlsx")
    parser.add_argument("--output-dir", type=Path, default=Path("data"))
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()
    if not args.input.is_file():
        raise SystemExit(f"Input workbook not found: {args.input}")
    if not 100 <= args.limit <= 300:
        raise SystemExit("--limit must be between 100 and 300")
    records, manifest = build_catalog(args.input, args.limit)
    write_outputs(records, manifest, args.output_dir)
    print(
        f"Wrote {len(records)} employers to {args.output_dir} "
        f"from {manifest['scope']['matched_rows']} scoped LCA rows."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

