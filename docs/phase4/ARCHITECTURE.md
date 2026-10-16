# Phase 4 Architecture: Personalization, Teacher Hub & Institutional Layer

## 1. Overview

Phase 4 defines the **intelligence, personalization, path planning, and educator orchestration layers** operating on top of Taproot Phase 1–3 infrastructure.

```text
Student Workflow:
  Subject Selection → Self-Assessment → Diagnostic Quiz → KT State → Gap Detection → Prerequisite Path → Active Learning

Educator Workflow (Teacher Hub):
  Class Cohort Selection → Aggregate Mastery Calculation → Gap Prioritization → Intervention Planning → Resource Assignment

Institutional Workflow (Admin Portal):
  Organization & Department Setup → Seat License Allocation → Cross-Class Telemetry → Benchmark Evaluation
```

---

## 2. Student Personalization & Path Planning Modules

### 1. Concept Self-Assessment (`phase4/knowledge_initialization/concept_self_assessment.py`)
- Concepts are categorized as `KNOW`, `DONT_KNOW`, or `UNANSWERED`.
- **Invariance Rule:** Self-reported status does **NOT** directly mutate BKT mastery probability.
- `KNOW`: Subject to objective diagnostic assessment.
- `DONT_KNOW`: Candidate for gap analysis and foundational learning targets.
- `UNANSWERED`: Treated as `UNKNOWN / NOT_ASSESSED`.

### 2. Diagnostic Assessment Orchestration (`phase4/knowledge_initialization/diagnostic_orchestrator.py`)
- Diagnostic questions are generated/selected **ONLY** from concepts selected as `KNOW`.
- Zero `KNOW` concepts selected (e.g. learner marks "I don't know anything"): Diagnostic is bypassed; starting concept is derived dynamically from graph root nodes.
- Objective diagnostic performance updates Phase 3 `KnowledgeTracer` state.

### 3. Knowledge Gap Detection & Reasoning (`phase4/gaps/`)
- Detects four explicit gap categories:
  - `LOW_MASTERY`: Mastery < `MASTERY_THRESHOLD` (0.5).
  - `INSUFFICIENT_EVIDENCE`: Attempt count < `MIN_EVIDENCE_COUNT` or uncertainty > `UNCERTAINTY_THRESHOLD`.
  - `WEAK_PREREQUISITE`: Required by higher-level concept but prerequisite is weak.
  - `HIGH_DOWNSTREAM_IMPACT`: Weak concept affecting 2 or more downstream concepts.
- Explanations are generated deterministically from application state without LLM hallucination.

### 4. Deterministic Gap Prioritization (`phase4/gaps/gap_prioritizer.py`)
- Centralized linear weighted scoring:
  - `MASTERY_WEIGHT = 0.35`
  - `UNCERTAINTY_WEIGHT = 0.20`
  - `PREREQUISITE_WEIGHT = 0.25`
  - `DOWNSTREAM_IMPACT_WEIGHT = 0.15`

### 5. Path Planning & Graph Resolution (`phase4/planning/`)
- `PrerequisiteResolver`: Identifies foundational graph roots (in-degree = 0) and performs cycle-safe topological sorting (Kahn's Algorithm with cycle fallback).
- `LearningPathGenerator`: Generates prerequisite-first learning paths capped at `MAX_LEARNING_PATH_LENGTH = 10`.

---

## 3. Teacher Hub & Collective Teaching Optimizer (`phase4/teacher/`)

### 1. Teaching Optimizer Engine (`phase4/teacher/optimizer.py`)
- **Class Mastery Aggregation**: Computes mean mastery, median, variance, and distribution buckets across all enrolled students for every curriculum concept.
- **Critical Knowledge Gaps**: Identifies concept bottlenecks where more than 30% of the class exhibits `LOW_MASTERY` or `WEAK_PREREQUISITE` status.
- **Automated Intervention Generator**:
  - Automatically synthesizes classroom intervention lesson plans.
  - Matches struggling topics with external learning videos (Khan Academy, 3Blue1Brown, MIT OCW).
  - Generates recommended group activities and targeted mini-remediation quizzes.

### 2. Educator Models (`phase4/teacher/models.py`)
- `ClassCohort`: Represents an active classroom or section.
- `ClassKnowledgeState`: Aggregated class analytics and distribution percentiles.
- `InterventionPlan`: Prescriptive remediation actions and resource assignments.
- **Privacy & FERPA Compliance**: Supports standalone educator mode with irreversible student de-identification (`Student #104` instead of personal names).

---

## 4. Institutional Multi-Tenant B2B Portal (`phase4/institution/`)

### 1. Organizational Models (`phase4/institution/models.py`)
- `Organization`: Multi-tenant institution representation (University, School District, Learning Center).
- `Department`: Academic division (Computer Science, Mathematics, Engineering).
- `SeatLicense`: Allocation tracking for active seats, faculty licenses, and expiration quotas.
- `RoleEnum`: Role-Based Access Control (`ADMIN`, `INSTRUCTOR`, `LEARNER`).

### 2. Enterprise Telemetry & Benchmarking
- Cross-department learning velocity metrics.
- Cohort progression rates against institutional standards.
- Centralized administrative seat reallocation and course provisioning.

---

## 5. Configuration Settings (`phase4/config.py`)
All parameters, weights, and thresholds are centralized in `Phase4Config` with full mathematical rationales.
