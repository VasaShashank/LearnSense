"""
Canonical Curriculum & Knowledge Graph module (Person 2 ownership).

This package owns the *canonical* curriculum knowledge foundation that the rest of
LearnSense consumes:

* stable, document-independent canonical concept identifiers,
* alias / normalization handling without duplicate concepts,
* typed concept relationships with prerequisite-direction semantics,
* deterministic graph validation (endpoints, self-loops, duplicates, cycles,
  reachability),
* mapping of extracted educational content onto canonical concepts with honest
  accepted / uncertain / unmapped outcomes,
* provenance, teacher review and curriculum versioning,
* graph-quality metrics.

Ownership boundaries
--------------------
* Phase 1 (`schemas.document.StructuredDocument`, `extraction/`, `ingestion/`) is
  the *input* boundary.  Nothing here parses PDFs or re-extracts content; the
  structured-document representation and the Phase 2 EKR are consumed as-is.
* Learner mastery, BKT, grading and recommendations belong to Person 3 and are
  deliberately absent from the canonical graph.
* The canonical graph stores no per-student state.

See ``docs/curriculum/README.md`` for setup and usage.
"""

from curriculum.ids import (
    DEFAULT_CURRICULUM_ID,
    DEFAULT_SYLLABUS_VERSION,
    generate_concept_id,
    generate_relationship_id,
    generate_version_id,
    slugify,
    stable_key_from_name,
)
from curriculum.models import (
    AuditInfo,
    CanonicalConcept,
    ConceptLifecycleStatus,
    ConceptRelationship,
    CurriculumGraph,
    IdReference,
    ReviewStatus,
    SourceRef,
    Subject,
    Examination,
)
from curriculum.graph import (
    CurriculumGraphError,
    GraphIssue,
    GraphValidationReport,
    IssueSeverity,
    CurriculumGraphValidator,
    PrerequisiteCycleError,
    derive_topological_depth,
    topological_order,
)
from curriculum.normalization import normalize_formula, normalize_term, normalize_text
from curriculum.learner_adapter import (
    CanonicalGraphUnavailableError,
    KnowledgeGraphAdapter,
)
from curriculum.translation import (
    MasteryTranslationEntry,
    MasteryTranslationResult,
    UnknownSimulatorIdError,
    index_to_simulator_id,
    mastery_profile_from_indexed_output,
    translate_mastery_profile,
    validate_simulator_ids,
)
from curriculum.integration_factory import (
    AdapterInterfaceValidationError,
    AtomicLearnerStateUpdateError,
    CanonicalLearnerStateService,
    IncompatibleCurriculumError,
    ProductionCSVFallbackForbiddenError,
    ProductionCurriculumIntegrationFactory,
    validate_adapter_contract,
)

__all__ = [
    "AdapterInterfaceValidationError",
    "AtomicLearnerStateUpdateError",
    "AuditInfo",
    "CanonicalGraphUnavailableError",
    "CanonicalConcept",
    "CanonicalLearnerStateService",
    "ConceptLifecycleStatus",
    "ConceptRelationship",
    "CurriculumGraph",
    "CurriculumGraphError",
    "CurriculumGraphValidator",
    "DEFAULT_CURRICULUM_ID",
    "DEFAULT_SYLLABUS_VERSION",
    "derive_topological_depth",
    "topological_order",
    "GraphIssue",
    "GraphValidationReport",
    "IdReference",
    "IncompatibleCurriculumError",
    "IssueSeverity",
    "KnowledgeGraphAdapter",
    "MasteryTranslationEntry",
    "MasteryTranslationResult",
    "ProductionCSVFallbackForbiddenError",
    "ProductionCurriculumIntegrationFactory",
    "UnknownSimulatorIdError",
    "PrerequisiteCycleError",
    "ReviewStatus",
    "SourceRef",
    "Subject",
    "generate_concept_id",
    "generate_relationship_id",
    "generate_version_id",
    "normalize_formula",
    "normalize_term",
    "normalize_text",
    "index_to_simulator_id",
    "mastery_profile_from_indexed_output",
    "slugify",
    "translate_mastery_profile",
    "validate_adapter_contract",
    "validate_simulator_ids",
    "stable_key_from_name",
]

