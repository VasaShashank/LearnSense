# LearnSense Complete Repository Audit

## Scope and audit basis

- Repository: `VasaShashank/LearnSense`
- Inspected branch: `new`
- Inspected revision: `e335252` (`origin/new`)
- Audit scope: frontend, backend, persistence, authentication and authorization, content, Bayesian Knowledge Tracing, AI tutor, revision and analytics, testing, configuration, and operations.
- No source files were implemented, deleted, renamed, moved, or rewritten during the audit.

## Verification commands and results

| Command | Result |
|---|---|
| `pytest -q` | **356 passed, 1 failed**, 2 deprecation warnings, approximately 369 seconds |
| `cd frontend; npm run build` | **Passed** — TypeScript and Vite production build succeeded |
| `cd frontend; npm run lint` | Completed with warnings |
| Git status before/after audit | Clean after restoring test-generated artifacts |

### Python test failure

```text
tests/integration/test_e2e_real_user_journey.py::test_e2e_mixed_knowledge_learner

AssertionError:
need at least 4 grounded questions for c_limits
assert 2 >= 4
```

The end-to-end learner journey is not currently green. The failure reveals a mismatch between question-bank generation and the expected adaptive-learning workflow.

### Frontend lint warnings

Notable warnings include:

- Fast Refresh warning caused by exporting `PRESET_PERSONAS` from `frontend/src/components/common/LoginPersonaModal.tsx`.
- Impure `Math.random()` usage during render in `frontend/src/components/atlas/CustomConceptNode.tsx`.
- Additional React lint warnings in the frontend source.

---

# 1. Current architecture and dependency map

## Runtime topology

```text
React 19 + TypeScript + Vite
        |
        | REST/fetch
        v
FastAPI application
        |
        +-- /api facade routes
        +-- /documents ingestion routes
        +-- startup preflight
        |
        +-- KnowledgeService
        +-- LearnerService
        +-- LearningService
        +-- TutorService
        +-- TeacherService
        +-- InstitutionService
        +-- SourceService
        |
        +-- Phase 1 ingestion
        +-- Phase 2 educational knowledge representation
        +-- Phase 3 learner modeling/question bank/retrieval/LLM
        +-- Phase 4 diagnostics/gaps/planning/institutional logic
        +-- Phase 5 validation/idempotency/recovery
        |
        +-- JSON filesystem persistence
        +-- SQLite document/idempotency stores
        +-- optional live Groq/OpenAI services
```

## Backend

Primary entrypoint:

- `backend/app.py`
  - Creates the FastAPI application.
  - Loads `.env` manually.
  - Configures CORS.
  - Runs startup preflight checks.
  - Mounts `/api` and `/documents`.
  - Exposes `/health` and feature-status endpoints.

REST facade:

- `backend/routes/api.py`
  - Subjects and knowledge graph.
  - Learner progress and learning paths.
  - Self-assessment and diagnostic onboarding.
  - Activity and final assessment submission.
  - Tutor interaction.
  - Source upload and polling.
  - Resource recommendations.
  - Teacher analytics and interventions.
  - Institutional organizations, memberships, classes, and rosters.
  - Persona listing.

Document routes:

- `backend/routes/documents.py`
  - PDF upload.
  - Document metadata/status.
  - Structured document/page retrieval.
  - Asset retrieval.
  - Cancellation.

## Frontend

Frontend entrypoint:

- `frontend/src/App.tsx`

Major UI surfaces:

- Dashboard.
- Learning Atlas using `@xyflow/react`.
- Accessible atlas view.
- Concept inspector.
- Learning path timeline.
- Learning sessions and final assessment.
- Contextual tutor.
- Source library.
- Teacher dashboard.
- Institutional portal.
- Peer marketplace.
- Command palette.
- Persona switcher.
- Onboarding workflow.

API client:

- `frontend/src/api/client.ts`

The API client provides centralized timeout and structured error handling. However, some screens still contain fallback/demo behavior that can hide backend failures.

## Persistence

SQLite:

- `storage/db.py`
  - Documents.
  - Page states.
  - Warnings.
  - WAL mode and foreign keys.

- `storage/idempotency.py`
  - Durable idempotency tokens.
  - Cached response payloads.
  - TTL cleanup.

