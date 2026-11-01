# Person 2 — Integration API Contracts and Interface Reference

**Owner:** Person 2 — Knowledge Graph, Curriculum, and Content Management  
**Target Audience:** Person 1 (Backend & Infrastructure), Person 3 (Learner Modeling & Inference), Frontend Engineers  
**Date:** November 1, 2026  

---

## 1. REST API Endpoints (Mounted in FastAPI)

### 1.1 Curriculum Status & Exploration
- `GET /api/curriculum/status`
  - **Returns:** Concept count, relationship count, DAG validation status, content fingerprint, versions count.
- `GET /api/curriculum/concepts`
  - **Query Params:** `subject` (optional), `class_level` (optional), `status` (optional, default `active`).
  - **Returns:** List of canonical concept records conforming to Draft 2020-12 concept schema.
- `GET /api/curriculum/concepts/{concept_id}`
  - **Returns:** Single concept record, including prerequisites, successors, and metadata.
- `GET /api/curriculum/chapters`
  - **Returns:** List of curriculum chapters grouped by subject and class level.
- `GET /api/subjects/{subject_id}/learning-sequence`
  - **Query Params:** `start_concept_id` (optional).
  - **Returns:** Topologically ordered sequence of learning steps with step badges, prerequisites, and estimated duration.

### 1.2 Teacher & Reviewer Workflow
- `PUT /api/curriculum/concepts/{concept_id}`
  - **Auth:** Reviewer / Teacher role.
  - **Body:** `{ "name": str, "description": str, "chapter_id": str, "subject": str, "class_levels": List[str], "review_notes": str }`
  - **Returns:** Updated concept record with provenance revision incremented.
- `POST /api/curriculum/publish`
  - **Auth:** Curriculum Editor / Admin.
  - **Body:** `{ "reverted_by": str, "note": str }`
  - **Behavior:** Runs full `CurriculumGraphValidator`. If invalid (e.g. cycle detected), returns HTTP 400 with validation issues. If valid, writes immutable snapshot `cv_<index>_<timestamp>.json`.
- `POST /api/curriculum/versions/{version_id}/rollback`
  - **Auth:** Curriculum Editor / Admin.
  - **Body:** `{ "reverted_by": str, "note": str }`
  - **Behavior:** Reverts active graph to specified historical snapshot, archiving the pre-rollback state.

### 1.3 Syllabus Crosswalk
- `GET /api/curriculum/syllabus-items`
  - **Query Params:** `subject` (optional), `status` (optional).
  - **Returns:** Official JEE Main 2027 syllabus mappings.
- `GET /api/curriculum/syllabus-coverage`
  - **Returns:** Overall mapping coverage statistics (exact matches, review status, unmapped count).
- `POST /api/curriculum/syllabus-items/{syllabus_item_id}/review`
  - **Body:** `{ "mapping_status": "accepted" | "rejected" | "custom_verified", "canonical_concept_ids": List[str], "review_notes": str }`
  - **Returns:** Updated syllabus mapping record.

---

## 2. Python Inter-Process Interfaces (Person 3 Integration)

### 2.1 `KnowledgeGraphAdapter`
```python
from curriculum.learner_adapter import KnowledgeGraphAdapter

adapter = KnowledgeGraphAdapter(graph, accepted_only=True)

# Traversal universe (active concepts only, deprecated excluded)
cids = adapter.concept_ids

# Node view conforming to Person 3 duck typing
node = adapter.get_node("cc_3d26d1722cc57f40")
prereqs = adapter.get_prerequisites("cc_3d26d1722cc57f40")
succs = adapter.get_successors("cc_3d26d1722cc57f40")

# Contract dictionary export
contract_dict = node.to_contract_dict()
```

### 2.2 `ConceptTranslationService` & `SimulatorBridge`
```python
from curriculum.simulator import SimulatorBridge
from curriculum.translation import translate_mastery_profile

bridge = SimulatorBridge(graph)
entries = bridge.map_concepts(sim_concepts)
concept_map = bridge.resolve_map(entries)

# Translate simulator 62-d output vector to canonical mastery profile
outcome = translate_mastery_profile(
    sim_profile,
    graph=graph,
    concept_map=concept_map,
    mapping_entries=entries,
)
assert outcome.is_complete is True
canonical_mastery = outcome.canonical_mastery
```

### 2.3 `CanonicalLearnerStateService` (Atomic State Update)
```python
from curriculum.integration_factory import CanonicalLearnerStateService

service = CanonicalLearnerStateService(
    adapter=adapter,
    state_repo=state_repo,
    vocabulary=akt_vocab_path,
)

# Atomic update: rejects partial or invalid predictions without corrupting learner state
result = service.process_learner_mastery_update(learner_id, raw_predictions)
```
