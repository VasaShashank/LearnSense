# Job persistence contract

**Owners:** Person 1 (persistence, status rules) · Person 5 (execution, retries,
cancellation, job UI) · Person 2 (artifact semantics) · **Blueprint:** §3.9, §5.3

## Current state (two legacy paths, unchanged)

| Path | Store | Statuses | Notes |
|---|---|---|---|
| `POST /api/sources/upload` | `storage/jobs/<job_id>.json` (`storage/job_repository.py`) | `queued → processing → done / error / cancelled` | Work runs in an in-process daemon thread; lost on restart. |
| `POST /documents` | SQLite `storage/taproot.db` (`documents` table) | ingestion pipeline statuses | Phase 1 ingestion path. |

Neither path was changed by Person 1. Which one survives is a **Person 5 decision**.

## Canonical store (Implemented: persistence only)

Migration `006_jobs.sql` and `backend/repositories/job_store.py:JobStore`.

| Column | Meaning |
|---|---|
| `job_id` | `job_<hex>` (or caller-supplied), primary key |
| `kind` | e.g. `ingestion.pdf` (`^[a-z][a-z0-9_.]{0,63}$`) |
| `owner_id` | Verified user who created the job (tenant attribution) |
| `org_id` | Optional organization context (FK) |
| `document_id` | Associated document, if any |
| `status` | `queued`, `running`, `succeeded`, `failed`, `cancelled` (Blueprint §5.3) |
| `progress_pct`, `stage` | Progress (0–100) and a safe stage label; only updated while `running` |
| `error_code`, `error_message` | Safe failure info; message truncated to 500 chars. Never put secrets or raw provider responses here. |
| `attempt`, `max_attempts` | `attempt` increments on every `running` transition |
| `idempotency_key` | Unique per owner: repeating `create` returns the original job |
| `pipeline_version` | Version of the pipeline that produced results |
| `result` | JSON result summary |
| `cancel_requested_at` | Set by `request_cancel` (owner-scoped, idempotent) |
| `created_at`, `updated_at`, `started_at`, `finished_at` | Timestamps |

### Allowed transitions (enforced with a row lock)

| To | From |
|---|---|
| `running` | `queued` |
| `succeeded` | `running` |
| `failed` | `queued`, `running` |
| `cancelled` | `queued`, `running` |
| `queued` (re-queue) | `running` (interrupted), `failed` (only while `attempt < max_attempts`) |

`succeeded` and `cancelled` are terminal. Anything else raises `JobTransitionError`.
Verified against PostgreSQL 16 (`test_job_persistence_contract`).

### Legacy compatibility mapping

`queued→queued`, `processing→running`, `done→succeeded`, `error→failed`,
`cancelled→cancelled` (`to_canonical_status` / `to_legacy_status`). Existing
consumers keep their statuses until Person 5 migrates them.

## Not implemented (Person 5)

Worker process and queue, retry policy (when and how often to re-queue),
cancellation orchestration (acting on `cancel_requested_at`), job APIs/UI, job
metrics. The deployment provides a worker slot (`docker-compose.yml`, commented
`worker` service) once P5 chooses the worker entry point and queue.

## Decisions required (Person 5, with P2)

* Which upload path becomes canonical and when the JSON job store is retired.
* Retry policy and `max_attempts` defaults; whether cancellation of a running job is
  cooperative only.
* Whether job status APIs return canonical or legacy statuses during migration.
