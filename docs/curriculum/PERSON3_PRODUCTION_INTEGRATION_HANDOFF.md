# LearnSense — Person 3 Production Integration Handoff

**Author:** Person 2 Knowledge Graph & Curriculum Team  
**Recipient:** Person 3 Adaptive Learning & Modeling Team  
**Date:** 2026-10-23  
**Status:** Approved for Implementation (Main Repo Verified: `COMPATIBLE FOR TESTING`)  
**Target External Repository:** `References/LearnSense-Person3-FINAL` (read-only reference)

---

## 1. Executive Summary

This handoff specifies the exact steps, call sites, and patch patterns required to integrate Person 2's canonical curriculum subsystem into Person 3's external production service pipeline.

The canonical curriculum specification (`jee_class_11_12`, syllabus `2026.jee.v1`, fingerprint `0e2f5b8c9d1a3e74`) provides:
- **62/62 (100%)** canonical concept nodes corresponding to all simulator and AKT vocabulary concepts.
- **61/61 (100%)** structurally valid prerequisite edges in a strict directed acyclic graph.
- Complete duck-type compliance with Person 3's `PrerequisiteGraph` and `ConceptNode` interfaces.
- Safe, atomic mastery translation through `translate_mastery_profile()` and `CanonicalLearnerStateService`.

All main-repository integration components and an end-to-end 10-scenario integration test harness have been implemented and pass 100% (`tests/integration/test_person2_person3_runtime_integration.py`).

Because `References/LearnSense-Person3-FINAL` is read-only, Person 3 must apply the external patches specified in this document to achieve `COMPATIBLE FOR PRODUCTION`.

---

## 2. Target Files and Functions in Person 3 Repository

| Target File | Target Function / Class | Current Behavior | Required Production Change |
|---|---|---|---|
| `src/service.py` | `LearnSensePersonalizationService.__init__` (lines 39–50) | Defaults to `load_knowledge_graph_from_csv()` | Require injected `knowledge_graph` or raise `CanonicalGraphUnavailableError` in production mode. |
| `src/api.py` | `create_app` (lines 118–136) | Calls `LearnSensePersonalizationService(store=store)` with no graph | Use `ProductionCurriculumIntegrationFactory` to instantiate and inject the canonical adapter. |
| `src/akt_inference.py` | `_prepare_sequence_tensors` (line 197) | `concept_to_index.get(item.concept_id, 0)` falls back to index 0 | Validate `item.concept_id` against vocabulary; raise `UnknownSimulatorIdError` instead of falling back to 0. |
| `src/akt_inference.py` | `record_interaction` (lines 156–178) | Ingests unvalidated concept IDs | Validate concept ID against `vocabulary.concept_to_index` before appending to interaction history. |
| `src/state.py` | `LearnerStateService.__init__` (line 79) | Defaults to `load_knowledge_graph_from_csv()` | Require injected graph; do not silently read CSV. |
| `src/state.py` | `process_attempt` (lines 250–325) | Mutates state with simulator IDs | Use `CanonicalLearnerStateService` to atomically translate simulator profile to canonical IDs before persisting. |

---

## 3. Why Current Behavior is Unsafe in Production

1. **Silent Fallback to Synthetic CSV:**
   In `src/service.py:47`:
   ```python
   self.knowledge_graph = knowledge_graph or load_knowledge_graph_from_csv()
   ```
   If no knowledge graph is injected (e.g. during application startup in `src/api.py:134`), the service silently loads `data/synthetic jee/v3/concepts.csv`. In a production environment, this means student progress is evaluated against synthetic mock data rather than the accredited NCERT/JEE canonical curriculum.

2. **Silent Index-Zero Fallback in AKT Inference:**
   In `src/akt_inference.py:197`:
   ```python
   c_indices[i] = self.vocabulary.concept_to_index.get(item.concept_id, 0)
   ```
   If a question belongs to a novel, unmapped, or misspelled concept ID, `get(..., 0)` silently replaces it with concept index 0 (e.g. `PHY_UAM` or padding). This corrupts the causal attention state of the Transformer model without raising an error.

3. **Untranslated Learner-State Mutation:**
   When student attempts are processed in `src/state.py`, mastery records are keyed directly by simulator IDs (`PHY_KIN`, `CHE_EQM`). Person 1's tenant storage and Person 2's canonical repository expect canonical concept IDs (`cc_3e003bf9b038a36b`). Without translation, state records become fragmented across schemas.

4. **Non-Atomic Partial State Mutation:**
   If a mastery vector contains 10 concepts and the 9th fails due to an unmapped ID, previous implementations allowed the first 8 to persist, leaving the learner state partially mutated and inconsistent.

---

## 4. Production Configuration Requirements

The following environment variables or configuration settings must be provided to Person 3's service:

```bash
# Integration Mode: 'production' strictly enforces canonical graph presence
LEARNSENSE_INTEGRATION_MODE=production

# Canonical Curriculum Identification
LEARNSENSE_CURRICULUM_ID=jee_class_11_12
LEARNSENSE_CURRICULUM_SYLLABUS_VERSION=2026.jee.v1
LEARNSENSE_CURRICULUM_FINGERPRINT=0e2f5b8c9d1a3e74

# Canonical Repository Storage Path
LEARNSENSE_CURRICULUM_REPO_PATH=/var/data/learnsense/curriculum

# Prohibit CSV Fallback (safety interlock)
LEARNSENSE_ALLOW_CSV_FALLBACK=false
```

---

## 5. Detailed Implementation Instructions & Minimal Patches

### Patch 1: Enforce Canonical Graph Injection in `src/service.py`

**File:** `src/service.py`  
**Location:** `LearnSensePersonalizationService.__init__`

```python
# --- BEFORE ---
class LearnSensePersonalizationService:
    def __init__(
        self,
        config: Optional[BKTConfig] = None,
        knowledge_graph: Optional[PrerequisiteGraph] = None,
        knowledge_base: Optional[GroundedKnowledgeBase] = None,
        store: Optional[LearnerStateStore] = None,
        state_service: Optional[LearnerStateService] = None,
    ) -> None:
        self.knowledge_graph = knowledge_graph or load_knowledge_graph_from_csv()
        ...

# --- PROPOSED PRODUCTION-SAFE PATCH ---
import os

class CanonicalGraphUnavailableError(RuntimeError):
    """Raised when canonical knowledge graph is unavailable in production mode."""
    pass

class LearnSensePersonalizationService:
    def __init__(
        self,
        config: Optional[BKTConfig] = None,
        knowledge_graph: Optional[PrerequisiteGraph] = None,
        knowledge_base: Optional[GroundedKnowledgeBase] = None,
        store: Optional[LearnerStateStore] = None,
        state_service: Optional[LearnerStateService] = None,
        mode: Optional[str] = None,
    ) -> None:
        effective_mode = mode or os.getenv("LEARNSENSE_INTEGRATION_MODE", "production")
        
        if knowledge_graph is not None:
            self.knowledge_graph = knowledge_graph
        elif effective_mode == "production":
            raise CanonicalGraphUnavailableError(
                "Production mode requires an explicit, validated canonical KnowledgeGraphAdapter. "
                "Silent fallback to synthetic CSV is strictly prohibited in production."
            )
        else:
            # Testing / development fallback only
            self.knowledge_graph = load_knowledge_graph_from_csv()
            
        self.knowledge_base = knowledge_base or get_default_knowledge_base()
        self.config = config or BKTConfig(config_id="production_service_v1")
        ...
```

---

### Patch 2: Wire Canonical Factory in `src/api.py`

**File:** `src/api.py`  
**Location:** `create_app`

```python
# --- BEFORE (src/api.py:133-135) ---
    if service is not None:
        app.state.service = service
    else:
        app.state.service = LearnSensePersonalizationService(store=store)

# --- PROPOSED PRODUCTION-SAFE PATCH ---
    if service is not None:
        app.state.service = service
    else:
        # Load canonical curriculum adapter using Person 2's production factory
        from curriculum.integration_factory import ProductionCurriculumIntegrationFactory
        from curriculum.repository import CurriculumRepository

        repo_path = os.getenv("LEARNSENSE_CURRICULUM_REPO_PATH", "curriculum/repo")
        curriculum_id = os.getenv("LEARNSENSE_CURRICULUM_ID", "jee_class_11_12")
        expected_fp = os.getenv("LEARNSENSE_CURRICULUM_FINGERPRINT", "0e2f5b8c9d1a3e74")
        mode = os.getenv("LEARNSENSE_INTEGRATION_MODE", "production")

        repo = CurriculumRepository(base_dir=repo_path)
        factory = ProductionCurriculumIntegrationFactory(
            repository=repo,
            expected_fingerprint=expected_fp,
            mode=mode,
        )
        canonical_adapter = factory.create_adapter(curriculum_id)

        app.state.service = LearnSensePersonalizationService(
            knowledge_graph=canonical_adapter,
            store=store,
            mode=mode,
        )
```

---

### Patch 3: Pre-validate Vocabulary and Eliminate Index-0 Fallback in `src/akt_inference.py`

**File:** `src/akt_inference.py`  
**Location:** `record_interaction` and `_prepare_sequence_tensors`