Filesystem JSON:

- Learner states: `phase3/storage/learner_repository.py`
- Jobs: `storage/job_repository.py`
- Institutions/classes/memberships/enrollments: `backend/services/institution_service.py`
- Documents, contexts, and question banks under `storage/`

## Dependency summary

Backend dependencies are declared in `requirements.txt`:

- FastAPI and Uvicorn.
- Pydantic.
- PyMuPDF and PDFPlumber.
- `python-docx` and `python-pptx`.
- Tesseract/PyTesseract.
- OpenCV.
- PyYAML.
- Pytest.

Frontend dependencies are declared in `frontend/package.json`:

- React 19.
- Vite 8.
- TypeScript 6.
- React Flow.
- Tailwind CSS 4.
- Oxlint.
- Lucide React.

No Alembic or equivalent database migration framework was found. SQLite schema creation is performed using `CREATE TABLE IF NOT EXISTS`.

---

# 2. Feature inventory

## Working or substantially implemented

These features are supported by source code and passing tests in the exercised paths, but are not necessarily production-ready.

| Feature | Evidence | Classification |
|---|---|---|
| Multi-format ingestion pipeline | `ingestion/`, adapters, Phase 1 tests | Working in tested paths |
| Structured document extraction | `backend/routes/documents.py` | Working in tested paths |
| Educational knowledge representation | `phase2/` and Phase 2 tests | Working in tested paths |
| Knowledge graph construction | `backend/services/knowledge_service.py` | Working in tested paths |
| Server-side answer evaluation | `backend/services/learning_service.py` | Working in tested paths |
| BKT update engine | `phase3/learner/kt.py` | Implemented and unit-tested |
| Learner state persistence | `phase3/storage/learner_repository.py` | Implemented with file locks and atomic replacement |
| Idempotency tracking | `storage/idempotency.py` | Implemented and concurrency-tested |
| Diagnostic onboarding | API routes plus integration tests | Working in tested paths |
| Misconception records | `phase3/learner/models.py` | Implemented; educational validity needs further evaluation |
| Source-grounded tutor pipeline | `backend/services/tutor_service.py` | Implemented with grounding checks |
| Teacher aggregation and intervention models | `phase4/teacher/` and teacher tests | Implemented in local persistence model |
| React knowledge atlas | `frontend/src/components/atlas/LearningAtlas.tsx` | Build-verified; runtime flow not browser-verified |
| Centralized frontend API errors | `frontend/src/api/client.ts` | Implemented |
| Frontend production build | `npm run build` | Verified |

## Incomplete, simulated, or unverified

### Persona-based authentication — simulated

Relevant files:

- `frontend/src/components/common/LoginPersonaModal.tsx`
- `frontend/src/App.tsx`

The UI selects a persona locally. A custom user can choose `LEARNER`, `TEACHER`, or `ADMIN` and provide any ID. No login, session, bearer token, cookie, or server-derived identity is established.

### Teacher analytics fallback — simulated and domain-inconsistent

Relevant file:

- `frontend/src/components/teacher/TeacherDashboard.tsx`

If the backend fails or returns no data, the UI renders hardcoded computer-science insights such as recursion, dynamic programming, sorting, and graph traversal. This is inconsistent with the stated JEE Physics, Chemistry, and Mathematics product.

### JEE syllabus and governed question bank — incomplete

The repository contains a generic educational ingestion and knowledge-building pipeline. There is no verified JEE Main Paper 1 syllabus registry, official chapter taxonomy, NTA-aligned question provenance, or KCET expansion boundary.

The question bank is generated from uploaded documents and LLM-backed content rather than from a clearly governed JEE content catalog.

### Revision scheduling — incomplete/unverified

Learner progress, path selection, BKT, and gap prioritization exist, but no complete durable spaced-repetition scheduler was verified with:

- Review due timestamps.
- Scheduling algorithm/version.
- Rescheduling after success/failure.
- Missed-review handling.
- Timezone policy.
- Notification/job execution.
- Schedule persistence and recovery.

### Browser-level validation — unverified

No Playwright, Cypress, Selenium, or equivalent browser test suite was found. Accessibility attributes exist in some components, but there is no automated accessibility gate or browser-level evidence.

