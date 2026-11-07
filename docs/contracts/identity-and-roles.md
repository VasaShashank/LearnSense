# Identity, roles and tenant contract

**Owner:** Person 1 · **Consumers:** Persons 2–5 · **Blueprint:** §5.1, §7, Context §9

Status legend: **Implemented** (in code, tested) · **Planned** · **Deferred** ·
**Requires approval** (a team/owner decision) · **Requires staging verification**.

## 1. Identities

| Identifier | Meaning | Format | Status |
|---|---|---|---|
| `user_id` | A Supabase Auth user. The only identity the backend trusts. | UUID (Supabase `auth.users.id`) | Implemented |
| canonical learner ID | The same value as `user_id`. Every signed-in user *is* their own learner. | UUID | Implemented |
| `org_id` | Organization (tenant) | `org_` + 8 hex | Implemented |
| `membership_id` | One user's membership in one organization | `mem_` + 8 hex | Implemented |
| `class_id` | Classroom inside one organization | `cls_` + 8 hex, server-assigned | Implemented |
| `enrollment_id` | A learner's enrollment in one class | `enr_<class_id>_<learner_id>` | Implemented |

Identity is resolved **only** from a Supabase bearer token, validated server-side
by `backend/auth.py:get_current_user` (it calls Supabase `GET /auth/v1/user`; no
local JWT decoding). Request fields such as `learner_id`, `creator_user_id`,
`enroller_user_id` are never identity: legacy `learner_id` fields are compared with
the token identity and a mismatch returns **404**; the others are ignored.

## 2. Accounts (users)

| Behavior | Status |
|---|---|
| A local user record (`users` table / `storage/users` in JSON mode) is created idempotently by `POST /api/learners/me/initialize`, `GET /api/me` and `POST /api/institutions/organizations`. It stores email (informational copy), `status`, `created_at`, `last_seen_at`. No credentials. | Implemented |
| `status` is `active` or `disabled`. A **disabled** account is rejected with **403 `ACCOUNT_DISABLED`** on every protected route, in one place (`get_current_user`). If the status cannot be read, requests fail closed with **503 `ACCOUNT_STATUS_UNAVAILABLE`**. | Implemented |
| Disabling is an operator action (`scripts/manage_platform.py user-status`), audited as `user.status_changed`. There is no HTTP route because no platform-administrator role exists. | Implemented (operator tool) |
| Disabling does **not** change the Supabase account, memberships or learning data. Supabase-side bans/deletions also block access (token validation fails → 401). | Implemented / Requires staging verification (Supabase side) |
| `GET /api/me/export` returns Person 1-owned records about the caller: user record, memberships (incl. inactive), enrollments, owned document IDs, audit events the caller performed. | Implemented |
| Account deletion and full data export across modules | **Requires approval** (retention policy) — see §8 |

**Organization membership deactivation is not account disablement.** Deactivating a
membership removes access to *one organization* only; the account keeps working and
keeps any other memberships.

## 3. Roles and scope

Roles are **per organization** (`org_memberships.role`). A user may hold different
roles in different organizations; a role grants nothing outside its organization.

| Action | ADMIN | TEACHER | LEARNER |
|---|---|---|---|
| Create an organization (becomes its first ADMIN) | any authenticated user | ← | ← |
| Add member / change role / reactivate (`POST /api/institutions/memberships`) | ✔ | ✘ | ✘ |
| Deactivate a membership | ✔ | ✘ | ✘ |
| List members (`GET …/organizations/{org_id}/memberships`) | ✔ | ✘ | ✘ |
| Create a class in the org | ✔ | ✔ (is auto-assigned) | ✘ |
| Enroll / unenroll a learner | ✔ any class | ✔ assigned classes | ✘ |
| Replace a class's teachers (`PUT …/classes/{id}/teachers`) | ✔ | ✘ | ✘ |
| Read a class roster / class analytics | ✔ any class | ✔ assigned classes | ✘ |
| Share own document with a class | ✘ | ✔ assigned class, own document | ✘ |
| Read class-shared material | — | — | ✔ when actively enrolled |
| Index a shared catalog resource (`POST /api/resources`, create-only) | ✔ | ✔ | ✘ |

A platform-administrator role does not exist (**Requires approval** if needed).
Any authenticated user can create an organization: **Requires approval** (see §8).

## 4. Membership lifecycle (Implemented)

* **Create / role change / reactivate:** `POST /api/institutions/memberships` is an
  upsert. Only an *active ADMIN of that organization* may call it.
  * LEARNER targets must be provisioned learners (initialized via
    `/api/learners/me/initialize`).
  * TEACHER/ADMIN targets must be canonical UUIDs with an **active user record**
    (they have signed in). Otherwise **404 `USER_NOT_PROVISIONED`**.
  * Re-sending an identical membership is a no-op (no audit event).
* **Deactivate:** `DELETE /api/institutions/organizations/{org_id}/memberships/{user_id}`.
  Soft: the row is kept (`is_active=false`). Idempotent (`already_inactive`).
* **Last-active-admin invariant:** an organization always keeps ≥ 1 active ADMIN.
  Demoting or deactivating the last one returns **409 `LAST_ADMIN`**.
