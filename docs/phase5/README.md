# Taproot Phase 5 — Validation, Reliability & Recovery Documentation

## 1. Overview
Phase 5 introduces a robust boundary validation, error handling, bounded recovery, and observability layer on top of Taproot Phase 1–4. The goal is to make the existing pipeline safe against invalid or low-confidence outputs without duplicating or rewriting existing intelligence algorithms.

---

## 2. Core Architecture
The Phase 5 validation layer operates around key system boundaries:

```text
PDF Input ➔ Input Validation ➔ Extraction ➔ Extraction Validation ➔ NLP ➔ NLP Confidence Validation ➔ Knowledge Graph ➔ Graph Sanity/Cycle Validation ➔ Learner State ➔ State/Idempotency Validation ➔ Diagnostic/Planning ➔ Path/Target Validation
```

---

## 3. Validation Boundaries & Validators

| Boundary | Validator Class | Key Checks | Recovery / Fallback |
| :--- | :--- | :--- | :--- |
| **Input** | `InputValidator` | File extension (.pdf), size limit (`MAX_FILE_SIZE_BYTES`), PyMuPDF load checks, magic bytes, page limits | Reject invalid types; attempt PyMuPDF clean repair on corrupted PDFs. |
| **Extraction** | `ExtractionValidator` | Page count, text yield (`MIN_USABLE_TEXT_LENGTH`), empty page ratio, page status | Low/zero text triggers bounded OCR or engine fallback. |
| **NLP** | `NLPValidator` | Missing IDs, non-empty names, duplicate entity names, low confidence threshold (`NLP_CONFIDENCE_THRESHOLD`), self-references | Bounded reprocessing/regeneration via `MAX_NLP_RETRIES`. |
| **Knowledge Graph** | `KnowledgeGraphValidator` | Broken concept references, self-referencing edges, orphan concepts, prerequisite cycles | Iterative cycle removal (`sanitize_and_break_cycles`) guarantees DAG for planner. |
| **Question** | `QuestionValidator` | Non-empty text, MCQ option completeness, MCQ duplicate choices, correct answer matching, target concept alignment, difficulty bounds | Bounded regeneration or fallback to pre-existing validated question bank items. |
| **Learner State** | `LearnerStateValidator` | Score range [0.0, 1.0], concept existence, non-negative attempt counts, response submission idempotency | Idempotent token check prevents double-updating Bayesian Knowledge Tracing. |
| **Phase-4 Planning** | `PlanningValidator` | Self-assessment validity, restriction of diagnostic quiz strictly to `KNOW` concepts, learning path node uniqueness | Re-filter diagnostic quiz items or fallback to foundational concept start for zero-evidence learners. |

---

## 4. Failure Classifications

Every failure or validation event is classified into one of three recovery states:

1. **`RECOVERABLE`**: Transient or fixable failures where retrying or executing a fallback strategy yields a valid result (e.g., damaged PDF cross-reference table, low-confidence question generation, broken graph cycle).
2. **`PARTIALLY_RECOVERABLE`**: Non-fatal structural issues where processing can continue with degraded scope or flagged warnings (e.g., low NLP confidence on non-critical concepts, partial empty pages).
3. **`NON_RECOVERABLE`**: Fatal input errors or invalid payloads where processing must stop immediately with a clear user-facing error message (e.g., non-PDF upload, missing required fields, password-encrypted PDF).

---

## 5. Configuration Settings (`Phase5Config`)

Centralized in `phase5/config/phase5_config.py`:

* `MAX_PDF_RETRIES`: `2`
* `MAX_NLP_RETRIES`: `2`
* `MAX_QUESTION_RETRIES`: `3`
* `MAX_RECOVERY_ATTEMPTS`: `3`
* `NLP_CONFIDENCE_THRESHOLD`: `0.70`
* `MIN_USABLE_TEXT_LENGTH`: `100`
* `MAX_FILE_SIZE_BYTES`: `104857600` (100 MB)
* `MAX_PAGE_COUNT`: `500`
* `VALIDATION_STRICT_MODE`: `False`

---

## 6. Observability
Validation events, retries, cycle sanitizations, and idempotency hits are logged using `ValidationEventLogger` with structured JSON context (`document_id`, `learner_id`, `concept_id`, `question_id`, `attempt_id`).
