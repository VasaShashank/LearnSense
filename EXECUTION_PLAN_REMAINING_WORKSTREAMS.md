# Comprehensive Execution Plan: The 7 Remaining Workstreams

This document outlines the detailed technical gap analysis and step-by-step implementation plan for completing the remaining 7 production-hardening workstreams in **LearnSense / TAPROOT**.

---

## Workstream 1: Assessment Security

### Current State & Vulnerability Analysis
- In `LearningService.get_concept_question()` (`backend/services/learning_service.py`), `correct_answer` is returned directly in the response dictionary to the frontend:
  ```python
  return {
      "question_id": q.question_id,
      "options": q.options,
      "correct_answer": q.correct_answer,  # <--- LEAKED TO FRONTEND
      ...
  }
  ```
- In `LearningSession.tsx` and `OnboardingWorkflow.tsx`, evaluation is performed client-side:
  ```typescript
  const isCorrect = selectedOptionIdx !== null && question
    ? question.options[selectedOptionIdx]?.trim() === question.correct_answer?.trim()
    : selectedOptionIdx === 0;
  ```
  The client then submits an arbitrary `correctness: float` (1.0 or 0.0) to `/api/learners/activity-response` or `/api/initialization/diagnostic/submit`.
- Any user can inspect network traffic or craft a POST payload to award themselves 100% mastery without knowing the correct answers.

### Implementation Tasks
1. **Sanitize Outbound Question Payloads**:
   - In `LearningService.get_concept_question()`, strip `correct_answer` from the returned question payload.
   - Ensure `diagnostic/start` continues stripping `correct_answer` (already partially done, reinforce across all paths).
2. **Server-Side Answer Evaluation**:
   - Update `POST /api/learners/activity-response`:
     - Change request schema to accept `question_id: str`, `selected_option: Optional[str]`, and `is_dont_know: bool`.
     - Server retrieves the authoritative question from `QuestionBankRepository` by `question_id`.
     - If `is_dont_know=True`, server sets `correctness = 0.0`.
     - Otherwise, server compares `selected_option.strip() == question.correct_answer.strip()`, computing `correctness = 1.0` or `0.0`.
     - Server returns evaluation feedback (`is_correct: bool`, `explanation: str`, `correct_answer: str` *only after submission*, `updated_masteries`).
   - Update `POST /api/initialization/diagnostic/submit`:
     - Change payload from `responses: Dict[str, float]` to `responses: Dict[str, str]` (mapping `question_id -> selected_option_text`).
     - Server computes exact correctness by comparing against the persisted question bank.
3. **Frontend Component Updates**:
   - In `frontend/src/api/client.ts`, update `submitActivityResponse` and `submitDiagnostic` to send selected option strings instead of client-calculated correctness.
   - In `LearningSession.tsx`, remove client-side answer evaluation. The client sends `selectedOption`, waits for the server response, and displays the server-returned `is_correct` and `explanation`.
   - In `OnboardingWorkflow.tsx`, record the selected option string or `DON'T KNOW`, transmitting raw choices to the server.

---

## Workstream 2: Real AI Tutor

### Current State & Vulnerability Analysis
- In `backend/services/tutor_service.py`, `TutorService.generate_contextual_response()` currently uses hardcoded template strings with regex message sanitization instead of real retrieval and LLM inference:
  ```python
  if intent == "EXPLAIN":
      response_text = f"Let's build {c_name} step by step..."
  elif intent == "HINT":
      response_text = f"💡 Hint for {c_name}..."
  ```
- It does not invoke `EvidenceRetriever`, does not call `Phase3LLMAdapter`, and does not validate source citations.

### Implementation Tasks
1. **Passage Retrieval & Context Construction**:
   - In `TutorService`, initialize or acquire `EvidenceRetriever` for the subject via `KnowledgeBuildService.get_retriever(subject_id)`.
   - Retrieve top $k$ relevant passages ($k=3\text{--}5$) for `concept_id` with BM25 scoring.
   - Fetch the learner's active mastery probability ($P(L)$), prerequisite mastery statuses, and identified knowledge gaps.
