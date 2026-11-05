# Deployment

**Owner:** Person 1 · Status: deployment *foundations* implemented; **no staging or
production environment has been provisioned or verified yet.**

## Artifacts

| File | Purpose |
|---|---|
| `Dockerfile` | Backend image (FastAPI + Tesseract), non-root, `/health` healthcheck. Does not run migrations. |
| `frontend/Dockerfile` | Production frontend build with the existing Vite tooling, served by nginx. |
| `docker-compose.yml` | Local **staging** stack: PostgreSQL 16, `migrate` release step, API, web, commented worker slot. |
| `deploy/env/staging.env.example` | Environment template (placeholders only). |
| `deploy/postgres/init/00_supabase_roles.sql` | Creates `anon`/`authenticated` on non-Supabase PostgreSQL. |
| `.github/workflows/ci.yml` | CI (docs: §CI below). |

The images and compose file have not been built in this environment (no container
runtime was available): **Requires staging verification.**

## Environment variables (API)

| Variable | Required in staging/production | Notes |
|---|---|---|
| `LEARNSENSE_ENV` | ✔ in every environment: `development`, `test`, `staging` or `production` | **No default**: startup fails when unset or unknown. Staging/production add strict validation. Local development: set `LEARNSENSE_ENV=development` in your local `.env`. |
| `SUPABASE_URL` | ✔ (`https://`) | Server-side token verification |
| `SUPABASE_PUBLISHABLE_KEY` or `SUPABASE_ANON_KEY` | ✔ | Never a service-role key |
| `DATABASE_URL` | ✔ | Server-only, used by the API. Supabase: direct connection or session pooler, port 5432. The transaction pooler (6543 / `pgbouncer=true`) is refused: see §Database connections |
| `LEARNSENSE_REQUIRE_PG` | ✔ `1` | |
| `ALLOWED_ORIGINS` | ✔ exact origins, comma-separated, no `*`; `https` in production | |
| `PG_SSLMODE`, `PG_MIN_SIZE`, `PG_MAX_SIZE` | optional | |
| LLM/VLM/OCR settings | per `.env.example` | Owned by other workstreams |

**Startup validation** (`backend/config.py`, run in the startup hook): in staging and
production the API refuses to start if any required setting is missing or unsafe and
lists the offending *names* (never values). With `LEARNSENSE_REQUIRE_PG=1` it also
refuses to start when the database is unreachable, a migration is missing, an applied
migration's recorded checksum differs from the file in the image, or a version has no
recorded checksum (the error names the versions and the operator action; see
migrations/README.md §Startup verification). Without `LEARNSENSE_REQUIRE_PG=1` the
same problems are logged in a banner and reported as `postgres_schema: FAILED`.

## Database connections

Every LearnSense connection uses a **direct connection** (`db.<ref>.supabase.co:5432`)
or the **Supabase session pooler** (`<region>.pooler.supabase.com:5432`). Use the
session pooler when the direct connection is unreachable (it is IPv6-only unless the
project has the IPv4 add-on). The transaction pooler (port 6543) is not supported.

| Use | Connection | Why direct/session |
|---|---|---|
| API (`DATABASE_URL`) | direct or session pooler, 5432 | asyncpg caches prepared statements per connection; transaction pooling breaks them |
| Migrations (`scripts/migrate.py`) | direct or session pooler, 5432 | Session advisory lock; multi-statement files with their own `BEGIN`/`COMMIT` |
| Backup / restore scripts | direct or session pooler, 5432 | `pg_dump`/`pg_restore` need a session |

Enforcement (all checks happen before connecting and print no credentials):

* **API:** startup fails when `DATABASE_URL` uses port 6543 or `pgbouncer=true`,
  whatever `LEARNSENSE_REQUIRE_PG` is; the pool (`backend/db/pg_connection.py`)
  refuses the same DSNs if it is used outside the app.
