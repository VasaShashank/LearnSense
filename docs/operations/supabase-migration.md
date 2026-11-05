# Existing Supabase project: compatibility, rehearsal and production migration

**Owner:** Person 1 · **Status:** rehearsed; production run **not yet approved**
(GO/NO-GO at the end) · Tools: `scripts/premigration_check.py`,
`scripts/sql/supabase_premigration_check.sql`, `scripts/backup_postgres.sh`,
`scripts/restore_postgres.sh`, `scripts/migrate.py`

The existing project has migrations **001 and 002 recorded** in
`schema_migrations (version, applied_at, description)` **without a checksum column**,
TEXT ids, and data (5 organizations, 8 memberships, 3 classes, 2 enrollments at audit
time). Migrations **003–006** are pending. This document is the readiness report and the
procedure. Never use production as a test environment.

## 1. Compatibility check (read-only)

`scripts/sql/supabase_premigration_check.sql` is one `SELECT` returning one labelled
result set (status PASS / WARN / FAIL / INFO / UNAVAILABLE per row). It covers:
required columns and types; columns 003 adds; NOT NULL columns the API cannot fill;
the case-insensitive name index, primary keys, the unique keys behind both upserts
(column order irrelevant, valid indexes only) and foreign keys; ownership,
`REFERENCES`/`CREATE` rights, `rolbypassrls`, RLS enabled/forced, policies, client-role
grants, default privileges; `teacher_ids` shape; membership roles and orgs without an
active admin; case-insensitive duplicate names; membership/enrollment/teacher ids against
`auth.users` (types inspected first; case/whitespace variants and soft-deleted users
reported); collisions with the 9 tables, 23 index/key names, the trigger function and the
2 constraint names 003–006 create; recorded history, `search_path`, `gen_random_uuid()`,
join/FK type compatibility, row counts, roster consistency, duplicate key pairs,
orphans, triggers and event triggers. Data checks run only after the column is
confirmed to exist with a usable type **and** to be readable, so drift produces
`UNAVAILABLE`/`FAIL` rows instead of a crash.

**Run it** (either way is read-only):

```bash
# Direct (db.<ref>.supabase.co:5432) or session pooler (<region>.pooler.supabase.com:5432),
# as the postgres role. Set the variable in your own shell; never commit it.
export SUPABASE_CHECK_DSN='postgresql://…:5432/postgres?sslmode=require'
python scripts/premigration_check.py --dsn-env SUPABASE_CHECK_DSN --out reports/premigration-$(date -u +%F)
```

The runner reads the DSN only from the named variable and never prints it, refuses
transaction poolers, and executes the check inside a `READ ONLY` transaction (the server
rejects any write). It prints every non-PASS row, writes
`premigration_check.json`/`.md`, and exits 0 (no FAIL), 1 (FAIL present) or 2 (not run).
Alternatively paste the SQL file into the Supabase SQL Editor and set the row limit to
at least 200 (about 125 rows; the common default of 100 silently drops the last ones).

**Decision rules**

| Result | Action |
|---|---|
| 0 FAIL | Proceed. Review every WARN/UNAVAILABLE (table in the report says what each means). |
| Only FAIL is row 200 (`uq_organizations_name_ci` missing/invalid) | Resolve any row 600 duplicates, adopt contingency 007 (§3), then proceed. |
| Row 702/705/707 WARN (ids not in `auth.users`) | Data decision: those members cannot use their memberships. Fix or remove before go-live. |
| Any other FAIL | Stop. Each FAIL row's `action` column names the fix; most need a new reviewed migration. |

## 2. What the existing project is expected to differ in

From the audit facts, reproduced in `tests/support/supabase_sim.py`:

| Difference from the repository's 001/002 | Impact | Handled by |
|---|---|---|
| No `schema_migrations.checksum` column | None: 003 adds it; the runner then records checksums for 001/002 and reports them | Existing runner |
| Enrollment unique key in order `(learner_id, class_id)` | None: `ON CONFLICT (class_id, learner_id)` matches by column set | Verified (check row 203, rehearsal) |
| `uq_organizations_name_ci` possibly absent (not listed in the audit facts; a unique index is not a constraint, so the list does not prove absence) | API cannot return 409 for case-insensitive duplicate names; duplicates possible | Contingency 007, adopted only if row 200 FAILs |
| Tables owned by `postgres` (not a superuser), `BYPASSRLS` | None: migrations and API run as `postgres` | Verified (rehearsal runs everything as non-superuser `postgres`) |
| Supabase default privileges grant new `public` tables to `anon`/`authenticated`/`service_role` | 003–006 explicitly revoke `PUBLIC`/`anon`/`authenticated`; `service_role` keeps access (by design) | Verified: no client grant on any of the 14 tables after migration |

The exact differences of the **real** database are known only after §1 runs against it.

## 3. Migrations

