# Usage events, plans and quotas

**Owners:** Person 1 (storage, attribution, enforcement) · Person 5 (dimensions,
metering points, caching, cost reports, dashboards, alerts) · **Blueprint:** §5.6

## What exists (Implemented)

* Migration `005_plans_usage_quotas.sql`: `plans`, `org_plan_assignments`,
  `quota_limits(plan_id, dimension, period, limit_quantity)`, `usage_events`
  (unique `request_id`, indexed by org/dimension/time and user/time).
* `backend/services/usage_service.py:UsageService` (PostgreSQL and JSON modes).
* Operator commands: `scripts/manage_platform.py create-plan | set-limit | assign-plan`.
* **No plans, limits or dimensions are seeded. No production code path records usage
  yet** — integrating the metering points is Person 5's work.

## Service API

```python
from backend.services.usage_service import get_usage_service, QuotaExceeded

usage = get_usage_service()   # the supported way: one shared instance per process

await usage.consume(org_id, user_id, dimension, quantity, source, request_id)   # enforce + record
await usage.record_usage(org_id, user_id, dimension, quantity, source, request_id)  # record only
await usage.check_quota(org_id, user_id, dimension, qty)                        # advisory check
```

| Parameter | Rule |
|---|---|
| `org_id` | Organization the usage is charged to, or `None` for personal usage (never quota-limited). |
| `user_id` | The **verified** user (`AuthenticatedUser.id`). With an `org_id`, must be an active member of it, else `AuthorizationError` (403). |
| `dimension` | `^[a-z][a-z0-9_.]{0,63}$`, e.g. `llm.tokens`. Defined by Person 5. |
| `quantity` | Positive integer, in the dimension's unit. |
| `source` | Short component name, e.g. `ingestion.ocr`. |
| `request_id` | Idempotency key, globally unique. Namespace it (`"<component>:<job_id>:<step>"`). |

`get_usage_service()` returns one process-wide instance:

* **PostgreSQL mode** (`DATABASE_URL` configured): organization membership is checked
  in SQL and `consume` serializes per (org, dimension) with a transaction-scoped
  advisory lock, across processes and instances.
* **JSON mode** (development/tests): membership is checked through the API's
  `InstitutionService.get_membership`, resolved at call time; the shared instance's
  process-local lock serializes `consume` within the process (single process only).

Constructing `UsageService(...)` directly is for tests only; in JSON mode a direct
instance without `membership_lookup=` rejects every org-attributed call.

## Semantics

* **Idempotent:** replaying a `request_id` returns the original event (`created=false`)
  and never double-counts. Reusing a `request_id` for different usage →
  `IdempotencyConflict` (409).
* **Enforcement:** `consume` checks every limit for (org plan, dimension) and records in
  one transaction, holding a transaction-scoped advisory lock per (org, dimension).
  Verified on PostgreSQL 16: 12 concurrent `consume(qty=1)` calls against a limit of 5
  recorded exactly 5. `check_quota` alone is advisory (no lock).
* **Exceeded:** `QuotaExceeded` → HTTP **429**, `code=QUOTA_EXCEEDED`, `details` =
  `{dimension, period, limit, used, requested, resets_at}`, `recoverable=false`.
* **Periods:** `day`, `month` (UTC calendar boundaries) or `total`.
* **No plan assigned → no limits** (documented no-plan state). A limit of 0 blocks.
* **Transactions:** `consume` commits its own transaction. Call it *before* doing
  the expensive work; if the work then fails, the usage stays recorded (P5 decides
  whether to compensate with a separate refund dimension — not implemented).

## Person 5 integration (to do, P5)

1. Define the dimensions and units (proposal: `llm.tokens`, `ocr.pages`,
   `ingestion.documents`, `storage.bytes`).
2. Call `consume(...)` at the enforcement points (upload acceptance, LLM calls) with
   the verified user and the organization context.
3. Return the 429 envelope unchanged to clients.
4. Build caching, cost reporting, dashboards and alerts on `usage_events`.

## Decisions required

| Decision | Owner |
|---|---|
| Dimension names, units, and which are enforced vs. only metered | Person 5 |
| Default plan for new organizations (today: none → unlimited) | Team |
| Per-user limits (today: per organization only) | Team |
| Billing provider / subscriptions | Team (out of scope until approved) |