### Production deployment and recovery — unverified

Operational documentation exists, but no verified production deployment pipeline, infrastructure definition, backup/restore procedure, or multi-instance storage strategy was established by the audit.

---

# 3. Prioritised findings

## Security findings

| # | Severity | File | Lines | Vulnerability | Confidence |
|---|---|---|---:|---|---:|
| 1 | CRITICAL | `backend/routes/api.py` | 664-794, 824-866 | Teacher and institutional APIs have no authenticated principal and expose or mutate class, learner, organization, membership, and mastery data using caller-controlled IDs | 10/10 |
| 2 | HIGH | `backend/routes/api.py` | 824-852 | Any network caller can create memberships, assign arbitrary users `ADMIN`, create institutions/classes, and enroll arbitrary learners | 10/10 |
| 3 | HIGH | `backend/app.py` | 119-136 | CORS fallback includes `"*"` while `allow_credentials=True`; deployment behavior is unsafe or browser-dependent if environment configuration is missing | 8/10 |
| 4 | HIGH | `backend/routes/api.py` | 137-452 | Learner and document-facing routes accept `learner_id`/document identifiers without visible authentication; ownership is not established at the HTTP boundary | 9/10 |
| 5 | MEDIUM | `backend/routes/documents.py` | 123-130 | Asset path is composed from a request-controlled filename without an explicit resolved-path containment check | 7/10 |
| 6 | MEDIUM | `frontend/src/components/teacher/TeacherDashboard.tsx` | 108-228 | Failed backend requests are converted into fabricated analytics, concealing service failure and potentially presenting false student data | 10/10 |
| 7 | LOW | `backend/app.py` | 143 | Deprecated FastAPI startup event API is used; this is not an immediate vulnerability but creates upgrade risk | 10/10 |

The first two findings are verified static vulnerabilities. The learner/document identity boundary is also a verified architectural deficiency at the visible API layer. Whether an external reverse proxy supplies authentication is unverified.

## Correctness and reliability findings

### P0 — Question generation does not satisfy the adaptive journey contract

Evidence:

- `tests/integration/test_e2e_real_user_journey.py:322`
- `pytest -q` result: 356 passed, 1 failed.
- Generated only two questions for `c_limits` where the scenario requires at least four.

Dependency:

```text
Question-bank coverage policy
    -> diagnostic/final assessment length
    -> repeat practice
    -> adaptive path confidence
    -> end-to-end user journey
```

### P1 — Persistence is not suitable for multi-worker production

The application uses:

- Per-process Python locks.
- JSON files for learner and institution state.
- SQLite idempotency storage.
- Background daemon threads for ingestion.

These controls do not provide a coherent transaction boundary across multiple Uvicorn workers, multiple containers, process crashes during cross-file updates, concurrent institution updates, or external job execution.

Evidence:

- `phase3/storage/learner_repository.py`
- `backend/services/learning_service.py`
- `backend/routes/api.py`
- `backend/services/institution_service.py`

### P1 — No governed JEE content model

The product requirement is JEE Main Paper 1, but implementation is content-source-driven and generic. A production JEE platform needs versioned entities for:

- Exam.
- Subject.
- Chapter.
- Topic.
- Skill.
- Difficulty.
- Question provenance.
- Answer validation.
- Source/licensing metadata.
- Syllabus version.

Without this, analytics and BKT state may be mathematically consistent but educationally misaligned.

### P1 — Tutor grounding validation is heuristic rather than semantic

The tutor uses page citations extracted from model output and five-character lexical-stem overlap between response and retrieved chunks.

Evidence:

- `backend/services/tutor_service.py`

This can accept an incorrect explanation that happens to share vocabulary with a source passage. It also does not guarantee that every substantive claim is individually supported.

### P1 — LLM cost and rate governance is incomplete

No complete tenant/user-level quota system was verified for:

- Requests per minute.
- Tokens per day.
- Cost accounting.
- Concurrent generation limits.
- Circuit breakers.
- Abuse detection.
- Provider budget enforcement.

### P1 — Frontend failure states are inconsistent

The API client exposes structured `ApiError`, but top-level app loading catches errors and only logs them:

