"""LearnSense Person 3 — Knowledge Graph and Prerequisite DAG Representation.

Provides validated concept graph representations, prerequisite dependency resolution,
cycle detection, readiness evaluation, and targeted remediation sequence generation.
Strictly preserves canonical concept IDs and conforms to contracts/concept_schema.json.
"""

from __future__ import annotations

import copy
import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

REPO_ROOT = Path(__file__).resolve().parent.parent

RELEASE_CONCEPTS_CSV = REPO_ROOT / "curriculum" / "concepts.csv"
PRODUCTION_CONCEPTS_CSV = (
    RELEASE_CONCEPTS_CSV
    if RELEASE_CONCEPTS_CSV.is_file()
    else REPO_ROOT
    / "data"
    / "synthetic jee"
    / "v5_1_production"
    / "concepts.csv"
)
LEGACY_CONCEPTS_CSV = (
    REPO_ROOT
    / "data"
    / "synthetic jee"
    / "v3"
    / "concepts.csv"
)
DEFAULT_CONCEPTS_CSV = (
    RELEASE_CONCEPTS_CSV
    if RELEASE_CONCEPTS_CSV.is_file()
    else PRODUCTION_CONCEPTS_CSV
    if PRODUCTION_CONCEPTS_CSV.is_file()
    else LEGACY_CONCEPTS_CSV
)


@dataclass
class SourceReference:
    """Represents a validated provenance reference attached to a concept or activity."""
    source_id: str
    locator: Optional[str] = None
    excerpt_hash: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "locator": self.locator,
            "excerpt_hash": self.excerpt_hash,
        }


@dataclass
class ConceptNode:
    """Represents a canonical concept in the LearnSense Knowledge Representation."""
    concept_id: str
    name: str
    description: str = ""
    subject: Optional[str] = None
    chapter_id: Optional[str] = None
    topic_group: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    status: str = "active"
    prerequisite_concept_ids: List[str] = field(default_factory=list)
    source_refs: List[SourceReference] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_contract_dict(self) -> Dict[str, Any]:
        """Serializes node strictly conforming to contracts/concept_schema.json."""
        return {
            "concept_id": self.concept_id,
            "name": self.name,
            "description": self.description or f"Canonical concept: {self.name}",
            "subject": self.subject,
            "chapter_id": self.chapter_id,
            "tags": list(self.tags),
            "status": self.status,
            "prerequisite_concept_ids": list(self.prerequisite_concept_ids),
            "source_refs": [ref.to_dict() for ref in self.source_refs],
            "metadata": copy.deepcopy(self.metadata),
        }


