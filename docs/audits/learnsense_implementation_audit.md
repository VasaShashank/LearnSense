# LearnSense Requirements-Based Implementation and Integration Audit

**Audit date:** 2026-10-28
**Repository:** C:\Users\fawaz\OneDrive\Desktop\LearnSense
**Branch:** feat/supabase-auth-postgres
**Scope:** Read-only code and test audit, except for creating this requested report. No live database was accessed and no source, data, configuration, or migration was changed.

## Audit basis and limitations

The two named authoritative documents, LearnSense_Master_Blueprint_and_Team_Constraints.md and LearnSense_Complete_Project_Context_and_5_Person_Plan.md, were not found in the repository or in the searched user profile. The repo contains phase-specific architecture/decision documents and README.md, but those are not substitutes for the missing team blueprint. The Person 1 workstream and requirements below follow the user-provided audit prompt and observable repository behavior; blueprint-only acceptance criteria remain unverified rather than invented.

At baseline, the branch had extensive uncommitted changes: 31 modified tracked files and numerous untracked implementation/test/migration files (including an archive, a patch file, and other directories). These were treated as pre-existing. No source changes were made during this audit; this report is the only file created. .env values and environment secrets were not read or emitted.

README.md describes a broad platform and gives a pytest command, but overstates some claims (for example “enterprise-ready”, 3,000-page processing, and zero-fallback) relative to this audit's evidence. The code and test results below take precedence over README assertions. migrations/README.md documents migrations 001/002, but application startup does not check the recorded schema version.

## 1. Person 1 acceptance matrix