```python
# --- BEFORE (src/akt_inference.py:197) ---
        for i, item in enumerate(history):
            q_indices[i] = self.vocabulary.question_to_index.get(item.question_id, 0)
            c_indices[i] = self.vocabulary.concept_to_index.get(item.concept_id, 0)
            d_indices[i] = self.vocabulary.difficulty_to_index.get(item.difficulty, 0)

# --- PROPOSED PRODUCTION-SAFE PATCH ---
class UnknownSimulatorIdError(KeyError):
    """Raised when a concept ID is not present in the trained model vocabulary."""
    pass

    def record_interaction(
        self,
        learner_id: str,
        question_id: str,
        concept_id: str,
        difficulty: str = "medium",
        is_correct: Union[bool, int] = 1,
        timestamp: str = "",
    ) -> None:
        cid = str(concept_id).strip()
        # Strictly validate concept ID against active model vocabulary
        if self.vocabulary is not None and cid not in self.vocabulary.concept_to_index:
            raise UnknownSimulatorIdError(
                f"Concept ID '{cid}' is not in trained AKT model vocabulary. "
                "Rejecting interaction before sequence encoding to prevent silent index-0 corruption."
            )
        ...

    def _prepare_sequence_tensors(
        self,
        history: List[LearnerInteraction],
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        assert self.vocabulary is not None
        seq_len = len(history)
        q_indices = np.zeros(seq_len, dtype=np.int64)
        c_indices = np.zeros(seq_len, dtype=np.int64)
        d_indices = np.zeros(seq_len, dtype=np.int64)
        responses = np.full(seq_len, START_RESPONSE, dtype=np.int64)

        for i, item in enumerate(history):
            if item.concept_id not in self.vocabulary.concept_to_index:
                raise UnknownSimulatorIdError(
                    f"Invalid concept ID '{item.concept_id}' encountered during sequence preparation."
                )
            q_indices[i] = self.vocabulary.question_to_index.get(item.question_id, 0)
            c_indices[i] = self.vocabulary.concept_to_index[item.concept_id]
            d_indices[i] = self.vocabulary.difficulty_to_index.get(item.difficulty, 0)
            if i > 0:
                responses[i] = history[i - 1].is_correct
        ...
```

---

### Patch 4: Atomic Mastery Translation & Canonical State Persistence in `src/state.py`

**File:** `src/state.py`  
**Location:** Call site after `predict_concept_mastery` in `process_attempt`

```python
# --- PROPOSED INTEGRATION ---
        # When emitting or persisting learner mastery at the canonical boundary:
        from curriculum.translation import translate_mastery_profile
        from curriculum.integration_factory import CanonicalLearnerStateService

        # simulator_profile: Dict[str, float] = self.akt_inference.predict_concept_mastery(lid)
        # Process through CanonicalLearnerStateService:
        # state_service = CanonicalLearnerStateService(adapter=self.knowledge_graph)
        # translation_result = state_service.process_learner_mastery_update(lid, simulator_profile)
```

---

## 6. Local Validation Procedure for Person 3 Team

After applying the patches in Person 3's environment, execute the following validation steps:

```bash
# 1. Run Person 3's existing unit tests (must all pass)
pytest tests/test_knowledge_graph.py tests/test_recommendation.py -v

# 2. Run Person 3's pipeline tests with canonical adapter injected
pytest tests/test_integrated_pipeline.py -v

# 3. Run cross-repository reference equivalence tests
pytest tests/unit/curriculum/test_person3_reference_equivalence.py -v

# 4. Run the 10-scenario runtime integration harness
pytest tests/integration/test_person2_person3_runtime_integration.py -v

# Expected Output:
# ============================ 10 passed in 1.46s =============================
```

---

## 7. Rollback Guidance (No Learner Data Loss)

If production deployment needs to be rolled back:

1. **Do NOT delete or truncate learner state repositories:**
   Canonical states are stored with persistent key schemas (`cc_<hash>`). Rolling back the code to previous versions will not invalidate existing state files.
2. **Switch mode safely:**
   Set `LEARNSENSE_INTEGRATION_MODE=testing` to restore the legacy development fallback if an emergency hotfix is required.
3. **Preserve audit ledger:**
   `AttemptRecord` files in the learner store maintain the immutable audit trail with raw question IDs, answers, and timestamps. Replays remain 100% idempotent.

---

## 8. Separation of Responsibilities

| Responsibility Area | Owner | Implemented in Main Repo | Required in External Repo |
|---|---|---|---|
| Canonical Specification & DAG Validation | Person 2 | **YES** (`curriculum/data/jee_curriculum_spec.json`) | No action required |
| KnowledgeGraphAdapter & Duck Typing | Person 2 | **YES** (`curriculum/learner_adapter.py`) | No action required |
| 1-to-1 Simulator Concept Mapping | Person 2 | **YES** (`curriculum/simulator.py`) | No action required |
| Atomic Mastery Translation | Person 2 | **YES** (`curriculum/translation.py`) | No action required |
| Production Integration Factory | Person 2 | **YES** (`curriculum/integration_factory.py`) | No action required |
| 10-Scenario Runtime Test Harness | Person 2 | **YES** (`tests/integration/test_person2_person3_runtime_integration.py`) | No action required |
| Service Factory CSV Fallback Removal | Person 3 | N/A (read-only reference) | **REQUIRED** (`src/service.py`) |
| API App Canonical Graph Injection | Person 3 | N/A (read-only reference) | **REQUIRED** (`src/api.py`) |
| Vocabulary Validation & Index-0 Removal | Person 3 | N/A (read-only reference) | **REQUIRED** (`src/akt_inference.py`) |
| Production Deployment Verification | Person 3 / DevOps | N/A | **REQUIRED** in production cluster |
