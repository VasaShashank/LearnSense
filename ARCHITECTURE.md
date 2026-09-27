# TAPROOT — System Architecture

## Overview

TAPROOT is structured into six modular phases working as a single coherent adaptive learning pipeline:

```text
Material
   ↓
Document Processing (Phase 1)
   ↓
Text Extraction & Structure
   ↓
NLP & Knowledge Representation (Phase 2)
   ↓
Knowledge Graph Construction
   ↓
Subject Initialization & Self-Assessment (Phase 4)
   ↓
Diagnostic Quiz
   ↓
Initial KT State (Phase 3)
   ↓
Gap Detection & Prioritization
   ↓
Personalized Learning Path
   ↓
Active Learning Activity
   ↓
Student Answer Evaluation
   ↓
Bayesian Knowledge Tracing (BKT) Update
   ↓
Learning Atlas Visualization (Phase 6)
```

---

## Phase Breakdown

### Phase 1: Document Ingestion
- Extract layout, multi-column text, figures, and tables from PDF documents using PyMuPDF and PDFPlumber.
- Storage: Discovered PDF artifacts stored in `storage/documents/{doc_id}/`.

### Phase 2: NLP & Educational Knowledge Representation (EKR)
- Maps extracted content into canonical concepts (`Concept`), bloom taxonomy skills (`Skill`), and prerequisite relationships (`Relationship`).
- Generates `EducationalKnowledgeRepresentation` JSON outputs.

### Phase 3: Learner Modeling & Knowledge Tracing
- Implements Bayesian Knowledge Tracing (BKT) updating mastery $P(L_t)$ upon student responses:
  $$P(L_{t|obs}) = \frac{P(L_t) \cdot P(Obs|L_t)}{P(Obs)}$$
  $$P(L_{t+1}) = P(L_{t|obs}) + (1 - P(L_{t|obs})) \cdot P(T)$$
- Adaptive question bank and chapter assessment engine using Information Gain Policy.

### Phase 4: Initialization, Gap Detection & Path Planning
- **Self-Assessment**: Learners mark concepts as `KNOW`, `DONT_KNOW`, or `UNANSWERED`.
- **Diagnostic Quiz**: Runs strictly on `KNOW` concepts. If zero concepts reported as `KNOW`, diagnostic is skipped without setting mastery to 0.
- **Gap Detection**: Classifies gaps into `LOW_MASTERY`, `INSUFFICIENT_EVIDENCE`, `WEAK_PREREQUISITE`, and `HIGH_DOWNSTREAM_IMPACT`.
- **Cycle-Safe Planner**: Performs prerequisite-aware topological sorting and selects active learning targets.

### Phase 5: Validation, Reliability & Idempotency
- Input file validation (size, magic header, corrupt PDF, zero pages, password protection).
- Duplicate response submission prevention using `IdempotencyTracker` with `request_id`.
- Recovery logging and bounded retry handling.

### Phase 6: Student Application & Learning Atlas
- Unified FastAPI backend application layer isolators (`backend/services/`).
- Modern React + TypeScript + Vite frontend with Interactive Learning Atlas (`@xyflow/react`), X-Ray Concept Inspector, AI Tutor, and Source Library.