| ID | Requirement | Owner | Status | Evidence and verification | Gap, next action, prototype impact |
|---|---|---|---|---|---|
| P1-AUTH-01 | Verify Supabase bearer credentials server-side; reject absent/invalid credentials | Person 1 | **IMPLEMENTED** | backend/auth.py::get_current_user calls Supabase /auth/v1/user; it accepts only the returned id and optional email. tests/unit/test_supabase_auth.py; focused suite passed. | This verifies mocked provider behavior, not current live provider availability. No demo blocker if configured. |
| P1-AUTH-02 | Derive learner identity from verified identity and enforce learner-self access | Person 1 | **IMPLEMENTED** | backend/routes/api.py::_authenticated_learner_id, _assert_self_id; learner progress, onboarding, activity, diagnostic, final-assessment, tutor, entry-state, active-subject and resume routes use these checks and owner checks. tests/unit/test_learner_self_auth.py; passed. | Continue requiring every new learner endpoint to use these dependencies/helpers. |
| P1-AUTH-03 | Session restore, auth state changes, sign-in/out and bearer forwarding | Person 1 backend foundation; Person 4 frontend integration | **PARTIAL** | frontend/src/auth/session.ts, supabase.ts, AuthGate.tsx; frontend/src/api/client.ts retrieves current access token. Vitest session/API tests passed. | Session/auth UI exists, but the normal app does not enter learner workflow or provision/resume a learner. This blocks the authenticated student demo. Person 4 integration is next. |
| P1-AUTH-04 | Avoid persona fallback in authenticated journey | Person 1 / Person 4 | **IMPLEMENTED** for normal app entry | frontend/src/App.tsx::App mounts AuthGate; DemoPersonaWorkspace is explicitly separate and not mounted. | Legacy exported/demo code still uses persona IDs. Keep it isolated and never mount it as authenticated workflow. |
| P1-LEARN-01 | Trusted, repeatable learner provisioning with no legacy claiming | Person 1 | **IMPLEMENTED** | POST /api/learners/me/initialize in backend/routes/api.py; LearnerService.provision_authenticated_learner; provenance marker and conflict handling; tests/unit/test_learner_provisioning.py. | Endpoint reports a generic entry_state because it calls entry-state without a subject. The resume endpoint computes actual workflow state; consumers should use resume. This is a contract sharp edge, not a reason to infer state. |
| P1-LEARN-02 | Learner resume restores actual authorized source/session state | Person 1 backend; Person 4 frontend | **PARTIAL** | LearnerService.resume_learner_state; /api/learners/{learner_id}/resume filters source visibility to owner. Unit tests pass. App.tsx demo workspace calls resumeLearner, but normal authenticated app is only AuthGate. | Wire initialization then authenticated resume in normal frontend. Do not use initialize.entry_state as final routing state. Blocks student demo integration. |
| P1-PG-01 | PostgreSQL pool lifecycle and require-PG startup behavior | Person 1 | **IMPLEMENTED, live behavior historically verified** | backend/db/pg_connection.py; backend/app.py::on_startup/on_shutdown; test_pg_connection.py and institutional service tests passed. Previous user-provided successful pool/query/shutdown diagnostic is not repeated here. | No live connection was made in this audit. Startup tests are not proof of current Supabase availability. |
| P1-PG-02 | Migration ordering/tracking and least privilege | Person 1 | **PARTIAL** | Migrations 001/002 are transactional; 002 revokes client grants; schema_migrations uses idempotent inserts; tests/unit/test_migration_002_privileges.py. Prior user reports say both were applied and live roles checked. | Startup only ensures a pool can initialize; it does not check required migration versions despite migration 001 comment. Recommend a non-breaking diagnostic/startup warning or explicit deployment check, not an unannounced hard requirement. Live role/catalog facts are historical reports, not re-verified here. |
| P1-PG-03 | Application-level authorization with privileged DB role | Person 1 | **IMPLEMENTED in service/routes; live role assumption needs evidence** | InstitutionService authorizes before repository operations; RLS without client policies plus client revokes are in SQL. Prior audit said application connects as postgres (RLS bypass). | Do not rely on RLS for backend tenant checks. No live catalog query in this audit. |
| P1-ORG-01 | Organization membership, role, actor identity and tenant scoping | Person 1 | **IMPLEMENTED** in inspected paths | backend/services/institution_service.py::add_membership_as_admin_async, _pg_add_membership_as_admin, create_class, enroll_learner; API routes pass actor from current_user.id; tests/unit/test_institution_service_pg.py, test_institutional_learner_provisioning.py, test_supabase_auth.py. | Service-level JSON tests and mocks passed; no live DB test in this audit. |
| P1-ORG-02 | Class listing/roster/analytics enforce org role, assignment, and source ownership | Person 1 | **PARTIAL** | backend/routes/api.py::_authorize_teacher_class; class routes use it; global /student-learning-insights fails closed with 403. tests/unit/test_teacher_class_auth.py passed. | Assigned teacher must also own the class subject upload. Cross-uploader sharing is intentionally unavailable; team must choose a safe shared-content contract if required for demo. |
| P1-ORG-03 | Provisioned learner required for LEARNER membership/enrollment | Person 1 | **IMPLEMENTED** | InstitutionService._require_provisioned_learner; membership grant, initial roster and enrollment validate canonical UUID and identity_provider="supabase". tests/unit/test_institutional_learner_provisioning.py; passed. | No mapping table; current one-account/one-learner file-state assumption is explicit. |
| P1-DOC-01 | Private uploads/jobs have trusted owner; owner checks precede retrieval/status/cancel | Person 1 | **IMPLEMENTED** in inspected route paths | backend/routes/documents.py::_require_document_owner; /documents read/status/structured/page/asset/cancel; /api/sources/upload and owned-job status/cancel in backend/routes/api.py; DocumentOwnershipRepository, JobRepository; test_private_upload_ownership.py passed. | Legacy ownerless records fail closed and remain preserved. Teacher cannot read a document uploaded by someone else merely because assigned to a class. |
| P1-DOC-02 | Owner-scoped caches and subject-derived access | Person 1 | **IMPLEMENTED, focused evidence** | Upload dedupe cache key is owner-scoped; SourceService cache key includes owner and visible document IDs; subject/resource/graph endpoints require verified identity and owned source. test_private_upload_ownership.py, test_learner_self_auth.py. | No live concurrency/storage deployment verification. Shared-resource records remain deliberately separate. |
| P1-STOR-01 | Canonical UUID and storage path validation; avoid ID collisions | Person 1 | **IMPLEMENTED, focused evidence** | storage/id_validation.py; learner/session/active-subject and job/document owner repositories validate IDs and containment; tests/unit/test_storage_identity_hardening.py; passed. | Legacy safe demo identifiers remain valid only for legacy/test storage paths and are not authenticated identities. |
| P1-API-01 | Shared API contract matches client and errors are honest | Person 1 + Person 4 | **PARTIAL** | Backend request models/routes and frontend/src/api/client.ts. Error type ApiError preserves status/code; auth unit tests cover token attachment. | Frontend has no initialize helper; registerClass posts legacy payload without required org_id; createInstitutionClass accepts caller creator_user_id which backend ignores; roster/enrollment methods send redundant caller actor IDs that backend ignores. Person 4 should align client contracts. |
| P1-OPS-01 | No secret/token disclosure and safe missing-config behavior | Person 1 | **PARTIAL / NEEDS EVIDENCE** | backend/auth.py emits sanitized status messages; frontend session store does not publish tokens. .env.example and configuration docs describe intended variables. | This audit did not scan every log/error path or deployment secret store; backend ingestion exception messages may include provider-specific details. Never expose values in client errors. Deployment configuration absent. |
| P1-OPS-02 | Persistence behavior documented for prototype deployment | Person 1 | **PARTIAL** | Local JSON/files/SQLite under storage/; institutional entities can use PostgreSQL. migrations/README.md documents PG setup, not filesystem volume/restart deployment. | Deploy one backend with persistent storage/ volume for prototype. No deploy target or restart/volume test found. |
| P1-OPS-03 | Backup/restore and production retention controls | Person 1 / team operations | **MISSING for repository prototype; later operational need** | No backup/restore procedure, retention/deletion policy, or recovery exercise located in README.md, phase docs, or migrations docs. | Not needed to add infrastructure for a two-day demo; decide how demo data is preserved and who can delete it. Production blocker only if production launch is intended. |
| P1-CI-01 | CI runs reproducible backend/frontend/migration checks | Person 1/shared | **MISSING** | No .github workflow or other CI config found. README suggests pytest, TypeScript and build commands but no automation. | Add CI only if time permits; prototype blocker if team expects reproducible merge gating, otherwise P2. Migration application should not be automatic in CI. |
| P1-COST-01 | Usage metering and quotas | Person 5/team product | **NOT APPLICABLE to the agreed short prototype unless explicitly required** | Phase 4 architecture mentions seat/license model; no measured per-user LLM/ingestion quota implementation found by targeted search. | Person 5 should state whether prototype needs a simple usage counter/limit. Do not add production billing infrastructure speculatively. |

