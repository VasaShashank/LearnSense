# Backup and restore

**Owner:** Person 1 · Tools: `scripts/backup_postgres.sh`, `scripts/restore_postgres.sh`
(credential helper: `scripts/pg_credentials.py`)

## Evidence

Executed against **disposable local PostgreSQL 16 clusters** only:

* `tests/integration/test_p1_postgres_live.py::test_backup_and_restore_drill`: populated
  database → `backup_postgres.sh` → restore into a **new empty** database → row counts
  of all 11 Person 1 tables identical, schema versions identical, client-role
  revocations preserved; a wrong `--confirm-database` and a non-empty target are refused.
  CI runs it against the CI service container.
* `…::test_restore_refuses_grants_to_missing_roles_and_preserves_them_once_created`:
  a dump granting to a role the target lacks is refused before anything is restored
  (target left with zero tables); after the role is created the grant is restored.
* Supabase-origin reproduction (manual, P1 Batch B): a source cluster set up like a
  Supabase project (`anon`, `authenticated`, `service_role`, an `auth` schema, Supabase's
  default privileges in `public`), migrated and seeded, then backed up and restored into
  a plain PostgreSQL cluster. The previous scripts failed with
  `role "service_role" does not exist`. The current scripts refuse with exit 4 and list
  `service_role` unless `--create-supabase-roles` is given; with it the restore
  succeeds, data and versions match, `service_role` keeps its grants and `anon` /
  `authenticated` stay revoked.
* Password-authenticated cluster (SCRAM): backup and restore succeeded with the
  password supplied only through a temporary pgpass file; the password appeared in
  neither script output nor any produced artifact.
* `tests/unit/test_p1_batch_b.py` runs both scripts against recording fake
  `pg_dump`/`psql`/`pg_restore` and asserts that no child process receives the
  password in its arguments and that the temporary pgpass file is removed.

**Not yet done:** a drill against the real staging/production database or a real
Supabase project. Required before release (**Requires staging verification**).

## What is backed up

| Data | How | Consistency |
|---|---|---|
| PostgreSQL schema `public` (all P1 tables, their ACLs and RLS flags, triggers, `schema_migrations`) | `pg_dump --format=custom --no-owner --schema=public` | One consistent snapshot |
| File stores not yet in PostgreSQL (`storage/…`: documents, jobs, learner states, sessions, subjects, learning contexts, question banks, idempotency.db, taproot.db, …) | `tar -czf` with `--file-root` | Separate from the DB snapshot: stop the API (or accept skew of in-flight writes) |
| Manifest | `learnsense_<UTC>.manifest`: schema versions, row counts, `schemas=public`, sha256 of artifacts | — |

**Not backed up by these scripts:** Supabase platform schemas (`auth`, `storage`,
`realtime`, `extensions`, …) and cluster-wide objects (roles, role passwords).
Supabase Auth users live in Supabase and are covered by Supabase's own backups.
Only `public` is dumped because LearnSense owns nothing else; dumping a Supabase
database whole would carry platform objects that cannot be restored elsewhere.

## Credentials

Pass the DSN through an environment variable named with `--dsn-env`; it is never
printed. The scripts never put the password on a command line: `pg_credentials.py`
splits the DSN into a password-free connection string (passed to `pg_dump`/`psql`/
`pg_restore`) and a pgpass entry written to a private temporary directory (mode
0700, file 0600) referenced by `PGPASSFILE`. The directory is deleted when the script
exits, including on failure. DSNs carrying `password=` in the query string are
rejected. A DSN without a password also works (then libpq's normal sources apply:
your own `~/.pgpass`, `PGPASSWORD`, certificates).

Use a role that can read every table in `public` (backup) or create objects in the
target database (restore). Use a direct or session-mode connection
(`db.<ref>.supabase.co:5432` or `<region>.pooler.supabase.com:5432`); the transaction
pooler on port 6543 does not support `pg_dump`.

