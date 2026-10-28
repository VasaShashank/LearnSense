# Migrations

Version-controlled PostgreSQL migrations for LearnSense / TAPROOT.

---

## Applying migrations

### Prerequisites

1. A Supabase project (or self-hosted PostgreSQL ≥ 14).
2. `DATABASE_URL` set in `.env` (see `.env.example` for the exact format).
3. `psql` installed locally, **or** access to the Supabase SQL Editor.

---

### Apply via psql (recommended for CI / local dev)

```bash
# Activate your virtual environment first
source .venv/bin/activate          # Linux/macOS
.venv\Scripts\activate             # Windows PowerShell

# Apply migrations in order (001 is already applied in existing environments)
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/001_institutional_schema.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/002_revoke_institutional_client_privileges.sql
```

All migrations are **idempotent** — re-running them is safe and produces no
duplicate data.

---

### Apply via Supabase SQL Editor

1. Open your project at **https://supabase.com/dashboard**.
2. Navigate to **SQL Editor → New query**.
3. For a new database, paste and run `migrations/001_institutional_schema.sql` first.
4. Paste and run `migrations/002_revoke_institutional_client_privileges.sql`.

---

## Migration log

| Version | File | Description |
|---------|------|-------------|
| 001 | `001_institutional_schema.sql` | Organizations, memberships, course classes, enrollments. Creates `schema_migrations` tracking table. |
| 002 | `002_revoke_institutional_client_privileges.sql` | Revokes direct table privileges from `PUBLIC`, `anon`, and `authenticated` on the four institutional tables. |

---

## Connection string format

### Supabase Transaction Pooler (recommended for short-lived connections)
```
postgresql://postgres.<project-ref>:<db-password>@aws-0-<region>.pooler.supabase.com:6543/postgres
```

### Supabase Direct Connection (session-mode, for migrations)
```
postgresql://postgres.<project-ref>:<db-password>@aws-0-<region>.supabase.com:5432/postgres
```

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
