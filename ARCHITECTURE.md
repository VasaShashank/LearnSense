# TAPROOT / LearnSense — System Architecture

## 1. High-Level Architecture Overview

LearnSense is structured into modular phases working together as a single coherent adaptive learning, teaching intelligence, and institutional management pipeline:

```text
Uploaded Educational Material (PDF, PPTX, DOCX, IMG)
         ↓
Document Ingestion & Multi-Format Extraction (Phase 1)
         ↓
NLP & Educational Knowledge Representation (Phase 2)
  ├── 9-Stage EKR Pipeline
  ├── Tarjan SCC Cycle-Breaking (Strict DAG)
  └── Semantic Topic Extractor (Topic Clusters & Subheading DAGs)
         ↓
Subject Initialization & Diagnostic Onboarding (Phase 4)
  ├── Concept Self-Assessment (KNOW / DON'T KNOW / UNANSWERED)
  └── Objective Diagnostic Quiz (Restricted strictly to KNOW concepts)
         ↓
Bayesian Knowledge Tracing & Learner Modeling (Phase 3)
  ├── Exact BKT Posterior Update
  ├── Dynamic Live Groq Question & Distractor Engine
  ├── In-Depth Pedagogical Study Guide Generator
  └── Notation-Matched Video Recommender (Khan Academy, 3Blue1Brown, MIT OCW)
         ↓
Deterministic Gap Prioritization & Cycle-Safe Planning (Phase 4)
  ├── 4-Taxonomy Gap Classification
  └── Kahn's Algorithm Prerequisite-First Learning Paths
         ↓
Validation, Reliability & Idempotency Sandbox (Phase 5)
  ├── 500 MB & 3,000 Page High-Capacity Bounds
  ├── Dual-Model Transient 429 Recovery
  └── In-Memory & SQLite Idempotency Tokens
         ↓
Multi-Persona Client Workspaces (Phase 6)
  ├── Student: React Flow Learning Atlas, Topic Clusters, Concept Inspector, AI Tutor
  ├── Educator: Teacher Hub, Collective Teaching Optimizer, FERPA De-Identification
  └── Enterprise: B2B Institutional Portal, Multi-Tenant Seat License Administration
```

---

## 2. Phase-by-Phase Technical Breakdown

### Phase 1: Document Ingestion & Multi-Format Normalization
- **Multi-Format Parsers**: Direct format dispatchers for PDF (PyMuPDF & PDFPlumber), PowerPoint (`python-pptx`), Word (`python-docx`), and images (`Pillow` + OCR).
- **Extraction Fidelity**: Preserves PPTX tables as markdown grids, speaker notes as dedicated semantic blocks, and real coordinate bounding boxes.
- **High Capacity**: Supports up to 3,000 pages for university-grade textbooks.

### Phase 2: NLP & Educational Knowledge Representation (EKR)
- **9-Stage Deterministic Pipeline**: Processes blocks from normalization through role classification, candidate extraction, entity resolution, and object assembly.
- **DAG Invariant**: Uses Tarjan's Strongly Connected Components algorithm to detect and break cycles deterministically.
- **Topic Clusters & Subheading DAGs**: Extracts macro pedagogical territories and connects textbook section nodes with granular concepts.

### Phase 3: Learner Modeling, BKT & Provable Content Engine
- **Bayesian Knowledge Tracing (BKT)**:
  $$P(L_{t|obs=1}) = \frac{P(L_t) \cdot (1 - P(S))}{P(L_t) \cdot (1 - P(S)) + (1 - P(L_t)) \cdot P(G)}$$
  $$P(L_{t|obs=0}) = \frac{P(L_t) \cdot P(S)}{P(L_t) \cdot P(S) + (1 - P(L_t)) \cdot (1 - P(G))}$$
  $$P(L_{t+1}) = P(L_{t|obs}) + (1 - P(L_{t|obs})) \cdot P(T)$$
- **Dynamic Live LLM Question Engine**: Generates real domain questions, correct answers, and distractors via Groq (LLaMA 3.3 70B / GPT-OSS 120B) with dual-model burst retry.
- **Authoritative BM25 Retrieval**: Cites exact document pages and text blocks.
- **Notation-Matched Resource Recommender**: Links concepts to verified external video lessons matching notation conventions.

### Phase 4: Initialization, Planning, Teaching Optimizer & Institution
- **Diagnostic Protocol**: Self-assessment onboarding with quizzes restricted strictly to self-reported known concepts. If no concepts are marked known, diagnostics are bypassed without score penalty.
- **Gap Classification**: Detects `LOW_MASTERY`, `INSUFFICIENT_EVIDENCE`, `WEAK_PREREQUISITE`, and `HIGH_DOWNSTREAM_IMPACT`.
- **Teacher Hub & Collective Teaching Optimizer**: Aggregates class-level concept mastery, isolates cohort bottlenecks, generates automated intervention lesson plans, and supports FERPA student de-identification.
- **B2B Institutional Portal**: Multi-tenant administration, seat licensing, and cross-department analytics.

### Phase 5: Validation, Reliability & Zero-Fallback Sandboxing
- Input file validation across 6 formats, 3,000-page limit, and 500 MB capacity.
- Duplicate submission prevention using `IdempotencyTracker`.
- Dual-model rate-limit recovery (`openai/gpt-oss-120b` ↔ `openai/gpt-oss-20b`).
- Strict zero-fallback policy with fail-loud error boundaries.

### Phase 6: Modern Reactive Frontend Workspaces
- Unified FastAPI application layer with REST endpoints and asynchronous ingestion worker threads.
- Modern React 19 + TypeScript + Vite frontend powered by `@xyflow/react` (React Flow).
- Interactive Learning Atlas with Topic Cluster Nodes, Subheading DAGs, Concept Inspector drawer, Study Guides, and Persona Switcher.
