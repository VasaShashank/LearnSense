# Taproot — Phase 3 Architectural & Default Parameter Decisions

This document details key engineering decisions, default parameter selections, and threshold justifications across **Taproot Phase 3 (Adaptive Learning Engine & Learner Modeling)** and its interface with Phase 1 and Phase 2.

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
| **Resource Recommender (`ResourceRecommender`)** | Minimum Match Score | `0.60` | Minimum semantic and notation equivalence score for suggesting external resources. |

---

## 3. Live LLM Generation & Zero-Template Contract

### Dynamic Live Question & Distractor Engine
- **No Hardcoded Options**: Practice quiz questions and distractors are generated dynamically using Groq LLM (LLaMA 3.3 70B Versatile / GPT-OSS 120B).
- **Eliminated Replay Mock Interception**: When `GROQ_API_KEY` is present and active, mock replay caches are bypassed to guarantee fresh, domain-grounded questions.
- **Dual-Model Rate Limit Fallback**: Automatically retries 429 rate limit spikes with dual-model backoff (`openai/gpt-oss-120b` ↔ `openai/gpt-oss-20b`).
- **Comprehensive Pedagogical Study Guides**: In addition to quizzes, generates university-grade study modules:
  1. *Core Theory & Conceptual Foundation*
  2. *Intuitive Mental Model & The "Why"*
  3. *Governing Equations & Invariant Rules*
  4. *Step-by-Step Worked Problems*
  5. *Common Traps & Student Misconceptions*
  6. *Key Takeaway Banners*

---

## 4. Notation-Matched External Resource Recommender

- **`ResourceService` & `ResourceRecommender`**:
  - Automatically recommends external learning resources (e.g. 3Blue1Brown, Khan Academy, MIT OpenCourseWare) grounded in concept semantics and notation systems.
  - Matches symbol systems (e.g., Leibniz notation $\frac{dy}{dx}$ vs. Lagrange notation $f'(x)$) to ensure students receive resources aligned with their uploaded materials.
  - Curated resources are stored in `storage/resources/` with verified educational metadata.

---

## 5. Question Provenance Rules

Every question in the persistent bank maintains strict provenance (`QuestionSourceType`):
* `SOURCE`: Directly extracted from user material via Phase 2 `AssessableItem`s.
* `GENERATED`: LLM-generated based on Phase 2 `EducationalKnowledgeRepresentation` course concepts.
* `VARIANT`: LLM-generated variation of a `SOURCE` or `GENERATED` item.

Deduplication (`QuestionBankDeduplicator`) utilizes fingerprint hashing on normalized text strings to prevent duplicate questions from entering the persistent bank.