## 2. Whole-project workstream matrix

| Workstream | Status | Evidence and integration assessment | Owner / next action |
|---|---|---|---|
| Student learning loop: auth → upload → processing → graph → onboarding → assessment/practice → persisted mastery → recommendation | **PARTIAL** | Backend services and routes cover the stages; upload and learner data are owner-scoped. Authenticated normal frontend currently stops at AuthGate, so the full user journey is not available through App. Legacy persona workspace does exercise parts but is not an authenticated integration. No full journey test was run. | Person 4: wire initialization, source selection/upload, resume and existing learner components to verified user identity. Person 1 supports contract fixes. |
| Ingestion and jobs | **PARTIAL** | /documents and /api/sources/upload create owner-associated uploads/jobs, status and cancellation are owner-checked; persistence is local. test_private_upload_ownership.py passed. Processing runs in daemon threads; restart/recovery behavior and bounded resource use are not verified by this audit. | Person 1 owns authorization/persistence contract; ingestion workstream owns processing/retry/resource behavior. For prototype, verify one upload and poll/cancel manually using an isolated account. |
| Curriculum graph | **PARTIAL / NEEDS REQUIREMENTS** | Existing backend/services/knowledge_service.py, phase2 pipeline, graph models, provenance and phase2 tests exist. No accessible authoritative blueprint to verify canonical-ID, evidence, uncertainty, alignment/versioning acceptance. | Curriculum/graph owner to document the required graph contract and verify a representative source-to-graph flow. |
| Assessment and learner model | **PARTIAL** | Server-side answer authority and authenticated routes are present; assessment ownership and idempotency have focused tests. Full client flow and persisted update journey not exercised end to end. | Person 1 maintains identity/ownership contracts; learner-model owner validates assessment quality/update semantics; Person 4 integrates UI. |
| Tutor and recommendations | **PARTIAL** | Tutor routes use verified learner identity and owned source; recommendations require owner context. Grounding/resource unit tests exist. No whole authenticated tutoring run or external-cost verification here. | Tutor/recommendation owner validates grounded behavior and bounded provider use; Person 1 preserves ownership checks. |
| Teacher workflows | **PARTIAL** | Institutionally authorized class analytics, plan/approve/evaluate routes gate on membership/assignment/source ownership; global insights endpoint returns 403. Client still contains stale /classes registration shape. No full frontend teacher workflow after real authentication. | Person 1 backend auth appears implemented; Person 4 updates client/API usage; team decides whether teacher must access uploader-shared material. |
| Institutional workflows | **PARTIAL** | Organization, membership, class, roster and enrollment services/route tests exist. Trusted learners required. Institutional API calls depend on applied migrations and configured PG in deployment; no live database check this audit. | Person 1 owns; run only the previously defined controlled live verification when specifically needed. |
| Frontend/auth | **PARTIAL** | Supabase session persistence/refresh, sign-in/out UI, bearer forwarding, Vitest tests exist. App.tsx authenticated branch does not initialize or resume learner; no teacher onboarding/membership workflow. | Person 4 owns normal app integration, loading/error/empty/access-denied handling, and updated institutional client methods. |
| Shared contracts | **PARTIAL** | Canonical learner UUID and verified actor conventions are implemented server-side; private doc/job owner contract is in sidecars/job records. | Person 1 + Person 4 document and align initialization/resume, source/document/job, class/org, and error contracts. Remove unused client actor IDs only when compatible with consumers. |
| Reliability and operations | **PARTIAL** | Atomic local writes, PostgreSQL pool lifecycle, startup PG requirement and honest preflight exist. No CI, deployment config, backup/restore or multi-instance storage. | Person 1 documents single-instance persistent-storage assumption for prototype; team handles deploy/backup decisions if hosted. |

