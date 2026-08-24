from __future__ import annotations

import json
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

from .ats import NormalizedJob
from .catalog import Catalog, Company


SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    legal_name TEXT NOT NULL,
    ats_type TEXT NOT NULL CHECK (ats_type IN ('greenhouse', 'lever', 'ashby', 'workday')),
    ats_slug TEXT NOT NULL,
    ats_region TEXT NOT NULL DEFAULT 'global',
    ats_host TEXT NOT NULL DEFAULT '',
    workday_site TEXT NOT NULL DEFAULT '',
    approval_count INTEGER NOT NULL DEFAULT 0,
    approval_rate REAL NOT NULL DEFAULT 0,
    certified_positions INTEGER NOT NULL DEFAULT 0,
    industry TEXT NOT NULL,
    hq_location TEXT NOT NULL,
    socal_worksites_json TEXT NOT NULL DEFAULT '[]',
    feed_url TEXT NOT NULL,
    feed_verified_at TEXT NOT NULL,
    lca_rank INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (ats_type, ats_region, ats_slug, ats_host, workday_site)
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT NOT NULL,
    department TEXT NOT NULL,
    external_url TEXT NOT NULL,
    posted_date TEXT,
    date_provenance TEXT NOT NULL CHECK (date_provenance IN ('published_at', 'updated_at', 'relative_posted', 'first_seen')),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    UNIQUE (company_id, external_id)
);

CREATE INDEX IF NOT EXISTS idx_jobs_active_recent ON jobs(is_active, posted_date DESC, first_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company_id, is_active);