* **Migrations:** the runner exits 2 for the same DSNs, and after connecting refuses
  a connection whose consecutive statements run on different server sessions. That
  probe is a backstop, not a guarantee: tested with PgBouncer in transaction mode on a
  non-6543 port, it refused every time under concurrent load but passed when the pooler
  was idle (one client stayed on one backend).
* **Not detectable:** a transaction-mode pooler on another port, without
  `pgbouncer=true`. Do not configure one.

Sizing: the session pooler holds one server connection per client connection, so
`PG_MAX_SIZE` × API replicas (+1 for migrations) must stay within the project's
pooler/connection limit.

The API and the release step can share one DSN. A separate secret (e.g.
`MIGRATION_DATABASE_URL`) is still useful when migrations should run with a different
role.

**CORS:** explicit origins only. A wildcard is never combined with credentials; in
development an unset `ALLOWED_ORIGINS` allows only local Vite/dev-server origins.

**Exposure outside development/test:** unless `LEARNSENSE_ENV` is explicitly
`development` or `test` (so also when it is unset or misspelled),
`GET /api/auth/personas` (demo data) returns 404, `GET /api/system/feature-status`
reports statuses without exception text, and `GET /api/health` returns only
`{status, llm_ready}` (no provider, model or mode). Still public in every
environment: `/docs` and `/openapi.json` (the API contract); restrict them at the edge
if required.

## Secrets

* Inject through the platform's secret manager (or Docker secrets); never bake into
  images (`.dockerignore` excludes `.env*`) and never commit (`deploy/env/*.env` and
  `*.txt` are git-ignored).
* The frontend receives only `SUPABASE_URL`, the publishable key and the API base URL
  (`frontend/vite.config.ts` exposes nothing else).

## Release procedure

The first migration of the existing Supabase project (001/002 recorded, 003-006
pending) follows docs/operations/supabase-migration.md instead: read-only
compatibility check, backup, rehearsal, then the steps below.

1. Back up the database (docs/operations/backup-and-restore.md).
2. `python scripts/migrate.py status --dsn-env DATABASE_URL` — review pending versions
   (or `--dsn-env MIGRATION_DATABASE_URL` if migrations use a separate role; either
   way a direct/session connection on 5432).
3. `python scripts/migrate.py apply --dsn-env DATABASE_URL` (release step; the
   compose `migrate` service does this and the API starts only if it succeeds). If it
   reports "recorded checksums for previously unverified versions", confirm those files
   are unchanged since they were applied.
4. Roll out the new API image; `/health` must report `healthy`.
5. Smoke test: sign in, `GET /api/me`, `POST /api/learners/me/initialize`.

## Rollback

* **Application:** redeploy the previous image tag. Allowed when the database schema
  is unchanged or the new migrations are additive (all of 003–006 are additive).
* **Schema:** there are no down-migrations. To undo a schema change, restore the
  pre-release backup into a new database and point the previous release at it
  (docs/operations/backup-and-restore.md). Never edit an applied migration file —
  the runner refuses it and the API will not start (checksum mismatch).
* An older application against a newer schema is supported for additive migrations;
  a newer application refuses to start against an older schema (missing versions).

## Health checks

* `GET /health` — overall status and subsystem statuses (`postgres_schema` when
  PostgreSQL is configured). Unauthenticated; no exception text.
* `GET /api/health` — LLM provider readiness.

## Worker boundary (Person 5)

Long-running ingestion currently runs in API-process threads. The compose file has a
commented `worker` service sharing the API image, environment and file-store volume.
Person 5 provides the worker entry point and queue choice; the job contract is
docs/contracts/jobs.md. Until then, run **exactly one API instance**
(docs/architecture/persistence-strategy.md).

## Local staging

```bash
cp deploy/env/staging.env.example deploy/env/staging.env    # fill in values
printf '%s' '<db-password>' > deploy/env/staging_db_password.txt
docker compose up --build
```

The compose database is a fresh, disposable PostgreSQL volume
(`docker compose down -v` destroys it). Do not point it at Supabase production.
