"""
Production Curriculum Integration Factory and Boundary Service (Person 2 x Person 3).

Provides the explicit, production-safe boundary between Person 2's canonical curriculum
repository and downstream learner-model pipelines (Person 3).

Key Guarantees:
1. Strict Production Mode: Loads the canonical curriculum from the configured CurriculumRepository;
   never silently falls back to simulator CSV or synthetic fixtures.
2. Graph Validation: Enforces curriculum ID, syllabus version, deterministic content fingerprint,
   and structural validity (CurriculumGraphValidator) before adapter creation.
3. Adapter Contract Validation: Validates that the constructed adapter satisfies all methods,
   properties, and node views expected by downstream components.
4. Model Vocabulary Boundary: Validates all incoming simulator IDs against declared vocabularies,
   preventing silent index-zero or unknown-concept substitution.
5. Atomic Mastery Translation: Translates simulator-keyed mastery profiles to canonical IDs
   using approved mappings, and updates learner state atomically if and only if all entries
   resolve cleanly.
6. Tenant & Learner Isolation: Persists updates strictly scoped to the target learner ID.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from curriculum.graph import CurriculumGraphValidator
from curriculum.learner_adapter import (
    CanonicalGraphUnavailableError,
    KnowledgeGraphAdapter,
)
from curriculum.repository import CurriculumRepository
from curriculum.translation import (
    MasteryTranslationResult,
    translate_mastery_profile,
    validate_simulator_ids,
)
from phase3.learner.models import ConceptState, LearnerState
from phase3.storage.learner_repository import LearnerStateRepository

logger = logging.getLogger(__name__)

__all__ = [
    "AdapterInterfaceValidationError",
    "AtomicLearnerStateUpdateError",
    "CanonicalGraphUnavailableError",
    "CanonicalLearnerStateService",
    "IncompatibleCurriculumError",
    "ProductionCSVFallbackForbiddenError",
    "ProductionCurriculumIntegrationFactory",
    "REQUIRED_ADAPTER_METHODS",
    "REQUIRED_ADAPTER_PROPERTIES",
    "REQUIRED_NODE_PROPERTIES",
    "validate_adapter_contract",
]


class IncompatibleCurriculumError(RuntimeError):
    """Raised when the loaded canonical curriculum does not match expected identity or integrity."""


class AdapterInterfaceValidationError(TypeError):
    """Raised when a knowledge graph adapter does not satisfy Person 3's required interface."""


class AtomicLearnerStateUpdateError(RuntimeError):
    """Raised when learner state cannot be updated cleanly/atomically due to translation failures."""


class ProductionCSVFallbackForbiddenError(RuntimeError):
    """Raised when production mode attempts to fall back to synthetic simulator CSV data."""


REQUIRED_ADAPTER_METHODS: Tuple[str, ...] = (
    "get_node",
    "get_concept",
    "get_prerequisites",
    "get_direct_prerequisites",
    "get_dependents",
    "get_direct_dependents",
    "get_all_ancestor_prerequisites",
    "get_all_descendant_dependents",
    "contains",
    "get_all_concept_ids",
    "topological_sort",
    "detect_cycles",
    "validate_graph",
    "evaluate_prerequisite_readiness",
    "get_remediation_sequence",
    "graph_fingerprint",
)

REQUIRED_ADAPTER_PROPERTIES: Tuple[str, ...] = (
    "concept_ids",
    "curriculum_id",
    "syllabus_version",
    "accepted_only",
    "fingerprint",
)

REQUIRED_NODE_PROPERTIES: Tuple[str, ...] = (
    "concept_id",
    "name",
    "description",
    "subject",
    "chapter_id",
    "topic_group",
    "tags",
    "status",
    "prerequisite_concept_ids",
    "source_refs",
    "metadata",
    "to_contract_dict",
)


def validate_adapter_contract(adapter: Any) -> None:
    """Validate that an adapter strictly satisfies Person 3's contract expectations.

    Raises AdapterInterfaceValidationError if any required method or property is missing.
    """
    missing_methods = [
        method for method in REQUIRED_ADAPTER_METHODS if not callable(getattr(adapter, method, None))
    ]
    if missing_methods:
        raise AdapterInterfaceValidationError(
            f"Adapter is missing required callable methods: {', '.join(missing_methods)}"
        )

    missing_props = [
        prop for prop in REQUIRED_ADAPTER_PROPERTIES if not hasattr(adapter, prop)
    ]
    if missing_props:
        raise AdapterInterfaceValidationError(
            f"Adapter is missing required properties: {', '.join(missing_props)}"
        )

    # Validate node contract using a sample concept if present
    cids = list(getattr(adapter, "concept_ids", []))
    if cids:
        sample_node = adapter.get_node(cids[0])
        if sample_node is None:
            raise AdapterInterfaceValidationError(
                f"adapter.get_node('{cids[0]}') returned None for an active concept ID"
            )
        missing_node_props = [
            prop for prop in REQUIRED_NODE_PROPERTIES if not hasattr(sample_node, prop)
        ]
        if missing_node_props:
            raise AdapterInterfaceValidationError(
                f"Adapter node view is missing required properties: {', '.join(missing_node_props)}"
            )


