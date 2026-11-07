"""Read-only startup verification of the migration history.

The list of required versions and their checksums come from
``backend/db/migrations.py`` (the ``migrations/`` directory), the same source
``scripts/migrate.py`` applies. This module only *reads* ``schema_migrations``; it
never applies, repairs or rewrites anything.

Startup requires every migration on disk to be recorded AND its recorded checksum
to match the file:

* missing    — version not recorded: run ``scripts/migrate.py apply``.
* modified   — recorded checksum differs from the file: an applied migration was
               edited after it ran. Restore the original file (never edit applied
               migrations); add a new migration for further changes.
* unverified — version recorded without a checksum (applied before migration 003
               added the column, or applied manually with psql). Run
               ``scripts/migrate.py apply`` once: it records the current files'
               checksums for those versions and reports which ones it recorded.

Versions recorded in the database but absent on disk (a newer schema than this code)
are tolerated so an older release can run against an additively migrated database.
A recorded version proves the migration script ran, not that the tables are intact.
"""

from __future__ import annotations

from typing import Any, Dict, List

from backend.db.migrations import discover_migrations, recorded_migrations

# version -> repository-relative file, in application order.
REQUIRED_MIGRATIONS: Dict[str, str] = {
    m.version: f"migrations/{m.filename}" for m in discover_migrations()
}
_CHECKSUMS: Dict[str, str] = {m.version: m.checksum for m in discover_migrations()}


class SchemaNotReadyError(RuntimeError):
    """The connected database's migration history does not match this code."""


async def inspect_migrations(pool: Any) -> Dict[str, List[str]]:
    """{"missing": [...], "modified": [...], "unverified": [...]} (read-only)."""
    async with pool.acquire() as conn:
        recorded = await recorded_migrations(conn)
    missing, modified, unverified = [], [], []
    for version in REQUIRED_MIGRATIONS:
        if version not in recorded:
            missing.append(version)
        elif recorded[version] is None:
            unverified.append(version)
        elif recorded[version] != _CHECKSUMS[version]:
            modified.append(version)
    return {"missing": missing, "modified": modified, "unverified": unverified}


async def find_missing_migrations(pool: Any) -> List[str]:
    """Required versions not recorded in ``public.schema_migrations`` (read-only)."""
    return (await inspect_migrations(pool))["missing"]


def has_problems(report: Dict[str, List[str]]) -> bool:
    return any(report[k] for k in ("missing", "modified", "unverified"))


def describe_missing(missing: List[str]) -> str:
    """Actionable message; names files and versions, never connection details."""
    files = "\n".join(f"  {REQUIRED_MIGRATIONS[v]}" for v in missing)
    return (
        "PostgreSQL schema is not ready: migration(s) "
        f"{', '.join(missing)} not recorded in public.schema_migrations:\n"
        f"{files}\n"
        "Apply them against the intended database with:\n"
        "  python scripts/migrate.py apply --dsn-env DATABASE_URL\n"
        "(see migrations/README.md). LearnSense never applies migrations automatically."
    )


def describe_report(report: Dict[str, List[str]]) -> str:
    parts = []
    if report["missing"]:
        parts.append(describe_missing(report["missing"]))
    if report["modified"]:
        parts.append(
            "Migration history does not match the code: recorded checksum differs for "
            f"{', '.join(report['modified'])} "
            f"({', '.join(REQUIRED_MIGRATIONS[v] for v in report['modified'])}). An applied "
            "migration file was changed. Restore the file exactly as applied (never edit an "
            "applied migration; add a new one), or restore a database that matches this code."
        )
    if report["unverified"]:
        parts.append(
            "Migration history cannot be verified: no checksum recorded for "
            f"{', '.join(report['unverified'])} (applied before checksums existed or with psql). "
            "Run once, against the intended database:\n"
            "  python scripts/migrate.py apply --dsn-env DATABASE_URL\n"
            "It records the current files' checksums for those versions and lists them."
        )
    return "\n".join(parts)


async def ensure_required_migrations(pool: Any) -> None:
    """Raise ``SchemaNotReadyError`` unless every migration is recorded with a matching checksum."""
    report = await inspect_migrations(pool)
    if has_problems(report):
        raise SchemaNotReadyError(describe_report(report))
