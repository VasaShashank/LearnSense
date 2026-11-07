# API error contract

**Owner:** Person 1 · **Consumers:** all · **Blueprint:** §11 · Implemented in
`backend/api_errors.py` (installed for every route by `backend/app.py`).

## Envelope

Every error response, from every route, has this shape:

```json
{
  "error": "AUTHORIZATION_ERROR",
  "code": "FORBIDDEN",
  "message": "You do not have permission to perform this operation.",
  "recoverable": false,
  "details": {},
  "detail": "You do not have permission to perform this operation."
}
```

| Field | Meaning |
|---|---|
| `error` | Category, derived from the HTTP status (table below) |
| `code` | Specific, machine-readable code. Clients branch on this. |
| `message` | Safe human-readable text. Never display raw text from other layers without mapping. |
| `recoverable` | `true` when retrying the same request later may succeed (503, provider issues) |
| `details` | Structured, non-sensitive context (e.g. quota period and reset time) |
| `detail` | **Deprecated** compatibility alias of `message`; for 422 it is FastAPI's error list. Will be removed after clients migrate. |

## Status codes

| Status | `error` | Use | Common `code`s |
|---|---|---|---|
| 400 | `INVALID_REQUEST` | Well-formed but invalid operation | `INVALID_ASSIGNMENT`, `ORG_REQUIRED`, `INVALID_USAGE`, `VALIDATION_ERROR` |
| 401 | `AUTHENTICATION_ERROR` | Missing, invalid or expired token; non-canonical identity | `AUTHENTICATION_REQUIRED`, `INVALID_TOKEN`, `INVALID_IDENTITY` |
| 403 | `AUTHORIZATION_ERROR` | Authenticated but not permitted (organization-level operations) | `FORBIDDEN`, `AUTHORIZATION_ERROR`, `ACCOUNT_DISABLED` |
| 404 | `NOT_FOUND` | Missing **or deliberately concealed** resource | `CLASS_NOT_FOUND`, `MEMBERSHIP_NOT_FOUND`, `ENROLLMENT_NOT_FOUND`, `USER_NOT_PROVISIONED`, `NOT_FOUND` |
| 409 | `CONFLICT` | Conflicting state | `LAST_ADMIN`, `ORGANIZATION_NAME_TAKEN`, `RESOURCE_EXISTS`, `IDEMPOTENCY_CONFLICT`, `LEARNER_STATE_CONFLICT` |
| 422 | `VALIDATION_ERROR` | Request body/query failed schema validation | `REQUEST_VALIDATION_FAILED` (`details.errors` lists fields) |
| 429 | `QUOTA_EXCEEDED` | Quota or rate limit | `QUOTA_EXCEEDED` (`details`: dimension, period, limit, used, requested, resets_at) |
| 503 | `SERVICE_UNAVAILABLE` | A required dependency is down or unconfigured | `AUTH_PROVIDER_UNAVAILABLE`, `AUTH_PROVIDER_TIMEOUT`, `AUTH_NOT_CONFIGURED`, `ACCOUNT_STATUS_UNAVAILABLE` |

Typed runtime errors from other modules (`phase3.errors.LearnSenseError`
subclasses) keep their own `code` and `http_status`; recoverable ones also send
`Retry-After: 5`.

## Concealment rules (Implemented)

* Every class-scoped route returns the **same 404 body** for a nonexistent class and a
  class the caller may not access: `code: "CLASS_NOT_FOUND"`, with `message` and
  `detail` equal to `"Class not found."`. This covers the institution class routes
  (roster, enroll, unenroll, teacher reassignment), class analytics
  (`/api/classes/{class_id}/knowledge-state`, `…/student-mastery`,
  `…/student-learning-insights`, `…/teaching-optimizer/plan`,
  `…/interventions/{id}/approve|evaluate`, including a mismatched `subject_id`) and
  class-material sharing (`POST /api/classes/{class_id}/materials/{document_id}/share`).
  Tests: `test_missing_and_foreign_class_responses_are_identical` and
  `test_class_analytics_and_sharing_conceal_with_class_not_found`
  (tests/unit/test_p1_identity_lifecycle_api.py).
  **Change note:** analytics and sharing previously returned `code: "NOT_FOUND"` for
  these cases. Status, `message` and `detail` are unchanged; only `code` became more
  specific. No frontend or test consumer branched on the old value. Revoking a share
  (`DELETE …/share`) is owner-scoped and still returns `NOT_FOUND` "Document not found.".
* Organization-level operations by a non-admin return the same 403 for a foreign
  organization and a nonexistent one.
* A learner route called with another learner's ID returns 404, not 403.
* Validation errors about the *subject* of an operation (e.g. a teacher who is not a
  member) are only reachable after the caller was authorized.

## Never in an error response

Tokens, connection strings, SQL or driver messages, stack traces, other tenants'
organization/class/user IDs, the caller's role, file paths. Server logs record the
exception type, not secrets.

## Known gaps

* Some older routes owned by other modules still put `str(exc)` from generic
  exceptions into `message` (400). They use the envelope, but their message text
  should be reviewed by those owners.
