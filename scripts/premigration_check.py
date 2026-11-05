"""Run the read-only pre-migration compatibility check against a database.

    python scripts/premigration_check.py --dsn-env SUPABASE_CHECK_DSN --out reports/premigration

The connection string is read from the environment variable named by --dsn-env;
it is never printed. The check (scripts/sql/supabase_premigration_check.sql) is one
SELECT statement and runs inside a READ ONLY transaction, so the server rejects any
write even if the SQL were changed. Use a direct or session-pooler connection
(port 5432); transaction poolers are refused like everywhere else in LearnSense.

Exit codes: 0 no FAIL rows, 1 at least one FAIL row, 2 error (nothing was checked).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.db.pg_connection import dsn_port_problem, transaction_pooler_reason  # noqa: E402

CHECK_SQL = Path(__file__).resolve().parent / "sql" / "supabase_premigration_check.sql"
STATUSES = ("FAIL", "WARN", "UNAVAILABLE", "INFO", "PASS")


def describe_target(dsn: str) -> str:
    """Database and host only; never user or password."""
    from urllib.parse import urlsplit

    parts = urlsplit(dsn)
    return f"database '{parts.path.lstrip('/') or '(default)'}' on {parts.hostname or 'localhost'}:{parts.port or 5432}"


async def run_check(conn: Any, sql: str) -> List[Dict[str, Any]]:
    """Execute the check inside a READ ONLY transaction and return its rows."""
    async with conn.transaction(readonly=True, isolation="repeatable_read"):
        rows = await conn.fetch(sql)
    return [dict(r) for r in rows]


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    return {status: sum(1 for r in rows if r["status"] == status) for status in STATUSES}


def render_markdown(rows: List[Dict[str, Any]], meta: Dict[str, Any]) -> str:
    lines = [
        "# Pre-migration compatibility check",
        "",
        f"* Target: {meta['target']}",
        f"* Run at (UTC): {meta['run_at']}",
        f"* Check script sha256: `{meta['sql_sha256']}`",
        "* Summary: " + ", ".join(f"{k} {v}" for k, v in meta["summary"].items()),
        "",
        "| # | Section | Check | Status | Observed | Expected | Action |",
        "|---|---|---|---|---|---|---|",
    ]

    def cell(value: Any) -> str:
        return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")

    for r in rows:
        lines.append("| " + " | ".join(cell(r[k]) for k in
                                         ("sort", "section", "check_name", "status", "observed", "expected", "action")) + " |")
    return "\n".join(lines) + "\n"


async def _connect(dsn: str):
    import asyncpg

    from backend.db.pg_connection import _normalize_database_url

    kwargs = {}
    ssl_mode = os.getenv("PG_SSLMODE", "").strip()
    if ssl_mode:
        kwargs["ssl"] = ssl_mode
    return await asyncpg.connect(dsn=_normalize_database_url(dsn), **kwargs)


async def _run(dsn: str, sql: str) -> List[Dict[str, Any]]:
    conn = await _connect(dsn)
    try:
        return await run_check(conn, sql)
    finally:
        await conn.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dsn-env", required=True, help="Name of the environment variable holding the DSN")
    parser.add_argument("--sql", default=str(CHECK_SQL), help="Check script (default: the repository's)")
    parser.add_argument("--out", help="Directory for premigration_check.json and .md reports")
    args = parser.parse_args(argv)

    dsn = os.environ.get(args.dsn_env, "").strip()
    if not dsn:
        print(f"ERROR: environment variable {args.dsn_env} is not set or empty.", file=sys.stderr)
        return 2
    problem = dsn_port_problem(dsn) or transaction_pooler_reason(dsn)
    if problem:
        print(f"ERROR: unsupported connection ({problem}). Use a direct connection or the "
              "Supabase session pooler on port 5432.", file=sys.stderr)
        return 2
    sql_bytes = Path(args.sql).read_bytes()
    target = describe_target(dsn)
    print(f"target: {target} (read-only)")
    try:
        rows = asyncio.run(_run(dsn, sql_bytes.decode("utf-8")))
    except Exception as exc:  # never echo the DSN
        print(f"ERROR: {type(exc).__name__}: the check could not run: {str(exc).splitlines()[0][:200]}",
              file=sys.stderr)
        return 2

    meta = {
        "target": target,
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sql_sha256": hashlib.sha256(sql_bytes).hexdigest(),
        "summary": summarize(rows),
    }
    order = {s: i for i, s in enumerate(STATUSES)}
    for r in sorted(rows, key=lambda r: (order.get(r["status"], 9), r["sort"])):
        if r["status"] in ("PASS", "INFO"):
            continue
        print(f"{r['status']:<11} {r['sort']:>4} {r['check_name']}: {str(r['observed'])[:160]}")
        if r["action"]:
            print(f"{'':16} -> {r['action'][:240]}")
    print("summary: " + ", ".join(f"{k} {v}" for k, v in meta["summary"].items()))

    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "premigration_check.json").write_text(
            json.dumps({"meta": meta, "rows": rows}, indent=2, default=str), encoding="utf-8")
        (out / "premigration_check.md").write_text(render_markdown(rows, meta), encoding="utf-8")
        print(f"reports written to {out}")
    return 1 if meta["summary"]["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