* **Concurrency (PostgreSQL):** every membership change locks all active ADMIN rows
  of the organization (ordered by `membership_id`), then the target row, in one
  transaction. Verified against real PostgreSQL 16 with concurrent requests
  (tests/integration/test_p1_postgres_live.py): concurrent mutual deactivations and
  concurrent self-demotions always leave exactly one admin; a 24-operation mixed
  storm completed without deadlock. JSON mode uses a process-local lock (single
  process only).

## 5. Classes and enrollment (Implemented)

* A class belongs to exactly one organization; its teachers are TEACHER members of
  that organization; its learners are LEARNER members.
* **Active roster** = enrolled with `status='active'` **and** an active LEARNER
  membership. Deactivated members and unenrolled learners are excluded immediately
  from rosters, analytics projections and class-shared material.
* **Unenroll** (`DELETE /api/institutions/classes/{class_id}/enrollments/{learner_id}`)
  is soft: the row keeps `status='unenrolled'`, `unenrolled_at`, `unenrolled_by`.
  Re-enrolling reactivates the same row. Learner accounts and learning evidence are
  never deleted.
* **Teacher reassignment** replaces `teacher_ids`; removed teachers lose access to
  that class at once.

## 6. Resource ownership categories

| Category | Examples | Rule | Status |
|---|---|---|---|
| User-owned | uploaded documents | readable by the uploader; ownership is claimed once, never transferred | Implemented |
| Class-shared | an owned document shared with a class | readable by active learners actively enrolled in that class | Implemented |
| Organization-owned | — | none exist yet | Planned / Requires approval |
| Global catalog | `POST /api/resources` records | public read; create-only for active staff of any organization | Implemented (policy **Requires approval**) |
| Learner records | progress, sessions, assessments | the learner only (Person 3 semantics) | Implemented (route level) |

## 7. Tenant authorization rules (Implemented)

1. Every protected route requires a valid bearer token (route sweep test enforces it
   for every OpenAPI operation; public routes are an explicit allowlist).
2. Organization-scoped operations resolve the target's organization from the stored
   record (e.g. a class's `org_id`), never from the request.
3. A missing class and another tenant's class are **indistinguishable** (same 404 body).
4. Error responses never contain other tenants' IDs, the caller's role or IDs
   (docs/contracts/api-errors.md).
5. Membership/role/enrollment checks happen inside `InstitutionService`. Teacher
   analytics are reachable from routes only with a `ClassStaffGrant`
   (`backend/services/authorization.py`). Learner-record services (Person 3) are
   guarded at the route boundary; pushing those checks into P3 services is a P3/P1
   follow-up.
6. Privileged operations are recorded in `audit_events` **in the same transaction**
   in PostgreSQL mode. Triggers reject `UPDATE`, `DELETE` and `TRUNCATE` on the table
   (tested against PostgreSQL 16). This is **not absolute immutability**: the role that
   owns the table — which is the role the application connects as — can disable or
   drop the triggers. Tamper-resistance against a compromised application credential
   needs a non-owner application role or an external append-only sink (not implemented).
   Recorded actions: `org.created`, `membership.created`,
   `membership.role_changed`, `membership.reactivated`, `membership.deactivated`,
   `class.created`, `class.enrollment.created|reactivated|removed`,
   `class.teachers.updated`, `document.share.granted|revoked`, `user.status_changed`.
   Denied or failed operations write nothing. No audit UI (Person 5).
7. `GET /api/me/export` returns the caller's own audit events with other users'
   identifiers removed (`target_id` set to `null` or reduced to the class ID, and
   `details` limited to non-identifying keys; such events carry `"redacted": true`).
   This holds for a caller whose memberships were deactivated.

## 8. Decisions that block further work

| Decision | Who | Blocks |
|---|---|---|
| Joining an organization: direct add (today) vs. invitation + consent | Team (P1, P5, product) | Invitations (§9) |
| Who may create organizations (today: any signed-in user) | Team | Org creation policy |
| Retention: what account deletion removes vs. anonymizes across modules | Team (P1, P3, P5) | Account deletion |
| Platform-administrator role | Team | HTTP routes for account status, plans |
| Global catalog editing policy | P1, P2, P3 | Updating catalog records |
| Fate of a deactivated teacher's share grants | P1, P4/P5 | Share suspension |

## 9. Invitations — proposal (Blocked: requires approval)

Not implemented: the consent policy is undecided and must not be invented.

* **Schema (proposed):** `org_invitations(invitation_id uuid pk, org_id fk, role,
  email_hash, token_hash unique, invited_by, created_at, expires_at, accepted_at,
  accepted_user_id, revoked_at)`. Only a SHA-256 hash of the token is stored.
* **API (proposed):** `POST /api/institutions/organizations/{org_id}/invitations`
  (ADMIN; returns the token once), `GET …/invitations` (ADMIN),
  `DELETE …/invitations/{id}` (ADMIN revoke), `POST /api/invitations/accept`
  `{token}` (the signed-in invitee; creates the membership through the same guarded
  path and audits `membership.created` with `via=invitation`).
* **Security:** 256-bit random tokens; single use; expiry ≤ 7 days; bound to the
  invited email (verified Supabase email must match); acceptance rate-limited;
  revocation immediate; no account enumeration (uniform responses).
* **Decision needed:** whether direct adds remain allowed for LEARNER (school
  rosters) once invitations exist, and whether learners may decline.
