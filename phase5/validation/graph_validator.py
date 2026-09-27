"""
Knowledge Graph Sanity Validator for Taproot Phase 5.
Detects duplicate nodes/edges, self-referencing relationships, broken targets, orphan concepts,
and prerequisite cycles (cycle removal / break to safeguard Phase 4 planner from infinite traversal).
"""

from typing import Dict, List, Set, Tuple, Optional
from phase3.knowledge.phase2_adapter import LearningContext
from phase5.models.validation_result import RecoveryClassification, ValidationResult, ValidationStatus
from phase5.observability.validation_events import ValidationEventLogger


class KnowledgeGraphValidator:
    """Validates structural integrity and cycle safety of knowledge graphs."""

    def validate_learning_context(self, context: LearningContext) -> ValidationResult:
        result = ValidationResult(status=ValidationStatus.VALID, is_valid=True)
        doc_id = context.document_id

        concepts = context.concepts
        prereqs = context.prerequisites

        concept_ids = set(concepts.keys())

        # 1. Broken targets & self-references in prerequisites
        broken_count = 0
        self_ref_count = 0
        seen_edges: Set[Tuple[str, str]] = set()

        for link in prereqs:
            src = getattr(link, "source_concept_id", None) or getattr(link, "prerequisite_concept_id", None)
            tgt = link.target_concept_id

            if src not in concept_ids:
                result.add_error(f"Prerequisite link references missing source concept '{src}'.")
                broken_count += 1
            if tgt not in concept_ids:
                result.add_error(f"Prerequisite link references missing target concept '{tgt}'.")
                broken_count += 1

            if src == tgt:
                result.add_error(f"Self-referencing prerequisite detected on concept '{src}'.")
                self_ref_count += 1

            edge = (src, tgt)
            if edge in seen_edges:
                result.add_warning(f"Duplicate prerequisite link: '{src}' -> '{tgt}'.")
            else:
                seen_edges.add(edge)

        # 2. Orphan concepts check (Warning)
        connected_concepts: Set[str] = set()
        for link in prereqs:
            src = getattr(link, "source_concept_id", None) or getattr(link, "prerequisite_concept_id", None)
            connected_concepts.add(src)
            connected_concepts.add(link.target_concept_id)

        orphans = concept_ids - connected_concepts
        if orphans and len(concept_ids) > 1:
            result.add_warning(f"Found {len(orphans)} orphan concept(s) without prerequisite connections: {list(orphans)[:5]}.")

        # 3. Cycle Detection in Prerequisite Graph (DFS / Tarjan)
        cycles = self._detect_cycles(context)
        if cycles:
            result.add_warning(f"Detected {len(cycles)} cycle(s) in prerequisite graph: {cycles}.")
            result.suggested_action = "Sanitize graph cycles to prevent infinite planning loops."
            result.status = ValidationStatus.WARNING
            ValidationEventLogger.log_event(
                "graph_cycle_detected",
                "WARNING",
                f"Prerequisite cycles detected in document '{doc_id}': {cycles}",
                document_id=doc_id,
            )

        result.metadata["total_concepts"] = len(concepts)
        result.metadata["total_prerequisites"] = len(prereqs)
        result.metadata["orphans_count"] = len(orphans)
        result.metadata["cycles_count"] = len(cycles)

        return result

    def sanitize_and_break_cycles(self, context: LearningContext) -> LearningContext:
        """
        Removes broken links, self-referencing links, duplicate links,
        and breaks prerequisite cycles to guarantee a Directed Acyclic Graph (DAG) for Phase 4.
        """
        concept_ids = set(context.concepts.keys())
        valid_links = []
        seen_edges: Set[Tuple[str, str]] = set()

        # Step 1: Remove broken, self-ref, and duplicate links
        for link in context.prerequisites:
            src = getattr(link, "source_concept_id", None) or getattr(link, "prerequisite_concept_id", None)
            tgt = link.target_concept_id
            if src in concept_ids and tgt in concept_ids and src != tgt:
                edge = (src, tgt)
                if edge not in seen_edges:
                    seen_edges.add(edge)
                    valid_links.append(link)

        context.prerequisites = valid_links

        # Step 2: Iteratively detect and break cycles
        while True:
            cycles = self._detect_cycles(context)
            if not cycles:
                break
            # Remove the last edge of the first detected cycle to break the loop safely
            cycle = cycles[0]
            src, tgt = cycle[-2], cycle[-1]
            ValidationEventLogger.log_event(
                "graph_cycle_broken",
                "RECOVERED",
                f"Breaking cycle by removing prerequisite link '{src}' -> '{tgt}'.",
                document_id=context.document_id,
            )
            context.prerequisites = [
                l for l in context.prerequisites
                if not (
                    (getattr(l, "source_concept_id", None) or getattr(l, "prerequisite_concept_id", None)) == src
                    and l.target_concept_id == tgt
                )
            ]

        return context

    def _detect_cycles(self, context: LearningContext) -> List[List[str]]:
        """Detects simple cycles in prerequisite graph using DFS."""
        adj: Dict[str, List[str]] = {c_id: [] for c_id in context.concepts.keys()}
        for link in context.prerequisites:
            src = getattr(link, "source_concept_id", None) or getattr(link, "prerequisite_concept_id", None)
            if src in adj and link.target_concept_id in adj:
                adj[src].append(link.target_concept_id)

        cycles: List[List[str]] = []
        visited: Dict[str, int] = {c_id: 0 for c_id in adj}  # 0: unvisited, 1: visiting, 2: visited
        path: List[str] = []

        def dfs(node: str):
            visited[node] = 1
            path.append(node)
            for neighbor in adj.get(node, []):
                if visited[neighbor] == 1:
                    # Cycle detected
                    idx = path.index(neighbor)
                    cycle_path = path[idx:] + [neighbor]
                    cycles.append(cycle_path)
                elif visited[neighbor] == 0:
                    dfs(neighbor)
            path.pop()
            visited[node] = 2

        for node in list(adj.keys()):
            if visited[node] == 0:
                dfs(node)

        return cycles