## 3. Important contracts and confirmed gaps

### Learner initialization/resume

POST /api/learners/me/initialize requires a verified bearer user and accepts no learner ID. It returns learner_id, status, created, entry_state, subject_id. Use learner_id as the canonical UUID in existing learner-self method arguments. Then call GET /api/learners/{learner_id}/resume with the same bearer token; use that response's entry_state, subject_id, active session/assessment and progress to choose the UI. Do not treat the initialization entry_state as authoritative: its implementation calls get_entry_state without a subject and may return a generic source-selection state.

Repeated initialization is designed to preserve marked identity_provider="supabase" records. A same-UUID unmarked legacy record fails closed; named legacy personas are not copied or claimed. These are supported by isolated unit tests, not live identity provisioning in this audit.

### Class and organization API

The backend POST /api/classes requires an organization ID and derives creator identity from the authenticated user. Prefer the institutional class contract POST /api/institutions/classes with org_id, subject_id, title, teacher_ids, optional enrolled_learner_ids; creator_user_id is accepted only as a legacy compatibility field and ignored. POST /api/institutions/memberships has a target user_id and role; acting admin identity is always the verified token. POST /api/institutions/classes/{class_id}/enroll has target learner_id; enroller identity comes from the token. Roster GET similarly derives caller identity from the token. Frontend registerClass is stale; roster/enrollment methods send redundant actor IDs that have no authority.

Assigned teacher access also checks the user's role and uploader ownership of the class subject. This is safe but means a teacher cannot use another user's private uploaded document. Do not “fix” this by relaxing upload privacy; agree an explicit shared-document policy with its owner/workstream first.

### Private uploads and legacy records

Authenticated document routes check sidecar ownership before content/status/page/asset/cancel operations; source upload jobs require matching persisted owner_id for polling/cancel. Owner-scoped source listing/cache prevents another user's visible-source set from selecting private results. Ownerless records are preserved and return not-found/denial. Public /api/resources/{resource_id} refers to separately indexed shared external content, not uploaded private documents. POST /api/resources now requires verified active TEACHER or ADMIN membership; implementation details are in docs/contracts/resource-sharing.md.

### Persistence/deployment assumption

Learner states, sessions, active subjects, document ownership sidecars, jobs, document assets/extraction artifacts, SQLite document/idempotency records, and teacher projections are local filesystem/SQLite state under storage/. Institutional rows use PostgreSQL when configured. A prototype deployment must mount persistent storage and run a single backend instance (or otherwise guarantee a single shared, consistent filesystem); current code does not establish safe multi-instance shared storage. No deployment target or restart/restore exercise was found. This is a deployment assumption, not live-verified behavior.

## 4. Tests and verification

### Commands run in this audit

Backend focused tests (isolated pytest temp directory; database URL cleared and require-PG disabled):

    $env:DATABASE_URL=''; $env:LEARNSENSE_REQUIRE_PG='0'; .\.venv\Scripts\python.exe -m pytest --basetemp "$env:TEMP\learnsense-audit-final-migrations" tests/unit/test_pg_connection.py tests/unit/test_supabase_auth.py tests/unit/test_learner_provisioning.py tests/unit/test_learner_self_auth.py tests/unit/test_institutional_learner_provisioning.py tests/unit/test_institution_service_pg.py tests/unit/test_teacher_class_auth.py tests/unit/test_private_upload_ownership.py tests/unit/test_storage_identity_hardening.py tests/unit/test_migration_002_privileges.py -q

