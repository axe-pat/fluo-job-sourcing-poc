from __future__ import annotations

import argparse
import json
from pathlib import Path

from .catalog import load_catalog
from .db import Database
from .refresh import Refresher, save_report_and_snapshot, utc_now
from .server import serve


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATALOG = PROJECT_ROOT / "data" / "companies.json"
DEFAULT_DATABASE = PROJECT_ROOT / "data" / "fluo_jobs.sqlite"
DEFAULT_STATIC = PROJECT_ROOT / "static"
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fluo sponsor-employer public ATS prototype")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    subparsers = parser.add_subparsers(dest="command", required=True)

    refresh = subparsers.add_parser("refresh", help="Fetch every configured public ATS feed once")
    refresh.add_argument("--workers", type=int, default=8)
    refresh.add_argument("--timeout", type=float, default=20)

    serve_parser = subparsers.add_parser("serve", help="Run the local list interface")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8876)
    serve_parser.add_argument("--workers", type=int, default=8)
    serve_parser.add_argument("--timeout", type=float, default=20)
    serve_parser.add_argument("--refresh-hours", type=float, default=24)
    serve_parser.add_argument("--no-auto-refresh", action="store_true")

    subparsers.add_parser("status", help="Print the latest refresh and database summary")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    catalog = load_catalog(args.catalog)
    database = Database(args.database)
    database.initialize()
    database.sync_catalog(catalog, utc_now())

    if args.command == "status":
        print(json.dumps(database.summary(), indent=2))
        return 0

    refresher = Refresher(
        database,
        catalog,
        workers=getattr(args, "workers", 8),
        timeout=getattr(args, "timeout", 20),
    )
    if args.command == "refresh":
        report = refresher.run()
        save_report_and_snapshot(database, report, DEFAULT_DATA_DIR)
        print(json.dumps(report.to_dict(), indent=2))
        return 0 if report.companies_failed == 0 else 2

    if args.host not in {"127.0.0.1", "::1", "localhost"}:
        print("Warning: no authentication is implemented; loopback binding is strongly recommended.")
    serve(
        host=args.host,
        port=args.port,
        database=database,
        refresher=refresher,
        static_dir=DEFAULT_STATIC,
        data_dir=DEFAULT_DATA_DIR,
        refresh_hours=None if args.no_auto_refresh else args.refresh_hours,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
