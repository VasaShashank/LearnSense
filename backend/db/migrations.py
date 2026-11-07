"""Single source of truth for PostgreSQL schema migrations.

Migration files live in ``migrations/`` and are named ``NNN_description.sql``.
Versions must be contiguous from ``001``. Each file manages its own transaction
(``BEGIN``/``COMMIT``) and records its version in ``schema_migrations``.

Used by ``scripts/migrate.py`` (operator tool) and by the startup readiness check
(``backend/db/schema_check.py``). The application never applies migrations on
ordinary startup; deployments run ``scripts/migrate.py apply`` as a release step.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
_FILE_PATTERN = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")
# Arbitrary constant: serializes concurrent migration runners on one database.
_ADVISORY_LOCK_KEY = 8_420_017_331


class MigrationError(RuntimeError):
    """The migration sequence or database history is inconsistent, or a migration failed."""


@dataclass(frozen=True)
class Migration:
    version: str
    path: Path
    checksum: str

    @property
    def filename(self) -> str:
        return self.path.name


def discover_migrations(directory: Path = MIGRATIONS_DIR) -> List[Migration]:
    """Return migrations ordered by version; refuse gaps, duplicates and stray names."""
    found: Dict[str, Path] = {}
    for path in sorted(Path(directory).glob("*.sql")):
        match = _FILE_PATTERN.match(path.name)
        if not match:
            raise MigrationError(f"Unrecognized migration filename: {path.name}")
        version = match.group(1)
        if version in found:
            raise MigrationError(f"Duplicate migration version {version}")
        found[version] = path
    versions = sorted(found)
    expected = [f"{i:03d}" for i in range(1, len(versions) + 1)]
    if versions != expected:
        raise MigrationError(
            f"Migration versions must be contiguous from 001; found {', '.join(versions) or 'none'}"
        )
    return [
        Migration(v, found[v], hashlib.sha256(found[v].read_bytes()).hexdigest())
        for v in versions
    ]


def required_versions(directory: Path = MIGRATIONS_DIR) -> List[str]:
    return [m.version for m in discover_migrations(directory)]


async def _has_checksum_column(conn: Any) -> bool:
    return bool(await conn.fetchval(
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'schema_migrations'
          AND column_name = 'checksum'
        """
    ))


async def recorded_migrations(conn: Any) -> Dict[str, Optional[str]]:
    """Map of recorded version -> checksum (None when not recorded). Read-only."""
    if await conn.fetchval("SELECT to_regclass('public.schema_migrations')") is None:
        return {}
    if await _has_checksum_column(conn):
        rows = await conn.fetch("SELECT version, checksum FROM public.schema_migrations")
        return {str(r["version"]): r["checksum"] for r in rows}
    rows = await conn.fetch("SELECT version FROM public.schema_migrations")
    return {str(r["version"]): None for r in rows}


def evaluate(migrations: List[Migration], recorded: Dict[str, Optional[str]]) -> Dict[str, Any]:
    """Compare files with database history. Pure function (no I/O)."""
    on_disk = {m.version: m for m in migrations}
    problems: List[str] = []
    unknown = sorted(set(recorded) - set(on_disk))
    if unknown:
        problems.append(f"Database records migrations not present on disk: {', '.join(unknown)}")
    applied = [m.version for m in migrations if m.version in recorded]
    pending = [m.version for m in migrations if m.version not in recorded]
    if applied and pending and min(pending) < max(applied):
        problems.append(
            f"Out-of-order history: {', '.join(p for p in pending if p < max(applied))} "
            f"missing below applied {max(applied)}"
        )
    modified = [
        v for v in applied
        if recorded[v] is not None and recorded[v] != on_disk[v].checksum
    ]
    if modified:
        problems.append(f"Applied migration files changed since application: {', '.join(modified)}")
    unverified = [v for v in applied if recorded[v] is None]
    return {
        "applied": applied,
        "pending": pending,
        "unverified_checksums": unverified,
        "problems": problems,
    }


async def migration_status(conn: Any, directory: Path = MIGRATIONS_DIR) -> Dict[str, Any]:
    return evaluate(discover_migrations(directory), await recorded_migrations(conn))