class PrerequisiteGraph:
    """Validated directed acyclic graph (DAG) of concept prerequisite relationships.
    
    Edges are directed from prerequisite -> dependent (i.e. P must be understood before D).
    """

    def __init__(self, nodes: Optional[Dict[str, ConceptNode]] = None) -> None:
        self._nodes: Dict[str, ConceptNode] = {}
        # Adjacency lists:
        # _prereqs[concept_id] = set of direct prerequisites that concept_id requires
        self._prereqs: Dict[str, Set[str]] = {}
        # _dependents[concept_id] = set of direct concepts that depend on concept_id
        self._dependents: Dict[str, Set[str]] = {}

        if nodes:
            for cid, node in nodes.items():
                self.add_node(node)
            self.validate_graph()

    def add_node(self, node: ConceptNode) -> None:
        """Adds a concept node to the graph and initializes adjacency entries."""
        cid = node.concept_id.strip()
        self._nodes[cid] = node
        if cid not in self._prereqs:
            self._prereqs[cid] = set()
        if cid not in self._dependents:
            self._dependents[cid] = set()

        for prereq_id in node.prerequisite_concept_ids:
            p_id = prereq_id.strip()
            self._prereqs[cid].add(p_id)
            if p_id not in self._dependents:
                self._dependents[p_id] = set()
            self._dependents[p_id].add(cid)

    def _resolve_id(self, concept_id: str) -> str:
        cid = str(concept_id).strip()
        if cid in self._nodes:
            return cid
        try:
            from src.migration_adapter import CanonicalConceptMigrationAdapter
            adapter = CanonicalConceptMigrationAdapter()
            canonical = adapter.to_canonical_id(cid, default_split_to_ray=True)
            if canonical in self._nodes:
                return canonical
        except Exception:
            pass
        return cid

    def get_node(self, concept_id: str) -> Optional[ConceptNode]:
        """Retrieves a concept node by canonical or legacy identifier."""
        return self._nodes.get(self._resolve_id(concept_id))

    def contains(self, concept_id: str) -> bool:
        """Checks if concept_id exists in the graph."""
        return self._resolve_id(concept_id) in self._nodes

    def has_node(self, concept_id: str) -> bool:
        """Checks if concept_id exists in the graph."""
        return self.contains(concept_id)

    @property
    def concept_ids(self) -> List[str]:
        """Returns sorted list of all concept identifiers in graph."""
        return sorted(self._nodes.keys())

    def __len__(self) -> int:
        return len(self._nodes)

    def get_direct_prerequisites(self, concept_id: str) -> List[str]:
        """Returns sorted list of direct prerequisites required by concept_id."""
        cid = self._resolve_id(concept_id)
        if cid not in self._nodes:
            raise KeyError(f"Concept '{cid}' not found in knowledge graph.")
        return sorted(self._prereqs.get(cid, set()))

    def get_direct_dependents(self, concept_id: str) -> List[str]:
        """Returns sorted list of direct downstream concepts depending on concept_id."""
        cid = self._resolve_id(concept_id)
        if cid not in self._nodes:
            raise KeyError(f"Concept '{cid}' not found in knowledge graph.")
        return sorted(self._dependents.get(cid, set()))

    def get_all_ancestor_prerequisites(self, concept_id: str) -> Set[str]:
        """Returns all transitive prerequisite concept IDs required (ancestors in DAG)."""
        cid = self._resolve_id(concept_id)
        if cid not in self._nodes:
            raise KeyError(f"Concept '{cid}' not found in knowledge graph.")

        ancestors: Set[str] = set()
        stack = list(self._prereqs.get(cid, set()))

        while stack:
            curr = stack.pop()
            if curr not in ancestors:
                ancestors.add(curr)
                stack.extend(self._prereqs.get(curr, set()) - ancestors)

        return ancestors

    def get_all_descendant_dependents(self, concept_id: str) -> Set[str]:
        """Returns all transitive downstream concept IDs depending on concept_id."""
        cid = self._resolve_id(concept_id)
        if cid not in self._nodes:
            raise KeyError(f"Concept '{cid}' not found in knowledge graph.")

        descendants: Set[str] = set()
        stack = list(self._dependents.get(cid, set()))

        while stack:
            curr = stack.pop()
            if curr not in descendants:
                descendants.add(curr)
                stack.extend(self._dependents.get(curr, set()) - descendants)

        return descendants

    def detect_cycles(self) -> List[List[str]]:
        """Detects directed cycles in the prerequisite graph using depth-first search.
        
        Returns:
            List of detected cycles, each formatted as a list of concept IDs forming the loop.
        """
        WHITE = 0  # unvisited
        GRAY = 1   # currently in recursion stack
        BLACK = 2  # completely visited

        color: Dict[str, int] = {cid: WHITE for cid in self._nodes}
        path: List[str] = []
        cycles: List[List[str]] = []

        def dfs(node: str) -> None:
            color[node] = GRAY
            path.append(node)

            for neighbor in self._prereqs.get(node, set()):
                if neighbor not in self._nodes:
                    continue  # Missing references checked separately
                if color[neighbor] == GRAY:
                    # Cycle detected: extract cycle segment from path
                    idx = path.index(neighbor)
                    cycles.append(path[idx:] + [neighbor])
                elif color[neighbor] == WHITE:
                    dfs(neighbor)

            path.pop()
            color[node] = BLACK

        for cid in sorted(self._nodes.keys()):
            if color[cid] == WHITE:
                dfs(cid)

        return cycles

    def find_invalid_prerequisite_references(self) -> List[Tuple[str, str]]:
        """Identifies any prerequisite edge referencing a concept not defined in the graph.
        
        Returns:
            List of (dependent_concept_id, missing_prerequisite_id) pairs.
        """
        invalid_refs: List[Tuple[str, str]] = []
        for cid, prereqs in self._prereqs.items():
            for p_id in sorted(prereqs):
                if p_id not in self._nodes:
                    invalid_refs.append((cid, p_id))
        return invalid_refs

    def validate_graph(self) -> None:
        """Validates that the prerequisite graph is well-formed:
        1. No references to undefined concepts.
        2. No circular prerequisite dependencies (must be a valid DAG).
        
        Raises:
            ValueError: If missing references or cycles are detected.
        """
        invalid_refs = self.find_invalid_prerequisite_references()
        if invalid_refs:
            raise ValueError(
                f"Prerequisite graph contains {len(invalid_refs)} broken references to undefined concepts: "
                f"{invalid_refs[:5]}"
            )

        cycles = self.detect_cycles()
        if cycles:
            raise ValueError(
                f"Prerequisite graph contains {len(cycles)} circular dependencies: {cycles[:3]}"
            )

    def topological_sort(self) -> List[str]:
        """Returns concept IDs sorted in valid pedagogical/topological curriculum order.
        
        A concept always appears AFTER all of its prerequisites.
        """
        self.validate_graph()

        in_degree: Dict[str, int] = {cid: len(self._prereqs.get(cid, set())) for cid in self._nodes}
        queue = [cid for cid in sorted(self._nodes.keys()) if in_degree[cid] == 0]
        result: List[str] = []

        while queue:
            # Deterministic pop (alphabetical)
            queue.sort()
            curr = queue.pop(0)
            result.append(curr)

            for dep in sorted(self._dependents.get(curr, set())):
                in_degree[dep] -= 1
                if in_degree[dep] == 0:
                    queue.append(dep)

        if len(result) != len(self._nodes):
            raise RuntimeError("Topological sort failed: graph may contain unhandled cycles.")

        return result

    def evaluate_prerequisite_readiness(
        self,
        concept_id: str,
        learner_concept_mastery: Dict[str, float],
        mastery_threshold: float = 0.50,
    ) -> Tuple[bool, Dict[str, str], List[str]]:
        """Evaluates whether a learner has satisfied prerequisites for candidate concept.
        
        Args:
            concept_id: Candidate concept under consideration.
            learner_concept_mastery: Map of concept_id -> estimated mastery probability.
            mastery_threshold: Minimum probability to consider a prerequisite satisfied (default 0.50).
            
        Returns:
            Tuple of:
            - is_ready (bool): True if ALL direct prerequisites are satisfied.
            - prerequisite_status_map (Dict[str, str]): 'satisfied' | 'unsatisfied' | 'unknown'.
            - remediation_needed (List[str]): List of unsatisfied or unknown prerequisite concept IDs.
        """
        cid = self._resolve_id(concept_id)
        if cid not in self._nodes:
            raise KeyError(f"Concept '{cid}' not found in knowledge graph.")

        direct_prereqs = self.get_direct_prerequisites(cid)
        if not direct_prereqs:
            # Root concept with no prerequisites is always ready
            return True, {}, []

        resolved_mastery: Dict[str, float] = {}
        for k, v in learner_concept_mastery.items():
            resolved_mastery[k.strip()] = v
            res_k = self._resolve_id(k)
            if res_k not in resolved_mastery:
                resolved_mastery[res_k] = v

        status_map: Dict[str, str] = {}
        remediation_needed: List[str] = []

        for p_id in direct_prereqs:
            if p_id not in resolved_mastery:
                status_map[p_id] = "unknown"
                remediation_needed.append(p_id)
            else:
                m_val = resolved_mastery[p_id]
                if m_val >= mastery_threshold:
                    status_map[p_id] = "satisfied"
                else:
                    status_map[p_id] = "unsatisfied"
                    remediation_needed.append(p_id)

        is_ready = len(remediation_needed) == 0
        return is_ready, status_map, remediation_needed

    def get_remediation_sequence(
        self,
        target_concept_id: str,
        learner_concept_mastery: Dict[str, float],
        mastery_threshold: float = 0.50,
    ) -> List[str]:
        """Computes a topologically ordered sequence of prerequisite concepts needing remediation.
        
        Orders concepts so that foundational prerequisites come first.
        """
        all_ancestors = self.get_all_ancestor_prerequisites(target_concept_id)
        resolved_mastery: Dict[str, float] = {}
        for k, v in learner_concept_mastery.items():
            resolved_mastery[k.strip()] = v
            res_k = self._resolve_id(k)
            if res_k not in resolved_mastery:
                resolved_mastery[res_k] = v

        broken_ancestors = {
            anc for anc in all_ancestors
            if resolved_mastery.get(anc, 0.0) < mastery_threshold
        }

        if not broken_ancestors:
            return []

        # Order topologically
        full_topo = self.topological_sort()
        return [cid for cid in full_topo if cid in broken_ancestors]


