# Taproot — Phase 3 Architectural & Default Parameter Decisions

This document details key engineering decisions, default parameter selections, and threshold justifications across **Taproot Phase 3 (Adaptive Learning Engine)** and its interface with Phase 1 and Phase 2.

---

## 1. Justification of `mastery_threshold = 0.5`

In `LearningContext.get_upstream_weak_prerequisites(target_concept_id, learner_state, mastery_threshold=0.5)`, the default threshold for identifying a weak prerequisite is set to **`0.5`**.

### Math & Bayesian Knowledge Tracing (BKT) Theory
In standard Bayesian Knowledge Tracing (Corbett & Anderson, 1994):
* $P(L_t) \in [0.0, 1.0]$ represents the probability that a learner has mastered a specific concept.
* $0.5$ is the exact **indifference boundary** (neutral odds ratio $1:1$).
* When $P(L_t) < 0.5$, the model estimates it is more probable that the student **does not** know the concept than that they do know it ($P(\text{unlearned}) > P(\text{learned})$).
* Therefore, $0.5$ serves as the mathematically sound threshold for flagging an upstream prerequisite concept as a **knowledge gap** triggering remediation or diagnostic review.

*Note: The parameter `mastery_threshold` is configurable in method signatures so callers or future Phase 4 policy modules can enforce stricter mastery standards (e.g. `0.75` or `0.80` for high-stakes concepts).*

---

## 2. Summary of Default Parameters & Hardcoded Constants

| Module / Component | Parameter / Constant | Default Value | Rationale & Specification Basis |
| :--- | :--- | :--- | :--- |
| **Knowledge Tracing (`KnowledgeTracer`)** | `p_init` | `0.3` | Standard default prior probability of knowing an unassessed concept. |
| **Knowledge Tracing (`KnowledgeTracer`)** | `p_transit` ($P(T)$) | `0.15` | Expected probability of transitioning from unlearned to learned state per learning item. |
| **Knowledge Tracing (`KnowledgeTracer`)** | `p_slip` ($P(S)$) | `0.1` | Probability of making a random slip/mistake despite knowing the concept. |
| **Knowledge Tracing (`KnowledgeTracer`)** | `p_guess` ($P(G)$) | `0.25` | Probability of guessing correctly on a 4-option MCQ despite not knowing the concept ($1/4 = 0.25$). |
| **Knowledge Tracing (`KnowledgeTracer`)** | Mastery Bounds | `[0.01, 0.99]` | Prevents probability locking at $0.0$ or $1.0$, maintaining sensitivity to future evidence. |
| **Topic Mini-Quiz (`DynamicMiniQuizGenerator`)** | `target_count` | `6` (range 5–8) | Specified in Prompt §19: Target of 5–8 questions per small topic mini-quiz for optimal cognitive load. |
| **Chapter Assessment (`AssessmentConstraints`)** | `min_questions` | `20` | Specified in Prompt §23 & §26: Minimum question target for chapter-level assessment. |
| **Chapter Assessment (`AssessmentConstraints`)** | `max_questions` | `25` | Specified in Prompt §23 & §26: Maximum question target for chapter-level assessment. |
| **Chapter Assessment (`AssessmentConstraints`)** | `time_limit_seconds` | `1800.0` (30 min) | Configurable hard constraint for time-bounded adaptive assessments. |
| **Answer Evaluation (`AnswerEvaluator`)** | Numerical Tolerance | `0.02` (2%) | Allows floating-point calculation variance within 2% margin. |
| **Answer Evaluation (`AnswerEvaluator`)** | Short Answer Overlap | `0.6` (60%) | Word overlap/ngram threshold for short-answer semantic correctness scoring. |
| **LLM Adapter (`Phase3LLMAdapter`)** | Replay Cache Directory | `.cache/llm_replay` | Standard directory for record/replay caching to eliminate duplicate API costs during testing. |

---

## 3. API Key & LLM Fallback Architecture

### How the system handles LLM generation with/without API Keys

1. **Environment Auto-Detection:**
   - `Phase3LLMAdapter` automatically inspects `.env` files and `os.environ` for `GROQ_API_KEY` or `OPENAI_API_KEY`.
   - If `GROQ_API_KEY` is present, it defaults to `llama-3.3-70b-versatile` via Groq's endpoint.
   - If `OPENAI_API_KEY` is present, it defaults to `gpt-4o-mini` via OpenAI's endpoint.

2. **Replay Cache First:**
   - Before hitting live endpoints, the adapter checks `.cache/llm_replay` using SHA-256 hashes of the prompt, model, and configuration. If a cached response exists, it returns immediately without network calls.

3. **Deterministic Mock Fallback:**
   - If no API key is set, or if an API key is invalid/times out/encounters network errors, `Phase3LLMAdapter` falls back to `MockLLMAdapter`.
   - `MockLLMAdapter` generates valid, schema-compliant JSON questions grounded in the user's uploaded Phase 2 concept metadata.
   - This guarantees that local test suites, offline laptop execution, and automated CI pipelines run reliably without needing developer API keys.

---

## 4. Question Provenance Rules

Every question in the persistent bank maintains strict provenance (`QuestionSourceType`):
* `SOURCE`: Directly extracted from user material via Phase 2 `AssessableItem`s.
* `GENERATED`: LLM-generated based on Phase 2 `EducationalKnowledgeRepresentation` course concepts.
* `VARIANT`: LLM-generated variation of a `SOURCE` or `GENERATED` item.

Deduplication (`QuestionBankDeduplicator`) utilizes fingerprint hashing on normalized text strings to prevent duplicate questions from entering the persistent bank.