- `frontend/src/App.tsx:114`
- `frontend/src/App.tsx:137`

This can leave stale data or empty screens without actionable user feedback. Teacher analytics instead uses fabricated fallback data.

### P2 — No formal schema migration strategy

SQLite tables are created opportunistically with `CREATE TABLE IF NOT EXISTS`. There is no migration version table, forward migration process, rollback procedure, or compatibility policy for persisted JSON.

### P2 — Upload processing is not production job infrastructure

`threading.Thread(..., daemon=True)` is used for ingestion in `backend/routes/api.py`. A process restart loses active execution. Durable job metadata alone does not make execution durable.

### P2 — API contract is under-specified

Frontend and backend shapes are manually duplicated. No checked OpenAPI-to-TypeScript generation or contract test was verified.

### P2 — Accessibility and browser behavior are unverified

The build passes, but there is no automated verification for:

- Keyboard navigation.
- Focus trapping in modal/drawer flows.
- Screen-reader names.
- Contrast.
- Responsive layouts.
- Upload progress behavior.
- Browser refresh/resume behavior.

### P3 — Frontend bundle size and render purity

The production JavaScript bundle is approximately 725 KB minified before gzip. Lint identifies impure render-time behavior. This is not the first architectural blocker but should be addressed before broad mobile use.

---

# 4. Proposed target architecture

## Identity and authorization

Introduce a real identity boundary:

```text
OIDC/JWT or managed identity provider
        |
        v
FastAPI authentication dependency
        |
        v
Verified Principal { user_id, roles, organization_ids }
        |
        v
Policy/service authorization checks
```

Rules:

- Never trust `learner_id`, `creator_user_id`, `enroller_user_id`, or `caller_user_id` as authentication.
- Derive acting user identity from the verified token/session.
- Keep requested target IDs as resource identifiers only.
- Enforce organization membership and role in the service layer.
- Require explicit authorization for teacher access to individual learner records.
- Add audit events for roster, membership, assessment, and data-export operations.

## Domain services

Separate the current facade into bounded application services:

1. Identity and authorization.
2. Tenant/institution administration.
3. Content ingestion and provenance.
4. JEE content catalog.
5. Question bank and assessment.
6. Learner model/BKT.
7. Revision scheduler.
8. Tutor/retrieval.
9. Teacher analytics.
10. Notifications and jobs.

The current service classes can be retained initially, but authorization and persistence should be centralized rather than duplicated across route handlers.

## Persistence

Move durable product state to PostgreSQL or an equivalent transactional database:

- Users.
- Organizations.
- Memberships.
- Classes.
- Enrollments.
- Documents.
- Concepts.
- Skills.
- Questions.
- Question provenance.
- Learner concept states.
- Attempts.
- Misconceptions.
- Revision schedule.
- Tutor conversations.
- Usage/cost records.
- Audit events.

Use:

- Alembic migrations.
- Transaction boundaries around learner attempt, BKT update, and idempotency record.
- Unique constraints for request idempotency.
- Row-level or service-level tenant filtering.
- Object storage for source files and extracted assets.
- Redis or a queue for job coordination.

## Content architecture

Add an exam-specific catalog:

```text
ExamVersion
  -> Subject
      -> Chapter
          -> Topic
              -> Concept
                  -> Skill
                  -> Question
                  -> SourceProvenance
```

Question requirements:

- Official or licensed provenance.
- Answer key and explanation provenance.
- Versioned validation.
- Difficulty and cognitive-skill metadata.
- Misconception tags.
- Subject/chapter/topic linkage.
- Deterministic quality gates.
- Minimum question pool per concept.

## Learner modeling

Retain the existing BKT engine as a replaceable model component:

```text
Attempt
  -> authoritative grading
  -> BKT update
  -> misconception evidence
  -> revision scheduling
  -> analytics event
```

Store each update as an immutable attempt/event, then materialize current learner state. This enables replay, audit, model recalibration, and rollback.

## Tutor

Use a retrieval-and-verification pipeline:

1. Retrieve source chunks.
2. Generate a structured answer with claim IDs.
3. Verify every claim against source spans.
4. Reject or revise unsupported claims.
5. Apply user/tenant quota.
6. Store prompt, model, tokens, latency, grounding result, and cost metadata without exposing secrets.