def load_knowledge_graph_from_csv(
    file_path: Optional[Union[str, Path]] = None,
) -> PrerequisiteGraph:
    """Loads and validates a PrerequisiteGraph from concepts.csv.
    
    Expected CSV columns:
        concept_id, subject, concept_name, topic_group, prerequisite_ids, curriculum_status
    """
    path = Path(file_path or DEFAULT_CONCEPTS_CSV)
    if not path.is_file():
        raise FileNotFoundError(f"Concepts CSV not found at: {path.resolve()}")

    nodes: Dict[str, ConceptNode] = {}

    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cid = row["concept_id"].strip()
            name = row.get("concept_name", cid).strip()
            subject = row.get("subject", "").strip() or None
            topic_group = row.get("topic_group", "").strip() or None
            status = "active" if "pilot" in row.get("curriculum_status", "active") or row.get("curriculum_status") == "active" else "active"

            raw_prereqs = row.get("prerequisite_ids", "").strip()
            if raw_prereqs:
                prereq_ids = [p.strip() for p in raw_prereqs.split(";") if p.strip()]
            else:
                prereq_ids = []

            # Populate canonical source references based on standard NCERT/JEE syllabus
            source_refs = [
                SourceReference(
                    source_id=f"NCERT_{subject or 'JEE'}_{topic_group or 'CORE'}",
                    locator=f"Concept:{cid}",
                )
            ]

            node = ConceptNode(
                concept_id=cid,
                name=name,
                description=f"{subject or 'Curriculum'} — {topic_group or 'Core'}: {name}",
                subject=subject,
                topic_group=topic_group,
                chapter_id=topic_group,
                tags=[subject.lower() if subject else "jee", "jee_core"],
                status=status,
                prerequisite_concept_ids=prereq_ids,
                source_refs=source_refs,
                metadata={"topic_group": topic_group},
            )
            nodes[cid] = node

    return PrerequisiteGraph(nodes)
