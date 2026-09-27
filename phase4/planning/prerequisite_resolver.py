"""
Prerequisite Resolver.
Graph analysis for identifying foundational concepts (roots or zero-prerequisite concepts),
topological sorting, and cycle-safe graph traversal.
"""

from typing import Dict, List, Set
from phase3.knowledge.phase2_adapter import LearningContext


class PrerequisiteResolver:
    """Provides cycle-safe graph operations on prerequisite structures."""

    def find_foundational_concepts(
        self,
        learning_context: LearningContext,
        subject_concept_ids: List[str],
    ) -> List[str]:
        """
        Determines foundational concepts from prerequisite graph structure.
        A concept is foundational if:
        1. It has no prerequisite concepts targeting it, OR
        2. It is an in-degree=0 root node among the subject's concept subgraph.
        """
        subject_set = set(subject_concept_ids)
        in_degree: Dict[str, int] = {c_id: 0 for c_id in subject_concept_ids}

        for link in learning_context.prerequisites:
            src = link.source_concept_id
            tgt = link.target_concept_id

            if src in subject_set and tgt in subject_set:
                in_degree[tgt] = in_degree.get(tgt, 0) + 1

        # Foundational concepts are those with in_degree == 0
        foundational = [c_id for c_id in subject_concept_ids if in_degree.get(c_id, 0) == 0]

        # Edge case handling: If graph is a pure cycle (no in_degree==0 node), pick first concept safely
        if not foundational and subject_concept_ids:
            foundational = [subject_concept_ids[0]]

        return foundational

    def get_prerequisites_for_concept(
        self,
        learning_context: LearningContext,
        target_concept_id: str,
    ) -> List[str]:
        """
        Returns direct prerequisite concept IDs for target_concept_id.
        """
        return [
            link.source_concept_id
            for link in learning_context.prerequisites
            if link.target_concept_id == target_concept_id
        ]

    def cycle_safe_topological_sort(
        self,
        learning_context: LearningContext,
        concept_ids: List[str],
    ) -> List[str]:
        """
        Performs cycle-safe topological sort (Kahn's Algorithm with cycle detection).
        Guarantees no infinite loop or crash if cycles exist in the graph.
        """
        concept_set = set(concept_ids)
        adj: Dict[str, List[str]] = {c: [] for c in concept_ids}
        in_degree: Dict[str, int] = {c: 0 for c in concept_ids}

        for link in learning_context.prerequisites:
            src = link.source_concept_id
            tgt = link.target_concept_id
            if src in concept_set and tgt in concept_set:
                adj[src].append(tgt)
                in_degree[tgt] = in_degree.get(tgt, 0) + 1

        queue = [c for c in concept_ids if in_degree[c] == 0]
        sorted_nodes = []

        while queue:
            # Deterministic sorting on queue for stable path generation
            queue.sort()
            curr = queue.pop(0)
            sorted_nodes.append(curr)

            for neighbor in adj.get(curr, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # Handle remaining cyclic nodes safely by appending in deterministic order
        remaining = [c for c in concept_ids if c not in set(sorted_nodes)]
        remaining.sort()
        sorted_nodes.extend(remaining)

        return sorted_nodes