**Result:** 120 passed, 6 warnings, 7.11 seconds. Warnings were Starlette/httpx TestClient deprecation, fitz/PyMuPDF deprecation, and FastAPI on_event deprecation. These are warnings, not test failures.

Frontend commands, from frontend/:

    npm.cmd test
    npm.cmd run lint
    node .\node_modules\typescript\bin\tsc --project tsconfig.app.json --noEmit --incremental false

**Results:** Vitest 2 files / 9 tests passed; lint exited 0 with existing React/React Compiler warnings (effect state updates, fast-refresh exports, impure render value, refs/memoization); TypeScript exited 0 without diagnostics. A production Vite build was not run to avoid producing build output; no UI journey was run.

Final whitespace check:

    git diff --check

**Result:** exit code 0. Git printed line-ending conversion warnings for existing dirty files. No live database, migration, external paid service, shared-storage integration test, or full E2E test was run.

### Existing integration test assumptions

These were inspected but not run because they use shared ingested_calculus/legacy fixtures or make writes/cleanup, and their request assumptions no longer match current guards:

- tests/integration/test_institutional_b2b.py::test_resource_api_endpoints expects unauthenticated personalized resource recommendations and public resource details. Recommendations now require verified auth and owned source; shared resource detail remains public by current code.
- tests/integration/test_institutional_b2b.py::test_teacher_optimizer_and_class_api posts unauthenticated to legacy /api/classes without org_id, with arbitrary learner IDs, and expects direct class access. Current implementation requires auth, organization membership/roles, trusted provisioned learner IDs, assignment, and owned upload.
- tests/integration/test_phase5_integration.py API idempotency case uses unauthenticated synthetic identity/fixture assumptions; current activity route requires verified learner identity and owned source.
- tests/integration/test_self_assessment_confidence_diagnostic.py and tests/integration/test_e2e_real_user_journey.py contain unauthenticated/legacy persona expectations and shared ingestion or cleanup helpers. They were not run because of data effects.

These are outdated test contracts inferred from inspection, not observed failing test results in this audit. The focused current authorization tests passed. Update only affected integration cases once isolated authenticated fixtures exist; do not restore removed public access.

## 5. Critical findings, prioritized

### P0 — none confirmed in inspected protected paths

The inspected learner-self, class-scoped teacher, institutional membership/enrollment, and private document/source paths use verified identity and fail closed on ownership/tenant mismatch. This does not establish that every uninspected route or deployment is secure.

### P1 — Blocks the authenticated prototype student journey

**Normal frontend stops after authentication.** frontend/src/App.tsx::App returns AuthGate; signed-in AuthGate says learner features are unavailable until mapping exists, although /api/learners/me/initialize now provides the trusted provisioning path. The API client has no initialization method and authenticated flow never requests resume. Impact: security foundations exist but the app cannot demonstrate the authenticated learner loop. **Action:** Person 4 adds init → resume → learner workspace integration, using returned UUID and resume state only.

### P1 — Teacher access to class materials is restricted to uploader

_authorize_teacher_class checks private upload ownership in addition to organization role and class assignment. Therefore a teacher assigned to a class cannot access source content uploaded by another account. This is safe private-by-default behavior but can block class demos. **Action:** team/product and document owner decide whether a controlled shared class material mechanism is needed; do not weaken the current private owner check.

### P2 — Frontend institutional client contract is stale

registerClass omits required org_id and sends the legacy class shape; backend rejects missing org. getClassRoster/enrollLearnerInClass send caller actor IDs that backend ignores. **Action:** Person 4 use institutional endpoints and current response models; remove redundant actor arguments where safe.

### Resolved in the subsequent resource-sharing implementation — shared-resource index mutation

POST /api/resources now requires a verified user with active TEACHER or ADMIN membership in an organization; public GET remains unchanged. The route has no separate update/delete endpoint; POST is its upsert operation. See docs/contracts/resource-sharing.md and tests/unit/test_shared_resource_authorization.py.

### P2 — Migration state is not checked at app startup

Migrations record versions, but no startup code checks schema_migrations; startup only requires a connectable pool when LEARNSENSE_REQUIRE_PG=1. A stale DB can start and fail later on a route. **Action:** add a non-breaking explicit readiness/diagnostic check or deployment verification command for required version 002; avoid silently turning an existing startup into a new breaking migration gate.

