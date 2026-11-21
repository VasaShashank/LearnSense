"""LearnSense Person 3 — Knowledge Graph Integration Adapter.

Provides read-only access to the canonical curriculum graph owned by Person 1:
- Validates concept nodes against contracts/concept_schema.json (Draft 2020-12).
- Preserves prerequisite directed edges and detects invalid references or cycles.
- Exposes immutable graph queries to downstream learner modeling and recommendation engines.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from src.integration.contracts import validate_concept
from src.knowledge_graph import ConceptNode, PrerequisiteGraph, load_knowledge_graph_from_csv


class KnowledgeGraphAdapter:
    """Read-only adapter for canonical knowledge graph data."""

    def __init__(self, graph: Optional[PrerequisiteGraph] = None) -> None:
        self._graph = graph or load_knowledge_graph_from_csv()

    @property
    def graph(self) -> PrerequisiteGraph:
        """Exposes the underlying verified DAG."""
        return self._graph

    def get_concept(self, concept_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves and validates a concept node conforming to concept_schema.json."""
        node = self._graph.get_node(concept_id)
        if not node:
            return None
        payload = node.to_contract_dict()
        is_valid, errors = validate_concept(payload)
        if not is_valid:
            raise ValueError(f"Concept '{concept_id}' violates contract: {errors}")
        return payload

    def get_prerequisites(self, concept_id: str) -> List[str]:
        """Returns immediate prerequisite concept IDs."""
        return self._graph.get_direct_prerequisites(concept_id)

    def get_dependents(self, concept_id: str) -> List[str]:
        """Returns direct dependent concept IDs."""
        return self._graph.get_direct_dependents(concept_id)

    def get_all_concept_ids(self) -> List[str]:
        """Returns all canonical concept IDs in topological order."""
        return self._graph.topological_sort()

    def evaluate_prerequisite_readiness(
        self,
        concept_id: str,
        mastery_vector: Dict[str, float],
        mastery_threshold: float = 0.50,
    ) -> Tuple[bool, Dict[str, float], List[str]]:
        """Evaluates whether all prerequisites for concept_id meet the mastery threshold."""
        return self._graph.evaluate_prerequisite_readiness(concept_id, mastery_vector, mastery_threshold)

    def get_remediation_sequence(
        self,
        target_concept_id: str,
        mastery_vector: Dict[str, float],
    ) -> List[str]:
        """Generates ordered remediation sequence for unmet prerequisites."""
        return self._graph.get_remediation_sequence(target_concept_id, mastery_vector)
