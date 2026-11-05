"""Import JSON document ownership/share records into PostgreSQL (migration 004).

    python scripts/import_document_access.py --dsn-env DATABASE_URL --storage-root storage          # dry run
    python scripts/import_document_access.py --dsn-env DATABASE_URL --storage-root storage --apply  # write

* Preserves document IDs and owners exactly; marks rows source='json_import'.
* Never overwrites: an existing PostgreSQL owner wins; a different JSON owner is
  reported as a conflict and skipped.
* Shares whose class does not exist in PostgreSQL are skipped and reported.
* Deletes nothing (JSON files stay as a rollback source).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def read_json_records(storage_root: Path):
    owners, shares = {}, []
    for path in sorted((storage_root / "document_owners").glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if data.get("document_id") == path.stem and isinstance(data.get("owner_id"), str):
            owners[path.stem] = data["owner_id"]
    for path in sorted((storage_root / "document_shares").glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        for grant in (data.get("shares") or {}).values():
            if isinstance(grant, dict) and grant.get("document_id") == path.stem:
                shares.append(grant)
    return owners, shares


async def run(dsn: str, storage_root: Path, apply: bool) -> dict:
    import asyncpg

    from backend.db.pg_connection import _normalize_database_url

    owners, shares = read_json_records(storage_root)
    report = {"owners_found": len(owners), "owners_imported": 0, "owners_existing": 0,
              "owner_conflicts": [], "shares_found": len(shares), "shares_imported": 0,
              "shares_skipped_missing_class": 0, "shares_skipped_missing_owner": 0}
    conn = await asyncpg.connect(dsn=_normalize_database_url(dsn))
    try:
        async with conn.transaction():
            for document_id, owner_id in owners.items():
                current = await conn.fetchval("SELECT owner_id FROM document_owners WHERE document_id=$1", document_id)
                if current is None:
                    report["owners_imported"] += 1
                    if apply:
                        await conn.execute(
                            "INSERT INTO document_owners (document_id, owner_id, source) VALUES ($1,$2,'json_import')",
                            document_id, owner_id,
                        )
                elif current == owner_id:
                    report["owners_existing"] += 1
                else:
                    report["owner_conflicts"].append(document_id)
            for grant in shares:
                owner_known = grant["document_id"] in owners or await conn.fetchval(
                    "SELECT 1 FROM document_owners WHERE document_id=$1", grant["document_id"])
                if not owner_known or grant["document_id"] in report["owner_conflicts"]:
                    report["shares_skipped_missing_owner"] += 1
                    continue
                if not await conn.fetchval("SELECT 1 FROM course_classes WHERE class_id=$1", grant["class_id"]):
                    report["shares_skipped_missing_class"] += 1
                    continue
                report["shares_imported"] += 1
                if apply:
                    await conn.execute(
                        """INSERT INTO document_shares (document_id, class_id, owner_id, shared_by, created_at)
                           VALUES ($1,$2,$3,$4,COALESCE($5::timestamptz, NOW()))
                           ON CONFLICT (document_id, class_id) DO NOTHING""",
                        grant["document_id"], grant["class_id"], grant["owner_id"],
                        grant.get("shared_by") or grant["owner_id"], _timestamp(grant.get("created_at")),
                    )
            if not apply:
                raise _DryRun()
    except _DryRun:
        pass
    finally:
        await conn.close()
    return report


def _timestamp(value):
    """ISO-8601 string from the JSON record -> aware datetime (None -> NOW())."""
    from datetime import datetime, timezone

    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class _DryRun(Exception):
    """Rolls back the dry-run transaction."""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dsn-env", required=True)
    parser.add_argument("--storage-root", default="storage")
    parser.add_argument("--apply", action="store_true", help="Write (default is a dry run)")
    args = parser.parse_args(argv)
    dsn = os.environ.get(args.dsn_env, "").strip()
    if not dsn:
        print(f"ERROR: environment variable {args.dsn_env} is not set or empty.", file=sys.stderr)
        return 2
    report = asyncio.run(run(dsn, Path(args.storage_root), args.apply))
    print(("APPLIED" if args.apply else "DRY RUN") + ": " + json.dumps(report, indent=2))
    return 1 if report["owner_conflicts"] else 0


if __name__ == "__main__":
    sys.exit(main())
