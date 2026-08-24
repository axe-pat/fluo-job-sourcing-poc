from __future__ import annotations

import hashlib
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .catalog import Company


MAX_RESPONSE_BYTES = 25 * 1024 * 1024
USER_AGENT = "FluoJobSourcingPrototype/0.1 (+public ATS API research)"
ALLOWED_API_HOSTS = {
    "boards-api.greenhouse.io",
    "api.lever.co",
    "api.eu.lever.co",
    "api.ashbyhq.com",
}
WORKDAY_PAGE_SIZE = 20
MAX_WORKDAY_JOBS = 5_000
WORKDAY_HOST_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*\.wd\d+\.myworkdayjobs\.com$")


@dataclass(frozen=True)
class NormalizedJob:
    external_id: str
    title: str
    location: str
    department: str
    external_url: str
    posted_date: str | None
    date_provenance: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FeedError(RuntimeError):
    pass


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        host = (urllib.parse.urlparse(newurl).hostname or "").lower()
        if not _is_allowed_api_host(host):
            raise FeedError(f"Blocked redirect to non-ATS host: {host or 'missing host'}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def build_feed_url(company: Company) -> str:
    slug = urllib.parse.quote(company.ats_slug, safe="._-")
    if company.ats_type == "greenhouse":
        return f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    if company.ats_type == "lever":
        host = "api.eu.lever.co" if company.ats_region == "eu" else "api.lever.co"
        return f"https://{host}/v0/postings/{slug}?mode=json"
    if company.ats_type == "ashby":
        return f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    if company.ats_type == "workday":
        tenant = urllib.parse.quote(company.ats_slug, safe="._-")
        site = urllib.parse.quote(company.workday_site, safe="._-")
        return f"https://{company.ats_host}/wday/cxs/{tenant}/{site}/jobs"
    raise ValueError(f"Unsupported ATS type: {company.ats_type}")


def _is_allowed_api_host(host: str) -> bool:
    normalized = host.casefold().rstrip(".")
    return normalized in ALLOWED_API_HOSTS or bool(WORKDAY_HOST_PATTERN.fullmatch(normalized))


def _read_limited(response) -> bytes:  # type: ignore[no-untyped-def]
    header = response.headers.get("Content-Length")
    if header:
        try:
            if int(header) > MAX_RESPONSE_BYTES:
                raise FeedError(f"ATS response exceeds {MAX_RESPONSE_BYTES} bytes")
        except ValueError:
            pass
    body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise FeedError(f"ATS response exceeds {MAX_RESPONSE_BYTES} bytes")
    return body


def fetch_json(
    url: str,
    *,
    timeout: float = 20,
    attempts: int = 3,
    opener: urllib.request.OpenerDirector | None = None,
    json_body: dict[str, Any] | None = None,
) -> Any:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not _is_allowed_api_host((parsed.hostname or "").lower()):
        raise FeedError(f"Blocked non-allowlisted ATS URL: {url}")
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    data = None
    if json_body is not None:
        data = json.dumps(json_body, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    safe_opener = opener or urllib.request.build_opener(SafeRedirectHandler())
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with safe_opener.open(request, timeout=timeout) as response:
                content_type = response.headers.get("Content-Type", "").lower()
                if "json" not in content_type and "javascript" not in content_type:
                    raise FeedError(f"ATS returned non-JSON content type: {content_type or 'missing'}")
                return json.loads(_read_limited(response).decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 500, 502, 503, 504} or attempt == attempts - 1:
                break
        except (urllib.error.URLError, TimeoutError, socket.timeout, json.JSONDecodeError, FeedError) as exc:
            last_error = exc
            if attempt == attempts - 1:
                break
        time.sleep(0.35 * (2**attempt))
    detail = getattr(last_error, "reason", None) or str(last_error) or "unknown error"
    raise FeedError(f"Could not fetch public ATS feed: {detail}") from last_error


def _clean(value: Any, fallback: str = "Not specified") -> str:
    text = " ".join(str(value or "").split())
    return text or fallback


def _iso_or_none(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_greenhouse(payload: Any) -> list[NormalizedJob]:
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise FeedError("Unexpected Greenhouse response shape")
    jobs: list[NormalizedJob] = []
    for raw in payload["jobs"]:
        if not isinstance(raw, dict) or not raw.get("id") or not raw.get("title"):
            continue
        departments = raw.get("departments") or []
        department = departments[0].get("name") if departments and isinstance(departments[0], dict) else None
        location = raw.get("location") if isinstance(raw.get("location"), dict) else {}
        jobs.append(
            NormalizedJob(
                external_id=str(raw["id"]),
                title=_clean(raw.get("title")),
                location=_clean(location.get("name")),
                department=_clean(department),
                external_url=_clean(raw.get("absolute_url"), ""),
                posted_date=_iso_or_none(raw.get("updated_at")),
                date_provenance="updated_at",
            )
        )
    return [job for job in jobs if job.external_url]


def normalize_lever(payload: Any) -> list[NormalizedJob]:
    if not isinstance(payload, list):
        raise FeedError("Unexpected Lever response shape")
    jobs: list[NormalizedJob] = []
    for raw in payload:
        if not isinstance(raw, dict) or not raw.get("id") or not raw.get("text"):
            continue
        categories = raw.get("categories") if isinstance(raw.get("categories"), dict) else {}
        department = categories.get("department") or categories.get("team")
        jobs.append(
            NormalizedJob(
                external_id=str(raw["id"]),
                title=_clean(raw.get("text")),
                location=_clean(categories.get("location")),
                department=_clean(department),
                external_url=_clean(raw.get("hostedUrl") or raw.get("applyUrl"), ""),
                posted_date=None,
                date_provenance="first_seen",
            )
        )
    return [job for job in jobs if job.external_url]


def _ashby_external_id(raw: dict[str, Any]) -> str:
    for key in ("id", "jobPostingId"):
        if raw.get(key):
            return str(raw[key])
    url = str(raw.get("jobUrl") or raw.get("applyUrl") or "")
    path_tail = urllib.parse.urlparse(url).path.rstrip("/").split("/")[-1]
    if path_tail:
        return path_tail
    return hashlib.sha256(json.dumps(raw, sort_keys=True).encode("utf-8")).hexdigest()[:24]


def normalize_ashby(payload: Any) -> list[NormalizedJob]:
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise FeedError("Unexpected Ashby response shape")
    jobs: list[NormalizedJob] = []
    for raw in payload["jobs"]:
        if not isinstance(raw, dict) or not raw.get("title") or raw.get("isListed") is False:
            continue
        department = raw.get("department") or raw.get("team")
        jobs.append(
            NormalizedJob(
                external_id=_ashby_external_id(raw),
                title=_clean(raw.get("title")),
                location=_clean(raw.get("location")),
                department=_clean(department),
                external_url=_clean(raw.get("jobUrl") or raw.get("applyUrl"), ""),
                posted_date=_iso_or_none(raw.get("publishedAt")),
                date_provenance="published_at" if raw.get("publishedAt") else "first_seen",
            )
        )
    return [job for job in jobs if job.external_url]


def _workday_posted_date(value: Any, *, now: datetime | None = None) -> str | None:
    text = _clean(value, "")
    if not text:
        return None
    anchor = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    days: int | None = None
    if text.casefold() == "posted today":
        days = 0
    elif text.casefold() == "posted yesterday":
        days = 1
    else:
        match = re.fullmatch(r"Posted\s+(\d+)\+?\s+Days?\s+Ago", text, flags=re.IGNORECASE)
        if match:
            days = int(match.group(1))
    if days is None:
        return None
    posted = (anchor - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    return posted.isoformat().replace("+00:00", "Z")


def normalize_workday(payload: Any, company: Company, *, now: datetime | None = None) -> list[NormalizedJob]:
    if not isinstance(payload, dict) or not isinstance(payload.get("jobPostings"), list):
        raise FeedError("Unexpected Workday response shape")
    jobs: list[NormalizedJob] = []
    for raw in payload["jobPostings"]:
        if not isinstance(raw, dict) or not raw.get("title") or not raw.get("externalPath"):
            continue
        external_path = str(raw["externalPath"])
        if not external_path.startswith("/job/"):
            continue
        bullets = raw.get("bulletFields") if isinstance(raw.get("bulletFields"), list) else []
        external_id = _clean(bullets[0], "") if bullets else ""
        if not external_id:
            external_id = external_path.rstrip("/").split("_")[-1]
        site = urllib.parse.quote(company.workday_site, safe="._-")
        posted_date = _workday_posted_date(raw.get("postedOn"), now=now)
        jobs.append(
            NormalizedJob(
                external_id=external_id,
                title=_clean(raw.get("title")),
                location=_clean(raw.get("locationsText")),
                department="Not specified",
                external_url=f"https://{company.ats_host}/en-US/{site}{external_path}",
                posted_date=posted_date,
                date_provenance="relative_posted" if posted_date else "first_seen",
            )
        )
    return jobs


def fetch_workday_jobs(company: Company, *, timeout: float = 20) -> list[NormalizedJob]:
    url = build_feed_url(company)
    jobs: list[NormalizedJob] = []
    offset = 0
    expected_total: int | None = None
    fetched_at = datetime.now(timezone.utc)
    while offset < MAX_WORKDAY_JOBS:
        payload = fetch_json(
            url,
            timeout=timeout,
            json_body={"appliedFacets": {}, "limit": WORKDAY_PAGE_SIZE, "offset": offset, "searchText": ""},
        )
        page = normalize_workday(payload, company, now=fetched_at)
        jobs.extend(page)
        total = payload.get("total") if isinstance(payload, dict) else None
        if expected_total is None and isinstance(total, int):
            expected_total = total
        returned = len(payload.get("jobPostings", [])) if isinstance(payload, dict) else 0
        if expected_total is not None and expected_total > MAX_WORKDAY_JOBS:
            raise FeedError(f"Workday feed exceeds the {MAX_WORKDAY_JOBS}-job safety cap")
        offset += returned
        if returned == 0 or (expected_total is not None and offset >= expected_total):
            break
    return jobs


NORMALIZERS: dict[str, Callable[[Any], list[NormalizedJob]]] = {
    "greenhouse": normalize_greenhouse,
    "lever": normalize_lever,
    "ashby": normalize_ashby,
}


def fetch_company_jobs(company: Company, *, timeout: float = 20) -> list[NormalizedJob]:
    if company.ats_type == "workday":
        return fetch_workday_jobs(company, timeout=timeout)
    payload = fetch_json(build_feed_url(company), timeout=timeout)
    return NORMALIZERS[company.ats_type](payload)
