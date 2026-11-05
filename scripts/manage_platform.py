"""Operator commands for Person 1 platform records (PostgreSQL).

There is no platform-administrator role or HTTP route for these operations yet
(docs/contracts/identity-and-roles.md). Operators run them with an explicit DSN:

    python scripts/manage_platform.py --dsn-env DATABASE_URL user-status <user_uuid> disabled --reason "..." --actor "<operator-id>"
    python scripts/manage_platform.py --dsn-env DATABASE_URL create-plan <plan_id> "<name>"
    python scripts/manage_platform.py --dsn-env DATABASE_URL set-limit <plan_id> <dimension> <day|month|total> <limit>
    python scripts/manage_platform.py --dsn-env DATABASE_URL assign-plan <org_id> <plan_id> --actor "<operator-id>"

Account status changes are audited (audit_events, action user.status_changed).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def run(dsn: str, args) -> int:
    import asyncpg

    from backend.db.pg_connection import _normalize_database_url
    from backend.repositories.platform_repository import AuditRepository, UsageRepository, UserRepository
    from backend.services.audit_log import USER_STATUS_CHANGED
    from backend.services.usage_service import PERIODS
    from storage.id_validation import validate_canonical_learner_id

    conn = await asyncpg.connect(dsn=_normalize_database_url(dsn))
    try:
        async with conn.transaction():
            if args.command == "user-status":
                user_id = validate_canonical_learner_id(args.user_id)
                record = await UserRepository().set_status(conn, user_id, args.status, args.reason)
                if record is None:
                    print("ERROR: no such user record (the user has never signed in)", file=sys.stderr)
                    return 1
                await AuditRepository().insert(
                    conn, actor_user_id=args.actor, org_id=None, action=USER_STATUS_CHANGED,
                    target_type="user", target_id=user_id,
                    details={"status": args.status, "reason": args.reason},
                )
                print(f"user {user_id}: status={record['status']}")
            elif args.command == "create-plan":
                await UsageRepository().create_plan(conn, args.plan_id, args.name)
                print(f"plan {args.plan_id} saved")
            elif args.command == "set-limit":
                if args.period not in PERIODS:
                    print("ERROR: period must be day, month or total", file=sys.stderr)
                    return 2
                await UsageRepository().set_limit(conn, args.plan_id, args.dimension, args.period, args.limit)
                print(f"limit {args.plan_id}/{args.dimension}/{args.period}={args.limit}")
            elif args.command == "assign-plan":
                await UsageRepository().assign_plan(conn, args.org_id, args.plan_id, args.actor)
                print(f"org {args.org_id}: plan={args.plan_id}")
        return 0
    finally:
        await conn.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dsn-env", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("user-status")
    p.add_argument("user_id")
    p.add_argument("status", choices=["active", "disabled"])
    p.add_argument("--reason")
    p.add_argument("--actor", required=True)
    p = sub.add_parser("create-plan")
    p.add_argument("plan_id")
    p.add_argument("name")
    p = sub.add_parser("set-limit")
    p.add_argument("plan_id")
    p.add_argument("dimension")
    p.add_argument("period")
    p.add_argument("limit", type=int)
    p = sub.add_parser("assign-plan")
    p.add_argument("org_id")
    p.add_argument("plan_id")
    p.add_argument("--actor", required=True)
    args = parser.parse_args(argv)
    dsn = os.environ.get(args.dsn_env, "").strip()
    if not dsn:
        print(f"ERROR: environment variable {args.dsn_env} is not set or empty.", file=sys.stderr)
        return 2
    return asyncio.run(run(dsn, args))


if __name__ == "__main__":
    sys.exit(main())