2. **Pedagogical LLM Grounding Prompt**:
   - Construct a prompt incorporating:
     - Subject & Concept canonical definitions.
     - Verbatim source passages with `[Page X]` citations.
     - Learner pedagogical context:
       - Low mastery ($P(L) < 0.40$): Provide intuitive, concrete breakdown, analogies, and step-by-step guidance.
       - High mastery ($P(L) \ge 0.70$): Offer deeper analytical connections, edge cases, and downstream implications.
     - Student intent (`EXPLAIN`, `HINT`, `ANALOGY`, `WHY_WRONG`, or `CUSTOM` query).
     - Strict guardrail: *"Base your response strictly on the retrieved source material. Never invent facts outside the text. Cite page numbers whenever referencing specific formulas or assertions."*
3. **LLM Inference via Phase3LLMAdapter**:
   - Call `Phase3LLMAdapter.generate_json()` or `generate_text()`.
   - Honors `LLM_MODE=mock` for deterministic testing and uses Groq (LLaMA 3.3 70B) in production.
4. **Citation Validation**:
   - Extract page citations mentioned in the LLM response.
   - Verify citations against actual retrieved evidence chunks; filter out or correct hallucinated references.
5. **Frontend Tutor Integration**:
   - Update `ContextualTutor.tsx` to display verified page citations with clickable jump links to document source sections.

---

## Workstream 3: Server Authority & Learner Ownership

### Current State & Vulnerability Analysis
- The backend currently trusts the client to supply concept lists:
  - `SelfAssessmentApiRequest.all_subject_concept_ids`
  - `ActivityResponseApiRequest.all_subject_concept_ids`
  - `get_knowledge_gaps(learner_id, subject_id, concept_ids)`
  - `get_learning_path(learner_id, subject_id, concept_ids)`
- If a client sends an empty, truncated, or tampered concept list, the backend uses it directly, potentially corrupting learner states and path planning.
- Sessions and learner states have no ownership checks; any caller specifying an arbitrary `learner_id` can mutate another learner's state.

### Implementation Tasks
1. **Authoritative Concept Derivation**:
   - In `LearningService` and `api.py`, remove the requirement for clients to supply `all_subject_concept_ids`.
   - The server derives the canonical concept list directly from the subject's persisted `LearningContext`:
     ```python
     ctx = self.knowledge_service.get_learning_context(subject_id)
     authoritative_concept_ids = list(ctx.concepts.keys())
     ```
   - If the client provides a concept list, validate that every ID exists in the authoritative context, rejecting any foreign IDs with HTTP 422.
2. **Establish Learner Ownership & Session Verification**:
   - In `SessionRepository` and `submit_diagnostic`, verify that `session.learner_id == req.learner_id` and `session.subject_id == req.subject_id`.
   - Prevent cross-subject or cross-learner session pollution.

---

## Workstream 4: Persistence Hardening

### Current State & Vulnerability Analysis
- **In-Memory Idempotency**: `IdempotencyTracker` in `phase5/validation/learner_state_validator.py` stores processed tokens in an in-memory `Set[str]`. A server restart or worker reload clears all tokens, allowing duplicate activity submissions.
- **In-Memory Ingestion Jobs**: `_JOBS: Dict[str, Dict[str, Any]]` in `backend/routes/api.py` stores upload progress in RAM. If the server restarts during ingestion, job status is lost and the frontend hangs.
- **Concurrency Hazards on Learner State**: `LearnerStateRepository.save_state` uses `with open(path, "w") as f:` without file locking or process mutexes. Concurrent requests for the same learner can cause lost updates or file truncation.

### Implementation Tasks
1. **Durable Idempotency Store**:
   - Implement `DurableIdempotencyTracker` backed by SQLite (`storage/idempotency.db`) or atomic append-only JSON storage.
   - Record `(token, learner_id, request_hash, response_json, created_at, expires_at)`.
   - If a duplicate token arrives, return the previously cached response payload immediately.
2. **Durable Ingestion Job Store**:
   - Store ingestion jobs under `storage/jobs/{job_id}.json` using atomic writes.
   - Maintain status (`queued`, `inspecting`, `extracting`, `synthesizing_atlas`, `building_questions`, `done`, `error`), percentage, elapsed time, and error details.
   - Survives server restarts and allows seamless client reconnection.
3. **Concurrency-Safe Learner State Mutations**:
   - Implement file-level locking (`portalocker` or cross-platform keyed mutex in `LearnerService`) per `learner_id`.
   - Upgrade `LearnerStateRepository.save_state` and `SessionRepository.save_session` to write via temporary file (`tempfile.mkstemp` + `os.replace`), matching `QuestionBankRepository`.

---

## Workstream 5: Architecture Consolidation