| Version | Purpose | Status |
|---|---|---|
| 003 | `users`, soft unenrollment (`class_enrollments.status` etc.), append-only `audit_events`, `schema_migrations.checksum` | Pending in production |
| 004 | `document_owners`, `document_shares` | Pending |
| 005 | `plans`, `org_plan_assignments`, `quota_limits`, `usage_events` | Pending |
| 006 | `jobs` | Pending |
| 007 (contingency) | Case-insensitive unique organization names; no-op where the index exists; refuses if names collide | **Not adopted.** Adopt only on evidence (row 200 FAIL) |

No other compatibility migration is needed on the evidence available. To adopt 007:
copy `scripts/sql/contingency_007_organization_name_ci.sql` unchanged to
`migrations/007_organization_name_ci.sql`, commit (CI runs the rehearsal including it),
and continue with §5. `tests/unit/test_premigration_check.py` fails while
`migrations/007_*` exists without that decision being recorded — update its assertion
in the same commit.

## 4. Rehearsal evidence

`tests/integration/test_supabase_migration_rehearsal_live.py` (live, runs in CI against
the disposable service container; locally: `LEARNSENSE_ALLOW_LIVE_PG_TESTS=1
LEARNSENSE_TEST_DATABASE_URL=<disposable server>`). Every database is created and
dropped by the test; all application objects are created and migrated as Supabase's
**non-superuser `postgres` role**.

| Check | Result |
|---|---|
| Check on the production shape (index present) | 0 FAIL, 0 WARN, 0 UNAVAILABLE; history `001,002`; 8/8 memberships match `auth.users` |
| Check with the name index missing | exactly one FAIL: row 200 |
| Injected schema/data drift (13 kinds) | every one reported with the expected status |
| Ownership drift (table owned by another role, unreadable) | reported as FAIL rows 106/300/305; data checks `UNAVAILABLE`; no crash |
| Read-only | a write inside the runner's transaction is rejected; tables and relations unchanged after a run |
| Backup | dump sha256 and row counts match the manifest; TOC lists the 5 tables; `auth` not dumped |
| Restore into a Supabase-provisioned database | every pre-existing row identical; **found and fixed** a restore defect (below) |
| `migrate.py status` before | exit 1; pending 003–006 (+007); unverified 001, 002 |
| `migrate.py apply` | applies 003–006 (+007); "recorded checksums for previously unverified versions: 001, 002"; re-run is a no-op |
| History | every version recorded with the checksum of its file |
| Data | all pre-existing rows identical; every enrollment `status = active` |
| Security | 14 tables, all RLS enabled and not forced, all owned by `postgres`; `anon`/`authenticated`/`PUBLIC` hold no privilege on any table; `service_role` retains access |
| Objects | audit triggers (UPDATE/DELETE and TRUNCATE), both 003 check constraints, `uq_organizations_name_ci`, `idx_class_enrollments_active`, usage/jobs unique keys, live enrollment key all present |
| Startup check | `ensure_required_migrations` passes on the rehearsed database |
| Application smoke (HTTP, PostgreSQL mode, as `postgres`, on pre-existing data) | `/api/me` for 6 existing users; org membership list (4); existing class roster; class creation; new enrollment; soft unenrollment and roster update; duplicate name 409 `ORGANIZATION_NAME_TAKEN`; last-admin protection 409 `LAST_ADMIN`; cross-tenant access denied; audit events written |

Both variants pass: index present, and index missing + contingency 007.

**Restore defect found and fixed.** Restoring into a database with Supabase's default
privileges re-granted `anon`/`authenticated` on every restored table, because `pg_dump`
records privileges only relative to PostgreSQL's built-in defaults. `restore_postgres.sh`
now reconciles table privileges to exactly the dump's inside the restore transaction
(docs/operations/backup-and-restore.md).

**Connection mode.** Supabase's session pooler (Supavisor) cannot run locally;
PgBouncer 1.24 in session mode was used instead: migrations applied through it (the
same-session probe accepted it) and the tenant-isolation suite passed through it with
the application's asyncpg pool (14/14). PgBouncer in transaction mode on a non-6543 port
was refused by the probe 5/5 times under load but passed while idle — the probe is a
backstop; the port-5432-only rule is the control.

**Product behavior to communicate.** Pre-existing learners keep their existing
enrollments, but must sign in once (which provisions them) before being enrolled in a
new class or granted a staff role (`USER_NOT_PROVISIONED` until then).

## 5. Production migration sequence (requires explicit approval)

Use `MIGRATION_DATABASE_URL`: direct or session pooler, port 5432, role `postgres`,
`sslmode=require`. Set it only in the operator's shell.

1. **Freeze.** Release commit chosen; CI green on it; migrations 003–006 (and 007 if
   adopted) unchanged since the rehearsal.
2. **Check (read-only).** `python scripts/premigration_check.py --dsn-env MIGRATION_DATABASE_URL --out reports/premigration-<date>`.
   Apply the decision rules (§1). Record row 1005's counts.
