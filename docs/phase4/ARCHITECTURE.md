# Phase 4 Architecture: Knowledge Initialization, Knowledge Gaps & Personalized Learning

## Overview

Phase 4 introduces the **personalization and path planning layer** on top of Taproot Phase 1–3 infrastructure.

```text
Subject Selection
        ↓
Knowledge Initialization Check
        ↓
Concept Self-Assessment (KNOW / DON'T KNOW / UNANSWERED)
        ↓
Diagnostic Assessment (Restricted to KNOW concepts)
        ↓
Initial Knowledge Tracing (KT) State
        ↓
Knowledge Sufficiency Check
        ↓
Knowledge Gap Detection
        ↓
Gap Reasoning & Prioritization (Deterministic weighted scoring)
        ↓
Personalized Learning Path (Prerequisite-aware, cycle-safe)
        ↓
Next Learning Target Selection
        ↓
Existing Phase 3 Content / Question System
        ↓
Student Response
        ↓
Phase 3 Knowledge Tracing Update
        ↓
Phase 4 Re-plan
```

---

## Key Modules & Semantics

### 1. Concept Self-Assessment (`phase4/knowledge_initialization/concept_self_assessment.py`)
- Concepts are categorized as `KNOW`, `DONT_KNOW`, or `UNANSWERED`.
- **Crucial Rule:** Self-reported status does **NOT** directly mutate KT mastery probability.
- `KNOW`: Subject to objective diagnostic assessment.
- `DONT_KNOW`: Candidate for gap analysis and learning targets.
- `UNANSWERED`: Treated as `UNKNOWN / NOT_ASSESSED` (not assumed weak).

### 2. Diagnostic Assessment (`phase4/knowledge_initialization/diagnostic_orchestrator.py`)
- Diagnostic questions are generated/selected **ONLY** from concepts selected as `KNOW`.
- Zero `KNOW` concepts selected (e.g. learner marks "I don't know anything"): Diagnostic is bypassed; starting concept is derived dynamically from graph root nodes.
- Objective diagnostic performance updates Phase 3 `KnowledgeTracer` state.

### 3. Knowledge Sufficiency (`phase4/knowledge_initialization/knowledge_sufficiency.py`)
- Evaluates subject evidence states: `UNINITIALIZED`, `INSUFFICIENT_EVIDENCE`, `INITIALIZED`.
- Enforces `MIN_EVIDENCE_COUNT = 3`.

### 4. Knowledge Gap Detection & Reasoning (`phase4/gaps/`)
- Detects four explicit gap categories:
  - `LOW_MASTERY`: Mastery < `MASTERY_THRESHOLD` (0.5).
  - `INSUFFICIENT_EVIDENCE`: Attempt count < `MIN_EVIDENCE_COUNT` or uncertainty > `UNCERTAINTY_THRESHOLD`.
  - `WEAK_PREREQUISITE`: Required by higher-level concept but prerequisite is weak.
  - `HIGH_DOWNSTREAM_IMPACT`: Weak concept affecting 2 or more downstream concepts.
- Explanations are generated deterministically from application state without LLM fabrication.

### 5. Deterministic Gap Prioritization (`phase4/gaps/gap_prioritizer.py`)
- Uses centralized linear weighted scoring:
  - `MASTERY_WEIGHT = 0.35`
  - `UNCERTAINTY_WEIGHT = 0.20`
  - `PREREQUISITE_WEIGHT = 0.25`
  - `DOWNSTREAM_IMPACT_WEIGHT = 0.15`
- No ML or LLM ranking models used.

### 6. Path Planning & Graph Resolution (`phase4/planning/`)
- `PrerequisiteResolver`: Identifies foundational graph roots (in-degree = 0) and performs cycle-safe topological sorting (Kahn's Algorithm with cycle fallback).
- `LearningPathGenerator`: Generates prerequisite-first learning paths capped at `MAX_LEARNING_PATH_LENGTH = 10`.
- Mastered concepts are filtered out.

---

## Configuration (`phase4/config.py`)

All thresholds and weights are centralized in `Phase4Config` with documented design rationales.