### Current State & Vulnerability Analysis
- `backend/routes/phase4.py` is mounted in `backend/app.py` under prefix `/phase4`.
- `phase4.py` maintains its own standalone in-memory dictionaries:
  - `_SESSIONS: Dict[str, KnowledgeInitializationSession] = {}`
  - `_LEARNER_STATES: Dict[str, LearnerState] = {}`
  - `_LEARNING_CONTEXTS: Dict[str, LearningContext] = {}`
  - `_QUESTION_BANKS: Dict[str, QuestionBank] = {}`
- Meanwhile, `backend/routes/api.py` delegates to `LearningService`, `LearnerService`, and `KnowledgeService`, which use persistent repositories.
- This creates an architectural split-brain where tests or external tools hitting `/phase4` bypass persistent disk storage.

### Implementation Tasks
1. **Consolidate Endpoints into `/api`**:
   - Audit all endpoints in `backend/routes/phase4.py`.
   - Ensure every required operation has a canonical implementation under `/api` backed by services and repositories.
2. **Deprecate & Remove `/phase4` Route**:
   - Update tests currently targeting `/phase4` (`tests/integration/test_phase5_integration.py`) to hit `/api/learners/activity-response`.
   - Unmount `phase4.router` from `backend/app.py`.
   - Remove or redirect `backend/routes/phase4.py`.

---

## Workstream 6: Product Cleanup

### Current State & Vulnerability Analysis
- **Demo Sources**: Mock/demo fixtures (`calculus_101`, `machine_learning`, `subj_algebra`) appear in the source list if directories exist in `storage/documents`. The product should distinguish user-uploaded documents from testing fixtures.
- **Fallback UI Assumptions**:
  - In `LearningSession.tsx`: `console.warn('Could not load authentic concept question, using fallback', err)` and `selectedOptionIdx === 0` fallback.
  - In `OnboardingWorkflow.tsx`: `correctness = optIdx === 0 ? 1.0 : 0.0` fallback.
- **Ingestion Cancellation & Progress Semantics**: No endpoint currently exists to cancel an in-flight upload job if the user abandons the flow.
- **True Source-Question Semantics**: Verify that every question served clearly displays its exact source page citation and excerpt so students always know *why* an answer is correct based on their document.

### Implementation Tasks
1. **Filter Test Fixtures from Source List**:
   - In `KnowledgeService.list_subjects()`, support filtering out test fixtures or tag them with a `"is_demo": true` badge so user documents remain distinct.
2. **Purge Fallback Language & Guessing Logic**:
   - Remove any client-side guessing (`optIdx === 0`).
   - If a question cannot be generated for a concept due to insufficient text in the document, display a graceful informative state: *"The uploaded material does not contain sufficient details to test this concept. Review the source material or select a related topic."*
3. **Job Cancellation Endpoint**:
   - Add `POST /api/sources/upload/cancel/{job_id}` to terminate worker threads and clean up temporary files.
4. **Preserve Grounded Provenance in UI**:
   - Render page number and evidence quote tags in the question review card in both `OnboardingWorkflow.tsx` and `LearningSession.tsx`.

---

## Workstream 7: Final Verification & Test Strategy

### Test Plan
1. **Frontend Production Build**:
   - Execute `npm run build` in `frontend/` to confirm zero TypeScript compilation errors.
2. **Unit & Integration Regression Suite**:
   - Run `pytest -v` across all test suites, verifying 100% pass rate.
3. **Server-Side Evaluation E2E Test**:
   - Add tests in `tests/integration/test_server_side_evaluation.py` verifying that sending invalid options or tampering with payloads fails gracefully and that `correct_answer` is never leaked before submission.
4. **AI Tutor Retrieval & Grounding Test**:
   - Add tests in `tests/unit/test_tutor_grounding.py` verifying BM25 retrieval, prompt construction, and citation verification in both mock and live LLM modes.
5. **Durable Persistence & Restart Test**:
   - Add tests verifying that `IdempotencyTracker` and `IngestionJobs` persist across class re-instantiation and simulated server restarts.
6. **Concurrent Submissions Test**:
   - Simulate 10 simultaneous activity submissions for the same learner using `asyncio` / `concurrent.futures`, verifying zero race conditions and exact BKT state consistency.
7. **Live Groq LLM Verification**:
   - Verify an end-to-end ingestion and study session using a live `GROQ_API_KEY`.