async def apply_migrations(
    conn: Any, directory: Path = MIGRATIONS_DIR, backfilled: Optional[List[str]] = None
) -> List[str]:
    """Apply pending migrations in order. Refuses inconsistent history.

    Each migration file runs as its own transaction (the file contains BEGIN/COMMIT)
    and must record its own version; the runner verifies that and stores checksums.
    Versions applied earlier without a recorded checksum (e.g. by psql, or before
    migration 003 added the column) get the current file's checksum; they are
    appended to ``backfilled`` so callers can report it. A recorded checksum is
    never overwritten: a mismatch is refused above.
    """
    backfilled = backfilled if backfilled is not None else []
    migrations = discover_migrations(directory)
    await conn.execute("SELECT pg_advisory_lock($1)", _ADVISORY_LOCK_KEY)
    try:
        status = evaluate(migrations, await recorded_migrations(conn))
        if status["problems"]:
            raise MigrationError("; ".join(status["problems"]))
        applied_now: List[str] = []
        for migration in migrations:
            if migration.version not in status["pending"]:
                continue
            try:
                await conn.execute(migration.path.read_text(encoding="utf-8"))
            except Exception as exc:
                if conn.is_in_transaction():
                    await conn.execute("ROLLBACK")
                raise MigrationError(
                    f"Migration {migration.filename} failed: {type(exc).__name__}: {exc}"
                ) from exc
            if migration.version not in await recorded_migrations(conn):
                raise MigrationError(
                    f"Migration {migration.filename} did not record version {migration.version}"
                )
            applied_now.append(migration.version)
        if await _has_checksum_column(conn):
            for migration in migrations:
                result = await conn.execute(
                    "UPDATE public.schema_migrations SET checksum = $2 "
                    "WHERE version = $1 AND checksum IS NULL",
                    migration.version, migration.checksum,
                )
                if result.endswith(" 1") and migration.version not in applied_now:
                    backfilled.append(migration.version)
        return applied_now
    finally:
        await conn.execute("SELECT pg_advisory_unlock($1)", _ADVISORY_LOCK_KEY)


# ---------------------------------------------------------------------------
# Connection requirements for the migration runner
# ---------------------------------------------------------------------------
# Migrations take a SESSION-level advisory lock and run multi-statement files with
# their own BEGIN/COMMIT. A transaction-mode pooler (Supabase's pooler on port 6543,
# PgBouncer in transaction mode) may move consecutive statements to different server
# connections, which breaks both. Direct connections and session-mode poolers
# (Supabase session pooler, port 5432) are fine.

# The same rule applies to the API pool (backend/db/pg_connection.py), which shares
# this detection.

from backend.db.pg_connection import (  # noqa: E402
    DIRECT_OR_SESSION_HINT,
    SUPABASE_TRANSACTION_POOLER_PORT,
    dsn_port_problem,
    transaction_pooler_reason,
)

_DIRECT_OR_SESSION_HINT = DIRECT_OR_SESSION_HINT


def migration_connection_problem(dsn: str) -> Optional[str]:
    """Reason this DSN must not be used for migrations, or None. Never echoes credentials."""
    if dsn_port_problem(dsn):
        return "The DSN port is not a valid number."
    reason = transaction_pooler_reason(dsn)
    if reason is None:
        return None
    return (
        f"Not usable for migrations: {reason}. Transaction pooling cannot hold the "
        "session the migration runner needs. " + DIRECT_OR_SESSION_HINT
    )


async def ensure_session_connection(conn: Any, probes: int = 3) -> None:
    """Refuse a connection whose statements do not share one server session.

    Catches transaction-mode poolers that the DSN does not reveal: consecutive
    statements reporting different backend PIDs mean no session affinity.
    """
    pids = {await conn.fetchval("SELECT pg_backend_pid()") for _ in range(probes)}
    if len(pids) != 1:
        raise MigrationError(
            "Consecutive statements ran on different server sessions (transaction pooling). "
            + _DIRECT_OR_SESSION_HINT
        )