## Frontend

Use:

- Authenticated session context.
- Server-derived principal and capabilities.
- Generated API types.
- Explicit loading, error, and empty states per screen.
- No fabricated production fallback data.
- Feature flags for unfinished surfaces.
- Route guards based on server capabilities, not local role state.
- Error boundaries and telemetry.
- Browser E2E and accessibility tests.

---

# 5. Migration plan

## Phase 0 — Safety gate

Goal: prevent additional unauthorized exposure.

- Add authentication middleware/dependency.
- Block or disable institutional/teacher routes until authorization is enforced.
- Replace client-selected role as an authority source.
- Replace teacher demo fallback with an explicit unavailable/error state.
- Add security regression tests.

Acceptance criteria:

- Unauthenticated requests receive `401`.
- Authenticated users cannot access another organization’s class or learner data.
- A learner cannot elevate to teacher/admin by changing request JSON or local state.
- No fabricated analytics appear when the API fails.

## Phase 1 — API contract and authorization model

- Define principal, organization membership, role, and capability models.
- Add policy functions for own learner data, teacher class data, institution administrator operations, and source/document access.
- Generate frontend types from OpenAPI or add contract tests.
- Add audit logging for authorization decisions and sensitive operations.

Acceptance criteria:

- Every protected route has a documented authorization policy.
- No route trusts caller identity from a body/query field.
- Contract tests cover success, `401`, `403`, `404`, and validation failures.

## Phase 2 — Transactional persistence

- Introduce PostgreSQL schema and Alembic.
- Migrate institution, learner, assessment, and idempotency data.
- Keep JSON read compatibility temporarily for migration.
- Add transactional attempt processing.
- Replace daemon threads with a durable worker/queue.

Acceptance criteria:

- Concurrent duplicate submissions produce exactly one learner-model mutation.
- Process restart does not lose queued jobs.
- Migrations run forward and rollback in a test database.
- Two application workers safely process different learners and the same learner.

## Phase 3 — JEE content foundation

- Create a versioned JEE Main Paper 1 catalog.
- Define Physics, Chemistry, and Mathematics chapter/topic/concept mappings.
- Import only approved/licensed questions.
- Add provenance and review status.
- Enforce a minimum question pool per concept and assessment.

Acceptance criteria:

- Every served question has valid subject/chapter/topic/concept linkage.
- Every question has answer/explanation provenance.
- Diagnostic and final assessments meet configured minimum/maximum lengths.
- No generic computer-science fallback data is shown in a JEE learner workflow.

## Phase 4 — Learner model and revision scheduler

- Preserve current BKT equations initially.
- Store immutable attempts and model-version metadata.
- Add spaced-repetition scheduling.
- Add misconception lifecycle and counter-evidence rules.
- Build replay tests from known answer sequences.

Acceptance criteria:

- BKT outputs match independently calculated reference values.
- Attempts are replayable to the same materialized state.
- Review due dates are persisted and recoverable.
- Success, failure, skipped, and “don’t know” responses have explicit scheduling behavior.

## Phase 5 — Tutor reliability and governance

- Replace lexical citation validation with claim-level evidence validation.
- Add response refusal for unsupported claims.
- Add per-user, per-tenant, and global LLM quotas.
- Add model/provider circuit breakers and cost telemetry.
- Test hostile document and user-message inputs.

Acceptance criteria:

- Unsupported claims are rejected or clearly marked.
- Every accepted factual claim maps to source evidence.
- Quota exhaustion returns a typed recoverable error.
- Tutor cost and token usage are observable by tenant and date range.

## Phase 6 — Frontend production hardening

- Add authenticated session bootstrap.
- Replace local persona switching with server-issued capabilities.
- Add generated API types.
- Add route-level error and empty states.
- Add Playwright flows for onboarding, learning, assessment, tutor, teacher, and institution paths.
- Add axe-based accessibility checks.
- Fix lint warnings and split the large bundle.

Acceptance criteria:

- Browser refresh resumes the correct authenticated state.
- Network failures show actionable UI state.
- No screen displays fabricated data.
- Critical flows pass in Chromium at desktop and mobile viewport sizes.
- Keyboard and screen-reader smoke tests pass.