CREATE TABLE IF NOT EXISTS fetch_runs (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'partial', 'failed')),
    companies_total INTEGER NOT NULL,
    companies_succeeded INTEGER NOT NULL DEFAULT 0,
    companies_failed INTEGER NOT NULL DEFAULT 0,
    jobs_seen INTEGER NOT NULL DEFAULT 0,
    jobs_new INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS fetch_sources (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES fetch_runs(id) ON DELETE CASCADE,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('ok', 'error')),
    jobs_seen INTEGER NOT NULL DEFAULT 0,
    jobs_new INTEGER NOT NULL DEFAULT 0,
    elapsed_ms INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    fetched_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with closing(self.connect()) as connection:
            connection.executescript(SCHEMA)
            connection.commit()

    def sync_catalog(self, catalog: Catalog, now: str) -> None:
        with self.transaction() as connection:
            for company in catalog.companies:
                connection.execute(
                    """
                    INSERT INTO companies (
                        name, legal_name, ats_type, ats_slug, ats_region, ats_host, workday_site,
                        approval_count, approval_rate, certified_positions,
                        industry, hq_location, socal_worksites_json, feed_url,
                        feed_verified_at, lca_rank, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET
                        legal_name=excluded.legal_name,
                        ats_type=excluded.ats_type,
                        ats_slug=excluded.ats_slug,
                        ats_region=excluded.ats_region,
                        ats_host=excluded.ats_host,
                        workday_site=excluded.workday_site,
                        approval_count=excluded.approval_count,
                        approval_rate=excluded.approval_rate,
                        certified_positions=excluded.certified_positions,
                        industry=excluded.industry,
                        hq_location=excluded.hq_location,
                        socal_worksites_json=excluded.socal_worksites_json,
                        feed_url=excluded.feed_url,
                        feed_verified_at=excluded.feed_verified_at,
                        lca_rank=excluded.lca_rank,
                        updated_at=excluded.updated_at
                    """,
                    (
                        company.name,
                        company.legal_name,
                        company.ats_type,
                        company.ats_slug,
                        company.ats_region,
                        company.ats_host,
                        company.workday_site,
                        company.approval_count,
                        company.approval_rate,
                        company.certified_positions,
                        company.industry,
                        company.hq_location,
                        json.dumps(company.socal_worksites),
                        company.feed_url,
                        company.feed_verified_at,
                        company.lca_rank,
                        now,
                        now,
                    ),
                )

    def company_id(self, name: str) -> int:
        with closing(self.connect()) as connection:
            row = connection.execute("SELECT id FROM companies WHERE name = ?", (name,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown company: {name}")
        return int(row["id"])

    def begin_run(self, started_at: str, companies_total: int) -> int:
        with self.transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO fetch_runs (started_at, status, companies_total) VALUES (?, 'running', ?)",
                (started_at, companies_total),
            )
            return int(cursor.lastrowid)

    @staticmethod
    def stable_job_id(company: Company, external_id: str) -> str:
        import hashlib

        raw = f"{company.name.casefold()}\x1f{external_id}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:32]

    def store_company_jobs(
        self,
        company: Company,
        jobs: Sequence[NormalizedJob],
        seen_at: str,
    ) -> tuple[int, int]:
        company_id = self.company_id(company.name)
        new_count = 0
        external_ids = [job.external_id for job in jobs]
        with self.transaction() as connection:
            for job in jobs:
                existed = connection.execute(
                    "SELECT 1 FROM jobs WHERE company_id = ? AND external_id = ?",
                    (company_id, job.external_id),
                ).fetchone()
                if existed is None:
                    new_count += 1
                connection.execute(
                    """
                    INSERT INTO jobs (
                        id, company_id, external_id, title, location, department,
                        external_url, posted_date, date_provenance,
                        first_seen_at, last_seen_at, is_active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    ON CONFLICT(company_id, external_id) DO UPDATE SET
                        title=excluded.title,
                        location=excluded.location,
                        department=excluded.department,
                        external_url=excluded.external_url,
                        posted_date=excluded.posted_date,
                        date_provenance=excluded.date_provenance,
                        last_seen_at=excluded.last_seen_at,
                        is_active=1
                    """,
                    (
                        self.stable_job_id(company, job.external_id),
                        company_id,
                        job.external_id,
                        job.title,
                        job.location,
                        job.department,
                        job.external_url,
                        job.posted_date,
                        job.date_provenance,
                        seen_at,
                        seen_at,
                    ),
                )
            if external_ids:
                placeholders = ",".join("?" for _ in external_ids)
                connection.execute(
                    f"UPDATE jobs SET is_active = 0 WHERE company_id = ? AND external_id NOT IN ({placeholders})",
                    (company_id, *external_ids),
                )
            else:
                connection.execute("UPDATE jobs SET is_active = 0 WHERE company_id = ?", (company_id,))
        return len(jobs), new_count

    def record_source(
        self,
        run_id: int,
        company_name: str,
        *,
        status: str,
        jobs_seen: int,
        jobs_new: int,
        elapsed_ms: int,
        fetched_at: str,
        error: str | None = None,
    ) -> None:
        company_id = self.company_id(company_name)
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO fetch_sources (
                    run_id, company_id, status, jobs_seen, jobs_new,
                    elapsed_ms, error, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, company_id, status, jobs_seen, jobs_new, elapsed_ms, error, fetched_at),
            )

    def finish_run(
        self,
        run_id: int,
        *,
        completed_at: str,
        succeeded: int,
        failed: int,
        jobs_seen: int,
        jobs_new: int,
    ) -> None:
        status = "completed" if failed == 0 else ("partial" if succeeded else "failed")
        with self.transaction() as connection:
            connection.execute(
                """
                UPDATE fetch_runs SET
                    completed_at=?, status=?, companies_succeeded=?,
                    companies_failed=?, jobs_seen=?, jobs_new=?
                WHERE id=?
                """,
                (completed_at, status, succeeded, failed, jobs_seen, jobs_new, run_id),
            )

    def latest_run(self) -> dict[str, Any] | None:
        with closing(self.connect()) as connection:
            row = connection.execute("SELECT * FROM fetch_runs ORDER BY id DESC LIMIT 1").fetchone()
            if row is None:
                return None
            result = dict(row)
            errors = connection.execute(
                """
                SELECT c.name AS company, s.error
                FROM fetch_sources s
                JOIN companies c ON c.id = s.company_id
                WHERE s.run_id = ? AND s.status = 'error'
                ORDER BY c.name
                """,
                (row["id"],),
            ).fetchall()
            result["errors"] = [dict(item) for item in errors]
            return result

    def company_rows(self) -> list[dict[str, Any]]:
        with closing(self.connect()) as connection:
            rows = connection.execute(
                """
                SELECT c.*,
                       COUNT(CASE WHEN j.is_active = 1 THEN 1 END) AS active_job_count
                FROM companies c
                LEFT JOIN jobs j ON j.company_id = c.id
                GROUP BY c.id
                ORDER BY c.name COLLATE NOCASE
                """
            ).fetchall()
        return [self._company_dict(row) for row in rows]

    @staticmethod
    def _company_dict(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["socal_worksites"] = json.loads(result.pop("socal_worksites_json", "[]"))
        result["approval_rate_percent"] = round(float(result["approval_rate"]) * 100, 1)
        return result

    def summary(self) -> dict[str, Any]:
        with closing(self.connect()) as connection:
            row = connection.execute(
                """
                SELECT
                    COUNT(CASE WHEN is_active = 1 THEN 1 END) AS active_jobs,
                    COUNT(CASE WHEN is_active = 1 AND datetime(first_seen_at) >= datetime('now', '-1 day') THEN 1 END) AS new_24h,
                    COUNT(DISTINCT CASE WHEN is_active = 1 THEN company_id END) AS companies_with_jobs
                FROM jobs
                """
            ).fetchone()
            company_count = connection.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
        return {**dict(row), "verified_companies": company_count, "latest_run": self.latest_run()}

    def query_jobs(
        self,
        *,
        search: str = "",
        company: str = "",
        min_approval_rate: float = 0,
        age_days: int | None = None,
        sort: str = "recent",
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        clauses = ["j.is_active = 1"]
        params: list[Any] = []
        if search:
            token = f"%{search}%"
            clauses.append("(j.title LIKE ? OR j.department LIKE ? OR j.location LIKE ? OR c.name LIKE ?)")
            params.extend([token, token, token, token])
        if company:
            clauses.append("c.name = ?")
            params.append(company)
        if min_approval_rate:
            clauses.append("c.approval_rate >= ?")
            params.append(min_approval_rate)
        if age_days is not None:
            clauses.append("datetime(COALESCE(j.posted_date, j.first_seen_at)) >= datetime('now', ?)")
            params.append(f"-{age_days} days")
        order_by = {
            "recent": "COALESCE(j.posted_date, j.first_seen_at) DESC, j.first_seen_at DESC",
            "first_seen": "j.first_seen_at DESC, COALESCE(j.posted_date, '') DESC",
            "approval": "c.approval_rate DESC, c.approval_count DESC, COALESCE(j.posted_date, j.first_seen_at) DESC",
            "company": "c.name COLLATE NOCASE, COALESCE(j.posted_date, j.first_seen_at) DESC",
        }.get(sort, "COALESCE(j.posted_date, j.first_seen_at) DESC, j.first_seen_at DESC")
        where = " AND ".join(clauses)
        base = f"FROM jobs j JOIN companies c ON c.id = j.company_id WHERE {where}"
        with closing(self.connect()) as connection:
            total = connection.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]
            rows = connection.execute(
                f"""
                SELECT j.*, c.name AS company, c.ats_type, c.approval_count,
                       c.approval_rate, c.industry, c.hq_location
                {base}
                ORDER BY {order_by}
                LIMIT ? OFFSET ?
                """,
                (*params, limit, offset),
            ).fetchall()
        jobs = []
        for row in rows:
            item = dict(row)
            item["approval_rate_percent"] = round(float(item["approval_rate"]) * 100, 1)
            item["is_active"] = bool(item["is_active"])
            jobs.append(item)
        return {"jobs": jobs, "total": total, "limit": limit, "offset": offset}

    def export_snapshot(self) -> dict[str, Any]:
        return {
            "summary": self.summary(),
            "companies": self.company_rows(),
            **self.query_jobs(limit=10_000),
        }
