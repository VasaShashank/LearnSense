# LearnSense — Complete Implemented System Architecture & Technical Record

This document provides a comprehensive, rigorous technical accounting of all architectural layers, subsystems, algorithms, data schemas, and user interfaces implemented across **Phases 1 through 7** in the **LearnSense / TAPROOT** codebase.

---

## 1. System Vision & Foundational Invariants

LearnSense is a local-first, privacy-respecting, CPU-friendly AI adaptive learning system that transforms arbitrary educational documents (textbooks, lecture slides, notes, assignments) into structured knowledge graphs, tracks individual mastery via Bayesian Knowledge Tracing (BKT), diagnoses knowledge gaps, generates cycle-safe learning paths, and powers interactive mastery visualization.

### Core Non-Negotiable Invariants Implemented Across the System
1. **Provenance-Grounded Generation (Zero-Hallucination Contract)**: All concept explanations, questions, and learning content must be directly anchored in retrieved passages with verified source citations (`document_id`, `page_number`, `block_id`, `quote`). If evidence cannot be retrieved, the system raises a typed error rather than inventing content.
2. **Cycle-Safe Knowledge Topology**: Directed acyclic graph (DAG) invariants are strictly enforced via Tarjan's strongly connected components algorithm and feedback-arc cycle breaking. Prerequisite graphs never contain circular dependencies.
3. **Evidence-Separated Initialization**: Self-reported learner assessments (`KNOW`, `DONT_KNOW`, `UNANSWERED`) are stored in distinct session structures and never conflated with objective Bayesian Knowledge Tracing evidence.
4. **Idempotent State Mutations**: Student activity submissions are guarded by request tokens to prevent double-counting Bayesian updates upon network retries or duplicate UI submissions.
5. **Resilient Local Persistence**: Atomic writes (`tempfile` + `os.replace`) safeguard JSON and SQLite repositories against file corruption during process termination.

---

## 2. Phase-by-Phase Technical Breakdown

```
+-----------------------------------------------------------------------------------+
|                            Phase 1: Ingestion & Extraction                        |
|  Multi-Format Parsers (PDF, PPTX, DOCX, IMG) -> Page Classifier -> OCR -> Math   |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|               Phase 2: NLP & Educational Knowledge Representation (EKR)          |
|    Concept Extraction -> Bloom Skills -> Prerequisite Graph -> Tarjan DAG        |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                 Phase 4: Subject Initialization & Path Planning                  |
|    Self-Assessment -> Diagnostic Quiz -> Gap Detection -> Topological Planner     |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|             Phase 3: Learner Modeling, BKT & Provable Question Engine             |
|   Bayesian Knowledge Tracing -> BM25 Evidence Index -> Live Groq Generation       |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                     Phase 5: Validation, Sandbox & Security                       |
|   Magic Byte Sanitizer -> Prompt Injection Guard -> Idempotency -> Boundary Check |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                       Phase 6: Reactive Student Experience                        |
|   Interactive React Flow Atlas -> X-Ray Concept Inspector -> Live Study Session   |
+-----------------------------------------------------------------------------------+
```

---

### Phase 1: Ingestion & Multi-Format Document Processing

#### 1. File Ingestion & Format Dispatcher (`ingestion/`)
- **`ingestion/pipeline.py` (`IngestionPipeline`)**:
  - Validates file headers, file size (max 500MB), and format signatures.
  - Automatically dispatches to format-specific extractors:
    - **PDF**: PyMuPDF (`fitz`) layout analysis + `pdfplumber` for tabular structures.
    - **DOCX**: `python-docx` semantic run extraction.
    - **PPTX**: `python-pptx` extracting slide hierarchy, title headers, shapes, and presenter notes.
    - **PNG / JPG**: Direct OCR pipeline routing with synthetic layout structure.
  - Outputs a standardized `StructuredDocument` artifact with normalize coordinates (`[x0, y0, x1, y1]` in 0–1000 range).

