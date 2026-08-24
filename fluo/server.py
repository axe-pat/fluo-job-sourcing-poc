from __future__ import annotations

import json
import mimetypes
import threading
import time
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .db import Database
from .refresh import Refresher, save_report_and_snapshot


class FluoHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address, handler, *, database: Database, refresher: Refresher, static_dir: Path, data_dir: Path):
        super().__init__(server_address, handler)
        self.database = database
        self.refresher = refresher
        self.static_dir = static_dir.resolve()
        self.data_dir = data_dir


class FluoHandler(BaseHTTPRequestHandler):
    server: FluoHTTPServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {self.client_address[0]} {format % args}")

    def _json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _first(params: dict[str, list[str]], key: str, fallback: str = "") -> str:
        return params.get(key, [fallback])[0].strip()

    def _api_jobs(self, params: dict[str, list[str]]) -> None:
        try:
            min_rate_raw = self._first(params, "min_approval_rate", "0")
            min_rate = float(min_rate_raw) if min_rate_raw else 0
            if min_rate > 1:
                min_rate /= 100
            min_rate = min(max(min_rate, 0), 1)
            age_raw = self._first(params, "age_days")
            age_days = int(age_raw) if age_raw else None
            if age_days is not None:
                age_days = min(max(age_days, 1), 3650)
            limit = min(max(int(self._first(params, "limit", "100")), 1), 250)
            offset = max(int(self._first(params, "offset", "0")), 0)
        except ValueError:
            self._json({"error": "Invalid numeric filter"}, HTTPStatus.BAD_REQUEST)
            return
        result = self.server.database.query_jobs(
            search=self._first(params, "q")[:120],
            company=self._first(params, "company")[:160],
            min_approval_rate=min_rate,
            age_days=age_days,
            sort=self._first(params, "sort", "recent"),
            limit=limit,
            offset=offset,
        )
        self._json(result)

    def _serve_static(self, request_path: str) -> None:
        relative = "index.html" if request_path in {"", "/"} else request_path.lstrip("/")
        candidate = (self.server.static_dir / relative).resolve()
        try:
            candidate.relative_to(self.server.static_dir)
        except ValueError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not candidate.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = candidate.read_bytes()
        mime_type, _ = mimetypes.guess_type(candidate.name)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{mime_type or 'application/octet-stream'}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query, keep_blank_values=False)
        if parsed.path == "/api/health":
            self._json({"status": "ok", "refresh_running": self.server.refresher.is_running})
        elif parsed.path == "/api/summary":
            self._json(self.server.database.summary())
        elif parsed.path == "/api/companies":
            self._json({"companies": self.server.database.company_rows()})
        elif parsed.path == "/api/jobs":
            self._api_jobs(params)
        elif parsed.path == "/api/runs/latest":
            self._json({"run": self.server.database.latest_run()})
        else:
            self._serve_static(parsed.path)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/api/refresh":
            self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        if self.client_address[0] not in {"127.0.0.1", "::1"}:
            self._json({"error": "Manual refresh is loopback-only"}, HTTPStatus.FORBIDDEN)
            return
        if self.server.refresher.is_running:
            self._json({"status": "already_running"}, HTTPStatus.CONFLICT)
            return

        def refresh_in_background() -> None:
            try:
                report = self.server.refresher.run()
                save_report_and_snapshot(self.server.database, report, self.server.data_dir)
            except Exception as exc:
                print(f"Refresh failed: {exc}")

        threading.Thread(target=refresh_in_background, name="fluo-manual-refresh", daemon=True).start()
        self._json({"status": "started"}, HTTPStatus.ACCEPTED)


def _scheduler_loop(refresher: Refresher, database: Database, data_dir: Path, refresh_hours: float) -> None:
    interval = max(refresh_hours, 0.25) * 3600
    while True:
        try:
            report = refresher.run()
            save_report_and_snapshot(database, report, data_dir)
            print(
                f"Refresh #{report.run_id}: {report.companies_succeeded}/{report.companies_total} feeds, "
                f"{report.jobs_seen} jobs, {report.jobs_new} new"
            )
        except RuntimeError as exc:
            print(f"Refresh skipped: {exc}")
        except Exception as exc:
            print(f"Scheduled refresh failed: {exc}")
        time.sleep(interval)


def serve(
    *,
    host: str,
    port: int,
    database: Database,
    refresher: Refresher,
    static_dir: str | Path,
    data_dir: str | Path,
    refresh_hours: float | None = 24,
) -> None:
    database.initialize()
    from .refresh import utc_now

    database.sync_catalog(refresher.catalog, utc_now())
    data_path = Path(data_dir)
    if refresh_hours is not None:
        threading.Thread(
            target=_scheduler_loop,
            args=(refresher, database, data_path, refresh_hours),
            name="fluo-scheduler",
            daemon=True,
        ).start()
    httpd = FluoHTTPServer(
        (host, port),
        FluoHandler,
        database=database,
        refresher=refresher,
        static_dir=Path(static_dir),
        data_dir=data_path,
    )
    print(f"Fluo Job Sourcing running at http://{host}:{port}")
    print(f"Refresh cadence: {'manual only' if refresh_hours is None else f'every {refresh_hours:g} hours'}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Fluo Job Sourcing")
    finally:
        httpd.server_close()