class ProductionCurriculumIntegrationFactory:
    """Factory creating validated canonical adapters for production learning pipelines."""

    def __init__(
        self,
        repository: Optional[CurriculumRepository] = None,
        mode: str = "production",
        expected_curriculum_id: str = "jee_class_11_12",
        expected_syllabus_version: str = "2026.jee.v1",
        expected_fingerprint: Optional[str] = None,
        accepted_only: bool = True,
    ) -> None:
        self.repository = repository or CurriculumRepository()
        self.mode = mode.strip().lower()
        self.expected_curriculum_id = expected_curriculum_id
        self.expected_syllabus_version = expected_syllabus_version
        self.expected_fingerprint = expected_fingerprint
        self.accepted_only = accepted_only

    def create_adapter(
        self,
        curriculum_id: Optional[str] = None,
    ) -> KnowledgeGraphAdapter:
        """Create and validate a KnowledgeGraphAdapter for the canonical curriculum.

        In production mode:
        - Fails clearly if the canonical graph is unavailable in the repository.
        - Verifies curriculum ID and syllabus version.
        - Validates graph structural integrity (no cycles, no dangling edges).
        - Validates the adapter interface contract.
        - Strictly forbids silent fallback to simulator CSVs.
        """
        target_id = curriculum_id or self.expected_curriculum_id

        if self.mode == "production":
            graph = self.repository.load_graph(target_id)
            if graph is None:
                stored = self.repository.list_curriculum_ids()
                raise CanonicalGraphUnavailableError(
                    f"Production curriculum '{target_id}' is not stored in the canonical repository. "
                    f"Available curricula: {stored or 'none'}. "
                    "Seed the curriculum before operating the production learning pipeline. "
                    "Silent fallback to simulator CSV data is strictly forbidden in production mode."
                )

            # Validate identity & version
            if graph.curriculum_id != target_id:
                raise IncompatibleCurriculumError(
                    f"Curriculum ID mismatch: expected '{target_id}', found '{graph.curriculum_id}'"
                )
            if (
                self.expected_syllabus_version
                and target_id == self.expected_curriculum_id
                and graph.syllabus_version != self.expected_syllabus_version
            ):
                raise IncompatibleCurriculumError(
                    f"Syllabus version mismatch for '{target_id}': expected "
                    f"'{self.expected_syllabus_version}', found '{graph.syllabus_version}'"
                )

            # Validate fingerprint if constrained
            if self.expected_fingerprint:
                actual_fp = graph.content_fingerprint()
                if actual_fp != self.expected_fingerprint:
                    raise IncompatibleCurriculumError(
                        f"Content fingerprint mismatch for '{target_id}': expected "
                        f"'{self.expected_fingerprint}', found '{actual_fp}'"
                    )

            # Validate graph structural integrity
            validator = CurriculumGraphValidator()
            report = validator.validate(graph)
            if not report.is_valid:
                errors = [
                    f"{issue.code}: {issue.message}"
                    for issue in report.issues
                    if getattr(issue.severity, "value", issue.severity) == "error"
                ]
                raise IncompatibleCurriculumError(
                    f"Canonical graph '{target_id}' failed structural validation: {'; '.join(errors)}"
                )

            adapter = KnowledgeGraphAdapter(graph, accepted_only=self.accepted_only)
            validate_adapter_contract(adapter)
            return adapter

        elif self.mode == "testing":
            # In testing mode, try loading from repository first
            graph = self.repository.load_graph(target_id)
            if graph is None:
                # If unavailable in repo, check if fixture package spec exists
                spec_path = (
                    Path(__file__).resolve().parent / "data" / "jee_curriculum_spec.json"
                )
                if spec_path.is_file():
                    from curriculum.seed import CurriculumSpec, seed_curriculum

                    spec_data = json.loads(spec_path.read_text(encoding="utf-8"))
                    spec = CurriculumSpec.model_validate(spec_data)
                    graph = seed_curriculum(spec)
                else:
                    raise CanonicalGraphUnavailableError(
                        f"Testing curriculum '{target_id}' is unavailable in repository and fixtures."
                    )

            adapter = KnowledgeGraphAdapter(graph, accepted_only=self.accepted_only)
            validate_adapter_contract(adapter)
            return adapter

        else:
            raise ValueError(f"Unknown integration mode '{self.mode}'; expected 'production' or 'testing'")

    def build_pipeline(
        self,
        pipeline_cls: Any,
        **pipeline_kwargs: Any,
    ) -> Any:
        """Instantiate a learning loop pipeline with the canonical adapter injected."""
        adapter = self.create_adapter()
        return pipeline_cls(knowledge_graph=adapter, **pipeline_kwargs)