## Phase 7 — Operations and recovery

- Add deployment manifests and environment validation.
- Add structured logs with correlation/request IDs.
- Add metrics and tracing.
- Add database/object-storage backup and restore procedures.
- Define RTO/RPO and disaster-recovery runbooks.
- Add staging smoke tests before production promotion.

Acceptance criteria:

- A clean environment can be deployed from documented steps.
- Secrets are injected externally and never logged.
- Restore drills recover learner state, content metadata, and schedules.
- Health endpoints distinguish liveness from readiness.

---

# 6. Test plan

| Area | Required tests | Acceptance criteria |
|---|---|---|
| Authentication | Missing, expired, and invalid token tests | All protected routes reject unauthenticated requests |
| RBAC | Learner, teacher, and admin capability matrix | Unauthorized operations return `403`; no data leakage |
| Tenant isolation | Cross-organization class, roster, mastery, and document tests | Cross-tenant reads and writes are denied |
| Ownership | Learner A accessing Learner B state, assessment, or tutor data | Access denied without authorized teacher policy |
| Upload security | Size, type, malformed, encrypted, decompression, and traversal inputs | Bounded processing and safe rejection |
| Persistence | Migration, rollback, restart, and concurrent writes | No lost updates or corrupt state |
| Idempotency | Same request concurrently and after restart | Exactly one state mutation; stable replay response |
| BKT | Independent reference calculations and property tests | Formula and bounds remain correct |
| Question bank | Minimum pool, provenance, and answer-key integrity | All assessments meet configured pool and provenance requirements |
| Revision | Review schedule transitions | Due dates and rescheduling persist correctly |
| Tutor | Prompt injection, unsupported claims, and citation mismatch | Unsupported content is rejected or marked ungrounded |
| LLM governance | Quotas, timeout, retry, and provider failure | Typed errors and no uncontrolled retry/cost loops |
| API contracts | OpenAPI/TypeScript contract tests | Frontend and backend shapes remain synchronized |
| Frontend | Playwright onboarding, learning, assessment, and tutor flows | Critical journeys pass with real backend |
| Accessibility | Axe, keyboard, focus, and screen-reader-name checks | No critical accessibility violations |
| Performance | Large graph, large document, and concurrent request tests | Defined latency and memory limits are met |
| Recovery | Worker restart, database restore, and object-store restore | Recovery meets declared RTO/RPO |

---

# 7. Decisions requiring approval

1. Identity provider: Auth0, Azure Entra ID, Clerk, Supabase Auth, or another OIDC provider.
2. Deployment target: single VM, container platform, or Kubernetes.
3. Primary database: PostgreSQL recommended; confirm whether SQLite is acceptable only for local development.
4. Queue/worker: Redis + RQ/Celery, Dramatiq, cloud queue, or another option.
5. JEE content provenance: licensed question bank, internally authored content, official public material, or a hybrid.
6. JEE syllabus version: which JEE Main year/version should be authoritative initially?
7. KCET boundary: separate exam catalog sharing the same learner-model engine, or a separate product workflow.
8. BKT policy: retain current parameters initially or recalibrate using a defined labeled dataset.
9. Tutor policy: source-only answers, permitted general knowledge, or a two-tier response model.
10. Teacher privacy policy: which learner-level fields teachers may access, retain, export, and aggregate.
11. Retention policy: source documents, tutor conversations, learner attempts, analytics, and audit logs.
12. Operational targets: uptime, latency, maximum upload size, RTO, RPO, and LLM budget.
13. Fallback policy: confirm that fabricated/demo analytics must never appear in production.
14. Implementation order: security gate first is strongly recommended before new feature work.

## Audit conclusion

LearnSense has a substantial prototype foundation: ingestion, educational extraction, BKT mechanics, source-grounded tutoring, persistence helpers, React views, and a broad automated test suite are present. The frontend build is healthy, and most backend tests pass.

It is **not ready for production or real institutional use** because authentication and tenant authorization are not enforced at the API boundary, the current persona system is simulated, teacher analytics can display fabricated fallback data, the JEE-specific content governance layer is missing, and the full test suite is not green.

This document records the audit and plan only. No implementation changes were made as part of the audit.