3. **Backups.**
   * Supabase dashboard: confirm the latest daily backup and, if available, PITR.
   * `scripts/backup_postgres.sh --dsn-env MIGRATION_DATABASE_URL --out <secure dir> --file-root <app root>`.
   * Verify: `pg_restore --list <dump>` succeeds; dump sha256 equals the manifest;
     manifest row counts equal row 1005.
4. **Rehearse on that exact backup** (never on production): restore it into an empty,
   Supabase-provisioned scratch database (a Supabase branch/scratch project, or local
   PostgreSQL with `--create-supabase-roles`), then run steps 6–8 against it and the
   verification in step 9. Any failure: stop.
5. **Window.** Low-traffic period; 003 takes brief exclusive locks on
   `class_enrollments`, `course_classes` and `schema_migrations` (tiny tables). The
   current API may keep running: all changes are additive.
6. `python scripts/migrate.py status --dsn-env MIGRATION_DATABASE_URL` → exit 1;
   `applied: 001, 002`; `pending: 003, 004, 005, 006` (+007); `unverified checksums: 001, 002`.
   Anything else: stop.
7. `python scripts/migrate.py apply --dsn-env MIGRATION_DATABASE_URL` → `applied now:
   003, 004, 005, 006` (+007) and `recorded checksums for previously unverified versions: 001, 002`.
8. `python scripts/migrate.py status --dsn-env MIGRATION_DATABASE_URL` → exit 0.
9. **Verify (read-only, SQL Editor):**
   ```sql
   select version, checksum is not null as verified from schema_migrations order by 1;
   select relname, relrowsecurity, relforcerowsecurity, pg_get_userbyid(relowner) owner,
          has_table_privilege('anon', oid, 'SELECT,INSERT,UPDATE,DELETE') anon,
          has_table_privilege('authenticated', oid, 'SELECT,INSERT,UPDATE,DELETE') authenticated
   from pg_class where relnamespace = 'public'::regnamespace and relkind = 'r' order by 1;
   select (select count(*) from organizations) orgs, (select count(*) from org_memberships) memberships,
          (select count(*) from course_classes) classes, (select count(*) from class_enrollments) enrollments,
          (select count(*) from class_enrollments where status <> 'active') not_active;
   select tgname from pg_trigger where tgrelid = 'public.audit_events'::regclass and not tgisinternal;
   ```
   Expect: every version verified; 14 tables, RLS on, not forced, owner `postgres`,
   no `anon`/`authenticated` privilege; counts equal step 2; `not_active = 0`; two triggers.
10. **Deploy the API** with `LEARNSENSE_REQUIRE_PG=1` and a 5432 `DATABASE_URL`;
    `/health` must show `postgres_schema: OK`; smoke test sign-in, `/api/me`, an
    organization's member list and a class roster.
11. **Communicate:** existing learners sign in once before new enrollments.

## 6. Rollback and recovery

| Failure point | State | Recovery |
|---|---|---|
| Steps 1–6 | Nothing changed | Fix and restart |
| Step 7 fails mid-way | Each migration file is one transaction: earlier files committed, the failing one rolled back, checksums not yet backfilled | Old API keeps working (additive). Fix the cause; rerun step 7 (resumes; already-applied files are skipped) |
| Steps 8–9 show a problem | Schema migrated | Old API still compatible; investigate before step 10 |
| New API misbehaves | Schema migrated | Redeploy the previous API image; schema is backward compatible (enrollments default to `active`; new tables unused by old code) |
| Schema must be undone | — | No down-migrations. Preferred: Supabase PITR to just before step 7 (loses later writes to the whole project, including `auth`). Alternative: restore the step-3 backup into a new database/project and repoint (`auth` users stay in the original project). |

## 7. Risks and limitations

* **The real project has not been checked yet** (§8). Everything above is rehearsed on a
  faithful simulation built from the audit facts, not on the live schema.
* Supavisor itself was not tested (PgBouncer session mode used as the analog).
* The LearnSense backup covers `public` only; Supabase Auth data relies on Supabase's
  backups/PITR.
* Checksums recorded for 001/002 are those of today's files; the check (not the
  checksum) is what verifies the structure the live schema actually has.
* `service_role` keeps access to every new table (Supabase default; by design). The
  trigger function receives Supabase's default `EXECUTE` grants (not callable as an RPC).
* If the live `applied_at` has no default, rows for 003–006 get NULL `applied_at`
  (cosmetic; check row 105).

## 8. GO / NO-GO

* **Code, migrations, tooling and procedure: GO.** Rehearsed end to end on both possible
  shapes of the existing database, including backup, restore, migration as the
  non-superuser `postgres` role, security posture and application behavior; CI runs the
  rehearsal on every push.
* **Production migration: NO-GO until** (1) the read-only check has run against the real
  project with 0 FAIL (or only row 200, with 007 adopted and CI green), (2) the step-3
  backup is verified and rehearsed (step 4), and (3) the production run is explicitly
  approved.