#### 2. Page Classification & Inspection (`ingestion/inspector.py`)
- Employs a multi-signal classifier to categorize pages before heavy processing:
  - **Blank Detection**: Ink density $< 0.001$, character count $< 10$, vector count $< 5$.
  - **Native Digital Text**: `char_count > 0` with low garbage token ratio.
  - **Hybrid**: Native text accompanied by image coverage $\ge 25\%$.
  - **Scanned**: True scanned page (`char_count == 0` with image coverage $\ge$ threshold) or corrupt font encodings (`garbage_ratio \ge 0.35`).
- **50-DPI Thumbnail Optimization**: Generates lightweight 50-DPI renders for ink density metrics, avoiding multi-megabyte 150-DPI memory spikes on 100+ page textbooks.

#### 3. Content Extraction Engines (`extraction/`)
- **Native Text (`extraction/native.py`)**: Multi-column text sorting, font size classification for heading hierarchies (H1–H3), and reading order resolution.
- **OCR Engine (`extraction/ocr.py`)**: Tesseract OCR at 300 DPI with orientation detection and garbage-string filtering.
- **Math Extraction (`extraction/math.py`)**: Identifies inline and block equations using regex/symbol detection, converting representations to LaTeX with SHA-256 asset tracking.
- **Table Extraction (`extraction/tables.py`)**: Recovers tabular grids via `pdfplumber`, reconstructing Markdown tables while capturing fallback raster crops.
- **Figure & Asset Extraction (`extraction/figures.py`)**: Isolates diagrams and illustrations, storing cropped PNG assets under `storage/documents/{doc_id}/assets/`.

---

### Phase 2: NLP & Educational Knowledge Representation (EKR)

#### 1. Concept & Entity Discovery (`phase2/`)
- Extracts educational concepts (`Concept`), learning objectives, and Bloom's taxonomy skills (`Skill`).
- Canonicalizes entity naming (resolves acronyms, handles singular/plural variants, removes spurious casing).
- Associates each concept with primary definition spans, chapter IDs, and evidence references.

#### 2. Prerequisite Graph Construction & Cycle Elimination
- Identifies prerequisite edges ($A \rightarrow B$ where $A$ must be understood to master $B$).
- **Tarjan's Strongly Connected Components (SCC) Algorithm**: Detects all cycles within prerequisite graphs.
- **Cycle-Breaking Heuristics**: Breaks cycles deterministically by removing edges with the lowest semantic confidence or earliest occurrence in the textbook structure, ensuring the resulting graph is a strict DAG.
- **Noisy-OR Aggregation**: Computes prerequisite readiness using probabilistic combination over parent concepts.

---

### Phase 3: Learner Modeling, BKT & Provable Question Engine

#### 1. Bayesian Knowledge Tracing (BKT) (`phase3/learner/kt.py`)
Tracks student mastery probability $P(L_t)$ per concept using the standard 4-parameter BKT model:
- $P(L_0)$: Prior probability of mastery (default: $0.10$).
- $P(T)$: Probability of transition from unlearned to learned state after an opportunity (default: $0.15$).
- $P(G)$: Guess probability (student answers correctly despite not knowing; default: $0.20$).
- $P(S)$: Slip probability (student knows the concept but answers incorrectly; default: $0.10$).

**Observation Update**:
$$P(L_{t|obs=1}) = \frac{P(L_t) \cdot (1 - P(S))}{P(L_t) \cdot (1 - P(S)) + (1 - P(L_t)) \cdot P(G)}$$

$$P(L_{t|obs=0}) = \frac{P(L_t) \cdot P(S)}{P(L_t) \cdot P(S) + (1 - P(L_t)) \cdot (1 - P(G))}$$

**Transition Update**:
$$P(L_{t+1}) = P(L_{t|obs}) + (1 - P(L_{t|obs})) \cdot P(T)$$

