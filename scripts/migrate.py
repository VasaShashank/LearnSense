"""Apply or inspect LearnSense PostgreSQL migrations.

    python scripts/migrate.py status --dsn-env DATABASE_URL
    python scripts/migrate.py apply  --dsn-env DATABASE_URL

The connection string is read from the environment variable named by --dsn-env.
This tool never reads .env files and never prints credentials. Point it only at
the database you intend to change.

Exit codes: 0 up to date / applied, 1 pending migrations (status), 2 error.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.db.migrations import (  # noqa: E402
    MIGRATIONS_DIR,
    MigrationError,
    apply_migrations,
    discover_migrations,
    ensure_session_connection,
    migration_connection_problem,
    migration_status,
)


def describe_target(dsn: str) -> str:
    """Database and host only; never user or password."""
    parts = urlsplit(dsn)
    database = parts.path.lstrip("/") or "(default)"
    return f"database '{database}' on {parts.hostname or 'localhost'}:{parts.port or 5432}"


async def _connect(dsn: str):
    import asyncpg

    from backend.db.pg_connection import _normalize_database_url

    kwargs = {}
    ssl_mode = os.getenv("PG_SSLMODE", "").strip()
    if ssl_mode:
        kwargs["ssl"] = ssl_mode
    return await asyncpg.connect(dsn=_normalize_database_url(dsn), **kwargs)


async def _run(command: str, dsn: str, directory: Path) -> int:
    discover_migrations(directory)  # fail fast on a bad sequence before connecting
    conn = await _connect(dsn)
    try:
        await ensure_session_connection(conn)
        if command == "status":
            status = await migration_status(conn, directory)
            print(f"applied: {', '.join(status['applied']) or 'none'}")
            print(f"pending: {', '.join(status['pending']) or 'none'}")
            if status["unverified_checksums"]:
                print(f"unverified checksums: {', '.join(status['unverified_checksums'])}")
            for problem in status["problems"]:
                print(f"PROBLEM: {problem}", file=sys.stderr)
            if status["problems"]:
                return 2
            return 1 if status["pending"] else 0
        backfilled: list = []
        applied = await apply_migrations(conn, directory, backfilled=backfilled)
        print(f"applied now: {', '.join(applied) or 'none (already up to date)'}")
        if backfilled:
            print(
                "recorded checksums for previously unverified versions: "
                + ", ".join(backfilled)
                + " (taken from the current files; review them if those files may have changed)"
            )
        return 0
    finally:
        await conn.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["status", "apply"])
    parser.add_argument("--dsn-env", required=True, help="Name of the environment variable holding the DSN")
    parser.add_argument("--migrations-dir", default=str(MIGRATIONS_DIR))
    args = parser.parse_args(argv)

    dsn = os.environ.get(args.dsn_env, "").strip()
    if not dsn:
        print(f"ERROR: environment variable {args.dsn_env} is not set or empty.", file=sys.stderr)
        return 2
    print(f"target: {describe_target(dsn)}")
    problem = migration_connection_problem(dsn)
    if problem:
        print(f"ERROR: {problem}", file=sys.stderr)
        return 2
    try:
        return asyncio.run(_run(args.command, dsn, Path(args.migrations_dir)))
    except MigrationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # connection failures etc.; message only, never the DSN
        print(f"ERROR: {type(exc).__name__}: could not complete '{args.command}'.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
