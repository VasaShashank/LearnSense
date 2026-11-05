# Migrations

Version-controlled PostgreSQL migrations for LearnSense / TAPROOT.

---

## Applying migrations

### Prerequisites

1. A Supabase project (or self-hosted PostgreSQL ≥ 14).
2. `DATABASE_URL` set in `.env` (see `.env.example` for the exact format).
3. `psql` installed locally, **or** access to the Supabase SQL Editor.

---

### Apply with the migration runner (recommended)

```bash
# On non-Supabase PostgreSQL (local, CI, compose) create Supabase's API roles first:
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f deploy/postgres/init/00_supabase_roles.sql

python scripts/migrate.py status --dsn-env DATABASE_URL   # applied / pending / problems
python scripts/migrate.py apply  --dsn-env DATABASE_URL   # apply pending, in order
```

The runner reads the DSN from the named environment variable (it never reads `.env`
and never prints credentials), takes an advisory lock, refuses unknown or
out-of-order history and modified applied files (sha256 checksums), and applies each
file in its own transaction. Exit codes: 0 ok, 1 pending (`status`), 2 error.
The application never applies migrations itself.

**Connection requirement.** The runner needs one server session (session advisory
lock; files with their own `BEGIN`/`COMMIT`). Use a direct connection or a
session-mode pooler. It refuses, before connecting, any DSN on port **6543**
(Supabase transaction pooler) or with `pgbouncer=true`, and after connecting refuses a
connection whose statements land on different backends (a best-effort backstop: an idle
transaction pooler can keep one client on one backend and pass it).

**Existing databases.** Before migrating a database that already has history (the
existing Supabase project: 001/002 recorded, no checksum column), run the read-only
compatibility check and follow docs/operations/supabase-migration.md. A contingency
migration 007 (`scripts/sql/contingency_007_organization_name_ci.sql`) is prepared and
rehearsed, but is adopted only if that check reports the case-insensitive organization
name index missing. The API's `DATABASE_URL`
follows the same rule (the API refuses to start with a transaction pooler), so one
5432 DSN serves both. See §Connection string format.

### Startup verification

With `LEARNSENSE_REQUIRE_PG=1` the API refuses to start unless, for every file in this
directory, the version is recorded in `schema_migrations` **and** the recorded sha256
equals the file's. Startup only reads; it never applies or repairs anything. Without
`LEARNSENSE_REQUIRE_PG=1` the same problems are logged and reported in `/health`.

| Problem | Cause | Operator action |
|---|---|---|
| missing | version not recorded | `python scripts/migrate.py apply --dsn-env <DSN env>` |
| checksum mismatch | an applied migration file was edited (or the database belongs to different code) | Restore the file exactly as applied, or deploy code/restore a database that matches. Never edit an applied migration; add a new one. The runner refuses too and never overwrites a recorded checksum |
| checksum not recorded | applied with psql/SQL Editor, or before 003 added the column | Confirm the files match what was applied, then run `migrate.py apply` once; it records the current files' checksums for those versions only and prints which ones |

Versions recorded in the database but missing on disk (newer schema) are tolerated
at startup; the runner refuses to apply against them.

### Manual alternative (psql / Supabase SQL Editor)

Apply the files below in version order with `psql -v ON_ERROR_STOP=1 -f <file>` or
paste them into the Supabase SQL Editor. All migrations are idempotent. Then run
`scripts/migrate.py apply` once to record checksums (the API refuses to start until
then).

---

## Migration log

| Version | File | Description |
|---------|------|-------------|
| 001 | `001_institutional_schema.sql` | Organizations, memberships, course classes, enrollments. Creates `schema_migrations` tracking table. |
| 002 | `002_revoke_institutional_client_privileges.sql` | Revokes direct table privileges from `PUBLIC`, `anon`, and `authenticated` on the four institutional tables. |
| 003 | `003_identity_lifecycle_audit.sql` | `users`, soft unenrollment columns, append-only `audit_events`, migration checksums. |
| 004 | `004_document_access.sql` | `document_owners`, `document_shares` (import JSON records with `scripts/import_document_access.py`). |
| 005 | `005_plans_usage_quotas.sql` | `plans`, `org_plan_assignments`, `quota_limits`, `usage_events`. |
| 006 | `006_jobs.sql` | Canonical `jobs` table (docs/contracts/jobs.md). |

---

## Connection string format

### Supabase Direct Connection (migrations, backup/restore, API)
```
postgresql://postgres:<db-password>@db.<project-ref>.supabase.co:5432/postgres
```

### Supabase Session Pooler (migrations, backup/restore, API; use when direct IPv6 is unavailable)
```
postgresql://postgres.<project-ref>:<db-password>@aws-0-<region>.pooler.supabase.com:5432/postgres
```

### Supabase Transaction Pooler — not supported

Port 6543 (or any DSN with `pgbouncer=true`) is refused by both the API (startup
fails; asyncpg's per-connection prepared statements do not survive transaction
pooling) and `scripts/migrate.py` (exit 2). Both checks run before connecting and
print no credentials. A transaction pooler on another port cannot be detected from
the DSN; do not configure one.

Find these strings in: **Supabase Dashboard → Project Settings → Database → Connection string**.

---

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | For PG operations | Full libpq connection string |
| `PG_SSLMODE` | No | asyncpg SSL mode (defaults to `require`) |
| `LEARNSENSE_REQUIRE_PG` | No | Set `1` in production to prevent JSON fallback |
| `PG_MIN_SIZE` | No | Pool min connections (default: 1) |
| `PG_MAX_SIZE` | No | Pool max connections (default: 5) |

---

## Security notes

- **Never** use the `service_role` key in application code or `.env`.
- Use the **anon/publishable key** for Supabase Auth (`SUPABASE_PUBLISHABLE_KEY`).
- Migration 001 enables row-level security on all institutional tables and adds
  no client policies. Migration 002 revokes direct table privileges from
  `PUBLIC`, `anon`, and `authenticated`; it preserves the server-side owner and
  `service_role` grants. The server's `DATABASE_URL` role must own these tables
  or have `BYPASSRLS`; Supabase's default `postgres` database role meets this
  condition. Direct PostgREST table access by `anon` or `authenticated` is denied.
- If a non-owner, non-`BYPASSRLS` application role is introduced, grant it only
  the required table privileges and add suitable policies before using it.
- Database credentials (`DATABASE_URL`) belong only in server-side environment
  variables — never in frontend code or committed to git.
- `.env` is listed in `.gitignore` and must never be committed.