- **Bounded Certainty**: Enforces numerical bounds ($0.001 \le P(L) \le 0.999$) to prevent saturation and allow recovery.

#### 2. BM25 Evidence Retrieval Engine (`phase3/retrieval/evidence_retriever.py`)
- Indexes every semantic text block of the `StructuredDocument` with page and section coordinates.
- Tokenizes and cleans content (removing English function stop-words and ordinal noise like "Chapter 3").
- Computes standard BM25 scores:
  $$\text{Score}(D, Q) = \sum_{t \in Q} \text{IDF}(t) \cdot \frac{f(t, D) \cdot (k_1 + 1)}{f(t, D) + k_1 \cdot \left(1 - b + b \cdot \frac{|D|}{\text{avgdl}}\right)}$$
- Provides exact source evidence snippets with page numbers and block IDs to question and content builders.

#### 3. Question Bank Builder & Live LLM Generation (`phase3/question_bank/builder.py`)
- **Zero-Template Contract**: Questions are dynamically created by the LLM (Groq / LLaMA 3.3 70B Versatile) grounded strictly on retrieved source passages.
- **Citation Validation**: Rejects any generated question whose citations do not match real evidence blocks in the document.
- **Persisted Question Bank (`storage/question_banks/{subject_id}.json`)**: Caches validated questions to avoid redundant LLM invocations while preserving grounded provenance.

---

### Phase 4: Initialization, Gap Detection & Path Planning

#### 1. Onboarding & Self-Assessment Protocol
- Learner classifies subject concepts into three distinct categories:
  - `KNOW`: Student believes they understand the concept.
  - `DONT_KNOW`: Student acknowledges no prior understanding.
  - `UNANSWERED`: Student skips classification.
- **Diagnostic Quiz Orchestration**:
  - Restricts diagnostic questions *strictly* to concepts marked `KNOW`.
  - Concepts marked `DONT_KNOW` are never tested during initial onboarding.
  - If zero concepts are marked `KNOW`, the diagnostic quiz is bypassed entirely without penalizing the student.

#### 2. Knowledge Gap Classification (`phase4/planning/gap_detector.py`)
Categorizes student learning gaps into 4 distinct taxonomies:
1. `LOW_MASTERY`: Concept tested with evidence showing $P(L) < 0.40$.
2. `INSUFFICIENT_EVIDENCE`: Concept marked `KNOW` or `UNANSWERED` without enough observations to substantiate mastery.
3. `WEAK_PREREQUISITE`: Student attempts an advanced concept while one or more foundational prerequisites have $P(L) < 0.60$.
4. `HIGH_DOWNSTREAM_IMPACT`: Unmastered foundational concept blocking a large subtree of downstream topics.

#### 3. Prerequisite-Aware Path Planning (`phase4/planning/path_generator.py`)
- Performs cycle-safe topological sorting over the knowledge graph.
- Orders target concepts so learners always address missing foundational prerequisites before attempting dependent target concepts.

---

### Phase 5: Reliability, Validation & Idempotency

- **Input File Validator (`phase5/validation/input_validator.py`)**: Checks file magic bytes, MIME types, corruption signatures, and maximum file sizes.
- **Prompt Injection Defense (`tests/security/`, `backend/services/tutor_service.py`)**: Sanitizes student queries against system prompt overrides ("Ignore previous instructions", etc.).
- **Idempotency Tracker (`phase5/validation/learner_state_validator.py`)**: Intercepts retry attempts and returns existing results without re-applying Bayesian updates.
- **Knowledge Graph Invariant Validator (`phase5/validation/knowledge_graph_validator.py`)**: Verifies DAG properties and connectivity before graph publishing.

---

### Phase 6: Student Application & Learning Atlas

