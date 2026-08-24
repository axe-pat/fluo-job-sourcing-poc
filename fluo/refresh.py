from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .ats import FeedError, fetch_company_jobs
from .catalog import Catalog, Company
from .db import Database


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class SourceResult:
    company: str
    status: str
    jobs_seen: int
    jobs_new: int
    elapsed_ms: int
    error: str | None = None


@dataclass(frozen=True)
class RefreshReport:
    run_id: int
    started_at: str
    completed_at: str
    companies_total: int
    companies_succeeded: int
    companies_failed: int
    jobs_seen: int
    jobs_new: int
    sources: tuple[SourceResult, ...]

    def to_dict(self) -> dict:
        result = asdict(self)
        result["sources"] = [asdict(source) for source in self.sources]
        return result


class Refresher:
    def __init__(
        self,
        database: Database,
        catalog: Catalog,
        *,
        workers: int = 8,
        timeout: float = 20,
        fetcher: Callable[..., list] = fetch_company_jobs,
    ):
        self.database = database
        self.catalog = catalog
        self.workers = max(1, min(workers, 12))
        self.timeout = timeout
        self.fetcher = fetcher
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return self._lock.locked()

    def _fetch_one(self, company: Company, seen_at: str) -> SourceResult:
        started = time.perf_counter()
        try:
            jobs = self.fetcher(company, timeout=self.timeout)
            seen, new = self.database.store_company_jobs(company, jobs, seen_at)
            return SourceResult(company.name, "ok", seen, new, int((time.perf_counter() - started) * 1000))
        except Exception as exc:
            error = str(exc)
            if not isinstance(exc, FeedError):
                error = f"Unexpected feed error: {error}"
            return SourceResult(company.name, "error", 0, 0, int((time.perf_counter() - started) * 1000), error[:500])

    def run(self) -> RefreshReport:
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("A refresh is already running")
        try:
            started_at = utc_now()
            self.database.initialize()
            self.database.sync_catalog(self.catalog, started_at)
            run_id = self.database.begin_run(started_at, len(self.catalog.companies))
            results: list[SourceResult] = []
            with ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="fluo-feed") as pool:
                futures = {
                    pool.submit(self._fetch_one, company, started_at): company
                    for company in self.catalog.companies
                }
                for future in as_completed(futures):
                    result = future.result()
                    results.append(result)
                    self.database.record_source(
                        run_id,
                        result.company,
                        status=result.status,
                        jobs_seen=result.jobs_seen,
                        jobs_new=result.jobs_new,
                        elapsed_ms=result.elapsed_ms,
                        fetched_at=utc_now(),
                        error=result.error,
                    )
            results.sort(key=lambda item: item.company.casefold())
            succeeded = sum(result.status == "ok" for result in results)
            failed = len(results) - succeeded
            jobs_seen = sum(result.jobs_seen for result in results)
            jobs_new = sum(result.jobs_new for result in results)
            completed_at = utc_now()
            self.database.finish_run(
                run_id,
                completed_at=completed_at,
                succeeded=succeeded,
                failed=failed,
                jobs_seen=jobs_seen,
                jobs_new=jobs_new,
            )
            return RefreshReport(
                run_id=run_id,
                started_at=started_at,
                completed_at=completed_at,
                companies_total=len(results),
                companies_succeeded=succeeded,
                companies_failed=failed,
                jobs_seen=jobs_seen,
                jobs_new=jobs_new,
                sources=tuple(results),
            )
        finally:
            self._lock.release()


def save_report_and_snapshot(database: Database, report: RefreshReport, data_dir: str | Path) -> None:
    output = Path(data_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "refresh_report.json").write_text(
        json.dumps(report.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "jobs_snapshot.json").write_text(
        json.dumps(database.export_snapshot(), indent=2) + "\n",
        encoding="utf-8",
    )