class CanonicalLearnerStateService:
    """Service providing safe, atomic translation and persistence between simulator and canonical state."""

    def __init__(
        self,
        adapter: KnowledgeGraphAdapter,
        state_repo: Optional[LearnerStateRepository] = None,
        concept_map: Optional[Mapping[str, str]] = None,
        vocabulary: Optional[Any] = None,
    ) -> None:
        self.adapter = adapter
        self.state_repo = state_repo or LearnerStateRepository()
        self.concept_map = dict(concept_map or {})
        self.vocabulary = vocabulary

        # If no concept_map was passed, build deterministic mapping from canonical graph aliases
        if not self.concept_map:
            self._build_concept_map_from_graph()

    def _build_concept_map_from_graph(self) -> None:
        """Construct simulator -> canonical concept mapping from the canonical graph's aliases."""
        for cid, concept in self.adapter.graph.concepts.items():
            for alias in getattr(concept, "aliases", []) or []:
                alias_str = str(alias).strip()
                if (
                    alias_str.startswith("PHY_")
                    or alias_str.startswith("CHE_")
                    or alias_str.startswith("MAT_")
                ):
                    self.concept_map[alias_str] = cid

    def process_learner_mastery_update(
        self,
        learner_id: str,
        simulator_profile: Mapping[str, float],
    ) -> MasteryTranslationResult:
        """Translate a simulator-keyed mastery profile and update canonical learner state atomically.

        Guarantees:
        - Rejects unknown simulator IDs against vocabulary before updating state.
        - Validates all probabilities are in [0.0, 1.0].
        - Rejects unmapped, ambiguous, or duplicate-target concepts.
        - Persists to LearnerStateRepository if and only if translation is 100% complete and valid.
        - Fails atomically: on any error, learner state remains completely unmodified.
        - Isolated per learner ID.
        """
        lid = str(learner_id or "").strip()
        if not lid:
            raise ValueError("learner_id cannot be empty")

        # 1. Validate vocabulary if present
        if self.vocabulary is not None:
            validate_simulator_ids(simulator_profile.keys(), self.vocabulary)

        # 2. Validate probability values
        for sim_id, val in simulator_profile.items():
            if not isinstance(val, (int, float)) or math.isnan(val) or val < 0.0 or val > 1.0:
                raise ValueError(
                    f"Invalid mastery probability for concept '{sim_id}': {val}. "
                    "Mastery probabilities must be finite numbers between 0.0 and 1.0."
                )

        # 3. Translate profile using Person 2's translation service
        result = translate_mastery_profile(
            simulator_profile,
            graph=self.adapter.graph,
            concept_map=self.concept_map,
        )

        # 4. Check for partial translation or collisions
        if not result.is_complete or result.unresolved_simulator_ids or result.duplicate_targets:
            reasons = []
            if result.unresolved_simulator_ids:
                reasons.append(f"unresolved concepts: {', '.join(result.unresolved_simulator_ids)}")
            if result.duplicate_targets:
                reasons.append(f"duplicate target collisions: {', '.join(result.duplicate_targets)}")
            raise AtomicLearnerStateUpdateError(
                f"Mastery translation incomplete for learner '{lid}'; refusing partial state mutation: "
                + "; ".join(reasons)
            )

        # 5. Persist atomically to LearnerStateRepository
        current_state = self.state_repo.load_state(lid) or LearnerState(learner_id=lid)

        # Apply canonical mastery values
        for canonical_id, prob in result.canonical_mastery.items():
            if canonical_id not in current_state.concept_states:
                current_state.concept_states[canonical_id] = ConceptState(
                    concept_id=canonical_id,
                    mastery_probability=prob,
                )
            else:
                current_state.concept_states[canonical_id].mastery_probability = prob

        self.state_repo.save_state(current_state)
        return result

    def get_learner_readiness(
        self,
        learner_id: str,
        concept_id: str,
        threshold: float = 0.50,
    ) -> Tuple[bool, Dict[str, str], List[str]]:
        """Evaluate prerequisite readiness for a concept given the learner's current canonical state."""
        state = self.state_repo.load_state(learner_id)
        mastery_map: Dict[str, float] = {}
        if state is not None:
            for cid, cstate in state.concept_states.items():
                mastery_map[cid] = cstate.mastery_probability

        # Follow alias or simulator ID if passed
        resolved_cid = self.concept_map.get(concept_id, concept_id)
        return self.adapter.evaluate_prerequisite_readiness(
            resolved_cid, mastery_map, threshold=threshold
        )
