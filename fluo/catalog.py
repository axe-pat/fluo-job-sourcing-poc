from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


ATS_TYPES = {"greenhouse", "lever", "ashby", "workday"}
SLUG_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
WORKDAY_HOST_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*\.wd\d+\.myworkdayjobs\.com$")


@dataclass(frozen=True)
class Company:
    name: str
    legal_name: str
    ats_type: str
    ats_slug: str
    approval_count: int
    approval_rate: float
    certified_positions: int
    industry: str
    hq_location: str
    socal_worksites: tuple[str, ...]
    feed_url: str
    feed_verified_at: str
    lca_rank: int | None = None
    ats_region: str = "global"
    ats_host: str = ""
    workday_site: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Company":
        ats_type = str(raw.get("ats_type", "")).strip().lower()
        ats_slug = str(raw.get("ats_slug", "")).strip()
        if ats_type not in ATS_TYPES:
            raise ValueError(f"Unsupported ATS type for {raw.get('name')!r}: {ats_type!r}")
        if not SLUG_PATTERN.fullmatch(ats_slug):
            raise ValueError(f"Unsafe or invalid ATS slug for {raw.get('name')!r}: {ats_slug!r}")
        rate = float(raw.get("approval_rate", 0))
        if not 0 <= rate <= 1:
            raise ValueError(f"Approval rate must be between 0 and 1 for {raw.get('name')!r}")
        region = str(raw.get("ats_region", "global")).strip().lower()
        if ats_type != "lever" and region != "global":
            raise ValueError(f"ATS region is only supported for Lever: {raw.get('name')!r}")
        if region not in {"global", "eu"}:
            raise ValueError(f"Unsupported Lever region: {region!r}")
        ats_host = str(raw.get("ats_host", "")).strip().lower()
        workday_site = str(raw.get("workday_site", "")).strip()
        if ats_type == "workday":
            if not WORKDAY_HOST_PATTERN.fullmatch(ats_host):
                raise ValueError(f"Unsafe or invalid Workday host for {raw.get('name')!r}: {ats_host!r}")
            if not SLUG_PATTERN.fullmatch(workday_site):
                raise ValueError(f"Unsafe or invalid Workday site for {raw.get('name')!r}: {workday_site!r}")
        elif ats_host or workday_site:
            raise ValueError(f"Workday fields supplied for non-Workday company: {raw.get('name')!r}")
        return cls(
            name=str(raw["name"]).strip(),
            legal_name=str(raw.get("legal_name") or raw["name"]).strip(),
            ats_type=ats_type,
            ats_slug=ats_slug,
            approval_count=int(raw.get("approval_count", 0)),
            approval_rate=rate,
            certified_positions=int(raw.get("certified_positions", 0)),
            industry=str(raw.get("industry", "Unknown")).strip() or "Unknown",
            hq_location=str(raw.get("hq_location", "Unknown")).strip() or "Unknown",
            socal_worksites=tuple(str(item).strip() for item in raw.get("socal_worksites", []) if str(item).strip()),
            feed_url=str(raw.get("feed_url", "")).strip(),
            feed_verified_at=str(raw.get("feed_verified_at", "")).strip(),
            lca_rank=int(raw["lca_rank"]) if raw.get("lca_rank") is not None else None,
            ats_region=region,
            ats_host=ats_host,
            workday_site=workday_site,
        )


@dataclass(frozen=True)
class Catalog:
    companies: tuple[Company, ...]
    source: dict[str, Any]
    decisions: dict[str, Any]


def load_catalog(path: str | Path) -> Catalog:
    catalog_path = Path(path)
    raw = json.loads(catalog_path.read_text(encoding="utf-8"))
    companies = tuple(Company.from_dict(item) for item in raw.get("companies", []))
    if not companies:
        raise ValueError(f"Catalog has no companies: {catalog_path}")
    names = [company.name.casefold() for company in companies]
    if len(names) != len(set(names)):
        raise ValueError("Catalog contains duplicate company names")
    feed_keys = [
        (
            company.ats_type,
            company.ats_region,
            company.ats_host,
            company.workday_site.casefold(),
            company.ats_slug.casefold(),
        )
        for company in companies
    ]
    if len(feed_keys) != len(set(feed_keys)):
        raise ValueError("Catalog contains duplicate ATS feeds")
    return Catalog(
        companies=companies,
        source=dict(raw.get("source", {})),
        decisions=dict(raw.get("prototype_decisions", {})),
    )


def serialize_companies(companies: Iterable[Company]) -> list[dict[str, Any]]:
    return [
        {
            "name": company.name,
            "legal_name": company.legal_name,
            "ats_type": company.ats_type,
            "ats_slug": company.ats_slug,
            "ats_region": company.ats_region,
            "approval_count": company.approval_count,
            "approval_rate": company.approval_rate,
            "certified_positions": company.certified_positions,
            "industry": company.industry,
            "hq_location": company.hq_location,
            "socal_worksites": list(company.socal_worksites),
            "feed_url": company.feed_url,
            "feed_verified_at": company.feed_verified_at,
            "lca_rank": company.lca_rank,
            "ats_host": company.ats_host,
            "workday_site": company.workday_site,
        }
        for company in companies
    ]