### P2 — No CI configuration found

No workflow configuration was found. Local tests pass, but reproducibility/merge gating is not automated. **Action:** add CI only if time permits; prototype blocker if team expects reproducible merge gating, otherwise P2. Migration application should not be automatic in CI.

### P3 — Operational hardening not established

No deployment, persistent-volume, backup/restore, retention/deletion or recovery evidence was found. For the two-day prototype, document/use one backend instance with persistent storage/; do not add production-scale infrastructure unless deployment requires it. For a later production release, add tested backup/restore and privacy/retention operations.

## 6. Ownership and next actions

### Person 1

1. Maintain backend identity, learner ownership, org/class authorization, PostgreSQL and private upload boundaries.
2. Resolve/clarify the initialization entry_state sharp edge. Consumers should use resume now; a later contract can either omit initialization state or compute it using the owned active subject.
3. Add explicit migration-version readiness/check procedure; do not auto-apply migrations.
4. Decide with team whether /api/resources is trusted internal-only; guard it before untrusted exposure.
5. Document single-instance persistent-storage assumptions for the selected demo deployment.

### Person 4

1. Implement normal frontend journey: restore Supabase session → call initialize → use returned learner UUID → call resume → enter correct workflow. Use resume entry_state, never persona ID, and present loading/error/access-denied states.
2. Align class client calls with /institutions/classes, membership/enrollment and roster contracts; remove stale actor ID assumptions.
3. Add frontend tests for the initialization/resume orchestration and API error behavior.

### Other owners / shared decisions

- Ingestion/graph/assessment/tutor owners should verify their quality/provenance semantics and cost bounds against the absent blueprint; this audit does not assign unowned requirements.
- Team/document owner: decide if class members need access to an upload owned by another account and define explicit sharing before implementation.
- Person 5/product owner: decide whether usage metering/quotas are needed for the prototype. Existing phase architecture mentions seat allocation, but no authoritative requirement document was available.
- Deployment owner/team: select persistent single-instance hosting and verify storage survives restart. Backup/restore can remain a later production item unless demo data retention is required.

### Single smallest next implementation task

**Person 4: wire the authenticated learner entry in App.tsx to call POST /api/learners/me/initialize, then call resume with the returned UUID, and route from the resume response.** Acceptance: signed-out app stays at AuthGate; signed-in user initializes without a caller ID; re-entry preserves progress; no persona ID is used; backend/API failures remain visible and do not fall back to demo mode.

## 7. Handoff readiness

**Decision: READY WITH DOCUMENTED LIMITATIONS.** Person 1's main backend security foundations have focused, isolated test evidence (120 backend tests plus 9 frontend tests), but the authenticated frontend student flow is not integrated, teacher content sharing is now explicit and uploader/assigned-class scoped, schema-version freshness is not checked at startup, and deployment durability is not verified. No end-to-end or live DB claim is made in this audit. The next handoff should be to Person 4 for the narrow initialization/resume integration above.

## 8. Files changed during this audit

- docs/audits/learnsense_implementation_audit.md — created as the requested requirements traceability and integration audit report.

No other file was changed by this audit. The pre-existing dirty worktree was preserved.

## Follow-up: authorized resource and class-material sharing (2026-10-28)

The subsequent approved implementation requires active organization `TEACHER` or `ADMIN` membership to mutate the global resource catalog, while keeping resource reads public. Private document grants are now explicit per document/class; only the verified uploader who is an assigned active teacher may create one. Access requires a current grant plus a provisioned learner, active `LEARNER` membership, and a class enrollment record. The uploader can revoke at any time; uploads remain private by default, legacy ownerless records remain denied, and cancellation remains uploader-only. Details and routes are in `docs/contracts/resource-sharing.md`.

The grant records use atomic JSON persistence under `storage/document_shares`; no institutional migration or live database change was made. A present class enrollment row is treated as active because the current enrollment model has no status field or deactivation operation. This prototype storage assumes the same persistent filesystem as document ownership and is not multi-instance coordinated.

Focused verification after this implementation: 14 new resource/class-sharing tests passed. Safe backend regression command covering sharing, upload ownership, learner-self, teacher/class, Supabase auth, provisioning, storage and migration invariants passed 128 tests with 6 deprecation warnings. `git diff --check` passed. No live DB or end-to-end verification was run.