`PYTHON` selects the interpreter (default `python`); `PG_BIN` may point to the
PostgreSQL client binaries (must be ≥ the server major version).

## Backup

```bash
export BACKUP_DSN='postgresql://…:5432/postgres'      # direct or session connection
scripts/backup_postgres.sh --dsn-env BACKUP_DSN --out /backups/$(date -u +%F) --file-root /app
```

**Verify every backup:** `pg_restore --list <dump>` must succeed; the manifest's
sha256 must match the files; and periodically (at least before each release) run a
full restore into a scratch database and compare row counts with the manifest.

**Retention (proposal, Requires approval):** daily backups kept 14 days, weekly kept
8 weeks, plus a backup before every release; store off-host, encrypted, with access
limited to operators. Student-data retention rules may shorten these.

## Restore

1. Create a **new, empty** database. Never restore over a live database.
2. Restore:
   ```bash
   export RESTORE_DSN='postgresql://…/learnsense_restore'
   scripts/restore_postgres.sh --dsn-env RESTORE_DSN \
       --dump /backups/…/learnsense_<UTC>.dump --confirm-database learnsense_restore
   ```
   Safety checks, in order (nothing is written until all pass):
   * `--confirm-database` must equal the connected database name (exit 3);
   * the target's `public` schema must contain no tables (exit 3);
   * every role named in the dump's GRANT/REVOKE statements must exist in the target
     cluster (exit 4, listing the missing roles, "Nothing was restored").
   The restore then runs as **one transaction with `--exit-on-error`**: on any error
   the target is left exactly as before (empty `public`).
3. Verify: `python scripts/migrate.py status --dsn-env RESTORE_DSN` (no problems) and
   compare row counts with the manifest.
4. File stores: stop the API, extract `learnsense_files_<UTC>.tar.gz` into an empty
   directory, verify its sha256 against the manifest, then swap it in as `storage/`.
5. Point the API at the restored database, start it, check `/health`, smoke test.

### Restoring into plain PostgreSQL (incl. Supabase-origin dumps)

A dump taken from Supabase contains grants to Supabase's roles (`anon`,
`authenticated`, `service_role`). Plain PostgreSQL does not have them, so the restore
stops at the role check. Choose explicitly:

* `--create-supabase-roles` runs `deploy/postgres/init/00_supabase_roles.sql`, which
  creates `anon`, `authenticated` and `service_role` as `NOLOGIN` roles (if missing).
  Grants are then restored exactly as dumped. These roles are cluster-wide and
  **remain** even if the restore later fails.
* Or create the listed roles yourself (e.g. with the privileges your platform needs)
  and rerun.

Privileges are never silently dropped: there is no option that skips missing roles.

| Object | Restored? |
|---|---|
| Tables, data, sequences, functions, triggers, RLS flags in `public` | Yes |
| Table/sequence/function grants and revocations (including to `service_role`, `anon`, `authenticated`) | Yes, once the roles exist |
| Ownership | No (`--no-owner`): objects are owned by the restoring role. The application role must own them or have `BYPASSRLS` (see migrations/README.md) |
| The `public` schema object itself (its comment and schema-level ACL) | No: the target's existing `public` schema is kept. Re-apply schema-level grants manually if your platform relies on them |
| Supabase platform schemas (`auth`, `storage`, …), default privileges outside `public`, roles and passwords | No (not in the dump) |

Restoring into a **Supabase** project needs no flag: the roles already exist.

## Schema versions differ

* Backup **older** than the current code: restore, then run
  `scripts/migrate.py apply` (migrations are additive) before starting the new code.
* Backup **newer** than the code being deployed: deploy the code version that matches
  the backup's `schema_versions` (from the manifest). The application refuses to
  start when versions are missing, and the runner refuses unknown versions.

## Rollback of a release

See docs/deployment/deployment.md §Rollback: redeploy the previous image; restore the
pre-release backup into a new database only if a schema change must be undone.