- **Unified FastAPI Backend (`backend/app.py`, `backend/routes/api.py`)**: Exposes REST endpoints for sources, subjects, atlas graph visualization, learning content, quizzes, and learner progress.
- **Asynchronous Document Ingestion (`backend/routes/api.py`)**:
  - Background worker thread executes Phase 1 $\rightarrow$ Phase 2 $\rightarrow$ Phase 3 without HTTP timeouts.
  - Immediate job dispatch returning `job_id` with real-time status polling at `/api/sources/upload/status/{job_id}`.
- **Frontend Architecture (`frontend/src/`)**:
  - **Learning Atlas (`components/atlas/LearningAtlas.tsx`)**: Built with `@xyflow/react`, rendering interactive DAG nodes with dynamic color-coding by BKT mastery (Emerald for Mastered, Amber for Developing, Slate for Unlearned).
  - **X-Ray Concept Inspector (`components/atlas/XRayInspector.tsx`)**: Inspects concept definition, mastery confidence interval, prerequisite links, and source page citations.
  - **Onboarding Workflow (`components/onboarding/OnboardingWorkflow.tsx`)**: Multi-step wizard supporting document drag-and-drop, real-time ingestion timer, self-assessment checklist, and diagnostic assessment.
  - **Learning Session Modal (`components/session/LearningSession.tsx`)**: In-depth curriculum reader with conceptual intuition, worked examples, common misconceptions, and grounded assessment problems.
  - **Contextual AI Tutor (`components/tutor/ContextualTutor.tsx`)**: Sliding panel for real-time tutoring queries.

---

### Phase 7: Graph Stress & Persistence Hardening

- **Performance Benchmarking (`tests/unit/test_phase7_graph_stress.py`)**: Tested and validated topological path generation on graphs with 10, 50, 100, and 250 concepts under cycle stress.
- **Atomic Persistence (`storage/repositories.py`)**: Atomic file replacement prevents truncated writes during disk or server interruptions.
- **Master Regression Suite**: 89 automated unit, integration, and failure test cases passing with zero errors.

---

## 3. Storage Directory Layout

```
storage/
├── documents/
│   └── {document_id}/
│       ├── raw.pdf / raw.pptx / raw.docx
│       ├── structured_document.json
│       └── assets/
│           ├── fig_p0001_00.png
│           └── tab_p0003_01.png
├── learning_contexts/
│   └── {subject_id}.json
├── question_banks/
│   └── {subject_id}.json
├── learner_states/
│   └── {learner_id}.json
└── sessions/
    └── {session_id}.json
```

---

## 4. Current State Matrix

| Subsystem | Implemented Status | Verification |
|---|---|---|
| Phase 1 Document Extraction (PDF, PPTX, DOCX, PNG) | Fully Implemented & Optimized (50-DPI thumbs) | Unit & Failure Tests Passing |
| Phase 2 Educational Knowledge Graph (EKR) & DAG | Fully Implemented (Tarjan SCC + Cycle Breaking) | Unit Tests Passing |
| Phase 3 Bayesian Knowledge Tracing (BKT) | Fully Implemented (Exact Probabilistic Formula) | Unit Tests Passing |
| Phase 3 BM25 Retrieval & Grounded Questions | Fully Implemented (Zero-Template Engine) | Provenance Tests Passing |
| Phase 4 Self-Assessment & Diagnostic Orchestration | Fully Implemented (KNOW-restricted quizzes) | Integration Tests Passing |
| Phase 4 Gap Detection (4 Categories) & Planner | Fully Implemented (Topological Prerequisite Path) | Unit Tests Passing |
| Phase 5 Validation, Sandboxing & Idempotency | Fully Implemented (In-memory token tracker) | Unit Tests Passing |
| Phase 6 React Flow Atlas & Learning Session UI | Fully Implemented & Responsive | Vite Build Passing |
| Phase 6 Async Upload & Real-Time Job Polling | Fully Implemented (Threaded Ingestion) | API Tests Passing |
| Test Suite Health | 89 / 89 Unit and Integration Tests Passing | `pytest -v` Green |
