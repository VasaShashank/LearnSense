# Persistence strategy

**Owner:** Person 1 · **Blueprint:** §3.3 (PostgreSQL is the authoritative store), §7

## 1. Where data lives today and where it goes

| Entity | Owner (semantics) | Today | Target | Status |
|---|---|---|---|---|
| Users (account record/status) | P1 | PostgreSQL `users` (JSON `storage/users` in dev) | PostgreSQL | **Implemented** |
| Organizations, memberships | P1 | PostgreSQL (`org_memberships`) + JSON mirror `storage/institutions` | PostgreSQL only | Implemented; mirror removal Planned |
| Classes, enrollments | P1 | PostgreSQL + JSON mirror; analytics projection `storage/classes` | PostgreSQL only | Implemented; projection removal Planned (P3) |
| Audit events | P1 | PostgreSQL `audit_events` (trigger-protected against UPDATE/DELETE/TRUNCATE; the owning role can bypass) / JSONL in dev | PostgreSQL | **Implemented** |
| Document ownership | P1 | PostgreSQL `document_owners` when `DATABASE_URL` is set; JSON `storage/document_owners` in dev | PostgreSQL | **Implemented** (import: `scripts/import_document_access.py`) |
| Document shares | P1 | PostgreSQL `document_shares` / JSON `storage/document_shares` in dev | PostgreSQL | **Implemented** |
| Plans, quota limits, usage events | P1 storage / P5 dimensions | PostgreSQL (`005`) / JSON in dev | PostgreSQL | **Implemented** (no metering points yet — P5) |
| Jobs | P1 storage / P5 execution | JSON `storage/jobs` + SQLite `taproot.db`; canonical `jobs` table exists | PostgreSQL `jobs` | Table + repository Implemented; adoption **P5** |
| Learner state, sessions, assessments | P3 | JSON `storage/learner_states`, `storage/sessions` | PostgreSQL (P3 schema) | **Requires P3 design** |
| Idempotency keys | P3 | SQLite `storage/idempotency.db` | PostgreSQL | **Requires P3 design** |
| Learning contexts, question banks, subjects, documents | P2 / P5 | JSON + files under `storage/` | PostgreSQL metadata + private object storage | **Requires P2/P5 design** |
| Interventions | P3 | JSON `storage/interventions` | PostgreSQL | Requires P3 design |

Consequence: **only one backend instance may run** until every authoritative store
above is in PostgreSQL (file stores and SQLite are per-instance; file locks are
per-process). This is a release blocker for multi-instance production, not for a
single-instance staging deployment.

## 2. Mode selection

* `DATABASE_URL` set → PostgreSQL for every P1 store (no dual-write for document
  ownership/shares; the JSON institutional mirror is still written for legacy readers).
* `DATABASE_URL` unset → JSON files (development and tests only; **not production-safe**).
* `LEARNSENSE_REQUIRE_PG=1` → startup fails without a reachable, fully migrated
  database. Mandatory in staging/production (`backend/config.py`).

## 3. Migrations

* Files: `migrations/NNN_name.sql`, contiguous from 001, each self-transactional and
  recording its own version. Discovery and checks: `backend/db/migrations.py`.
* Apply/inspect: `python scripts/migrate.py status|apply --dsn-env VAR` (advisory-locked,
  refuses out-of-order/unknown history and modified files, records sha256 checksums).
* Startup (`backend/app.py`) reads the **same** list and refuses to start in required
  mode when any version is missing. Migrations are never applied on startup.
* Integrity reviewed in 003–006: FKs to organizations/classes, `CHECK`s on statuses,
  periods, quantities, progress; unique `(org_id,user_id)`, `(class_id,learner_id)`,
  `request_id`, `(owner_id, idempotency_key)`; RLS enabled and client roles revoked on
  every table. Not enforceable in SQL without a schema change: "an enrollment's
  learner is a LEARNER of the class's organization" (enforced in
  `InstitutionService`; documented choice). Organization names are unique
  case-insensitively across all tenants (`uq_organizations_name_ci`) — a product
  decision to revisit.

## 4. Repository and transaction conventions

* **Repositories** (`backend/repositories/*`) take an `asyncpg` connection, run SQL and
  map rows; they never commit, roll back or authorize.
* **Services** own transactions: one `async with conn.transaction()` per operation;
  authorization reads, invariant checks, the write and its audit event happen in the
  same transaction.
* **Locking:** membership-affecting operations lock active ADMIN rows of the
  organization in `membership_id` order, then target rows. New operations touching
  memberships must follow the same order.
* **Pool:** one asyncpg pool (`backend/db/pg_connection.py`) bound to a dedicated
  background event loop (`institution_service._await_background` / `_run_async`).
  Person 1 routes await it or run their synchronous service calls with
  `run_in_threadpool`. Document-access checks in async handlers use
  `await _require_document_read_access(...)`, which runs the check in the threadpool
  (guarded by `tests/unit/test_p1_batch_a.py::test_async_handlers_never_call_synchronous_access_checks_inline`).
  Affected endpoints (shared with Person 3; behavior unchanged):
  `GET /api/subjects/{s}/concepts/{c}/question`, `…/content`, `…/resources`,
  `POST /api/learners/{id}/diagnose-root-gap`, `POST /api/initialization/self-assessment`,
  `GET /api/initialization/status`, `POST /api/learners/{id}/active-subject`,
  `POST /api/initialization/diagnostic/start|answer|submit`,
  `POST /api/learners/activity-response`, `POST /api/assessment/final/start|submit`,
  `GET /api/assessment/final/status/{id}`, `POST /api/tutor/interact`.
  **Remaining (Person 3):** those handlers still read session/assessment JSON files
  synchronously (`_require_owned_init_session`, `_require_owned_final_assessment`,
  learner services): file I/O, not database calls.
* **Document access (PostgreSQL):** `DocumentAccessService` answers
  `accessible_document_ids` with one query and `can_read` with one EXISTS query,
  both driven by the caller's own active enrollments (never a scan of all shares).
  Same policy as the JSON-mode algorithm; equivalence is tested case by case against
  the original algorithm on PostgreSQL. Measured on PostgreSQL 16 with 61 shares (60
  owned by another tenant): 1 round trip / 25 ms versus 260 round trips / 1.29 s.
* **Error mapping:** domain exceptions (`LastAdminError`, `ClassNotFoundError`, …) are
  mapped to the envelope in routes (docs/contracts/api-errors.md); unique violations
  that are business rules are translated (duplicate organization name → 409).
* **Idempotency:** creates that may be retried carry a unique key (`usage_events.request_id`,
  `jobs(owner_id, idempotency_key)`); upserts return the existing row.
* **File stores (until migrated):** write a temp file then `storage.atomic_replace.replace_atomically`
  (retries transient Windows sharing violations; atomic everywhere).

## 5. Test data isolation (actual behavior)

* Live PostgreSQL tests run only with the explicit opt-in and create and drop their
  own database (tests/support/pg_safety.py, tests/integration/test_p1_postgres_live.py).
* Person 1 tests write under `tmp_path`, with one exception: the `b2b_class_env`
  fixture in `tests/integration/test_institutional_b2b.py` provisions learners through
  the API's shared learner repository, which writes to the git-ignored
  `storage/learner_states`. The previously tracked artifacts
  (`storage/classes/cls_integration_test_101.json`, `storage/institutions/...`,
  `tests/tmp_knowledge/...`) and `storage/document_owners/` are no longer written by
  the suite; CI fails if a tracked file changes.
* **Not isolated:** many tests that go through Person 2/3 services (ingestion fixture,
  learner state, sessions, question banks, learning contexts) still write to
  git-ignored directories inside the repository (`storage/learning_contexts`,
  `storage/learner_states`, `storage/sessions`, `storage/question_banks`, SQLite files)
  via those services' default paths. State written there persists between local runs.
  Redirecting those defaults is a P2/P3 change.

## 6. Coordination required

* **P3:** schema for attempts, learner state and idempotency in PostgreSQL, using the
  conventions above; then drop `storage/learner_states`, `storage/sessions`,
  `idempotency.db` and the `storage/classes` projection.
* **P5:** adopt the `jobs` table for both upload paths; move ingestion work into a
  worker; choose object storage for document bytes.
* **P2:** document/learning-context metadata tables and versioning.
