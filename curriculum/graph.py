"""
Deterministic curriculum graph validation and prerequisite traversal (Person 2).

What is validated, and why it matters to the rest of the platform:

* **endpoint existence** – an edge naming a concept that is not in the graph would
  let the Phase 4 planner walk off the end of the graph.
* **self loops** – ``A --prerequisite_of--> A`` is never true educationally.
* **duplicate edges** – two records for the same (source, type, target) double
  count in traversal and inflate quality metrics.
* **duplicate concepts** – two canonical concepts for the same term in the same
  subject is exactly the bug alias normalization exists to prevent.
* **prerequisite direction** – ``A --prerequisite_of--> B`` must agree with
  ``B.prerequisite_concept_ids ∋ A``.  Storing the same fact twice in two shapes
  invites silent divergence, so disagreement is an error, not a preference.
* **prerequisite cycles** – a cycle means "learn A after B and B after A".  These
  are rejected (not silently broken) because a cycle is a *curriculum defect*
  that a human must fix; auto-breaking it would hide the mistake and make the
  answer depend on iteration order.

Only ``prerequisite_of`` edges are required to be acyclic.  Other educational
relations (``related_to``, ``contrasts_with`` …) are allowed to be cyclic; that
is normal and not a defect.

Everything here is deterministic: identical input produces byte-identical issue
lists and identical traversal orders.
"""

from __future__ import annotations

import heapq
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from pydantic import BaseModel, ConfigDict, Field

from curriculum.models import (
    CanonicalConcept,
    ConceptLifecycleStatus,
    CurriculumGraph,
    CurriculumGraphError,  # noqa: F401  re-exported for ``curriculum.__init__``
)
from phase2.models import RelationshipStatusEnum, RelationshipTypeEnum

__all__ = [
    "CurriculumGraphError",
    "CurriculumGraphValidator",
    "GraphIssue",
    "GraphValidationReport",
    "IssueSeverity",
    "PrerequisiteCycleError",
    "SCC",
    "cycle_safe_topological_order",
    "dependent_closure",
    "derive_topological_depth",
    "prerequisite_adjacency",
    "prerequisite_closure",
    "prerequisite_subgraph",
    "reverse_prerequisite_adjacency",
    "topological_order",
    "would_create_cycle",
]


class PrerequisiteCycleError(Exception):
    """Raised when a strict topological order is requested from a cyclic graph."""

    def __init__(self, cycles: Sequence[Sequence[str]]):
        self.cycles = [list(cycle) for cycle in cycles]
        super().__init__(f"Prerequisite cycle(s) detected: {self.cycles}")


class IssueSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


_SEVERITY_ORDER = {IssueSeverity.ERROR: 0, IssueSeverity.WARNING: 1, IssueSeverity.INFO: 2}


class GraphIssue(BaseModel):
    """One actionable validation finding."""

    model_config = ConfigDict(extra="forbid")

    code: str
    severity: IssueSeverity
    message: str
    subject_id: Optional[str] = None
    target_id: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)

    def sort_key(self) -> Tuple[int, str, str, str]:
        return (
            _SEVERITY_ORDER[self.severity],
            self.code,
            self.subject_id or "",
            self.target_id or "",
        )


class GraphValidationReport(BaseModel):
    """Deterministic validation result.  ``is_valid`` means "no error-severity issue"."""

    model_config = ConfigDict(extra="forbid")

    is_valid: bool = True
    error_count: int = 0
    warning_count: int = 0
    issues: List[GraphIssue] = Field(default_factory=list)
    stats: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_issues(cls, issues: Iterable[GraphIssue], stats: Optional[Dict[str, Any]] = None) -> "GraphValidationReport":
        ordered = sorted(issues, key=lambda issue: issue.sort_key())
        errors = sum(1 for issue in ordered if issue.severity == IssueSeverity.ERROR)
        warnings = sum(1 for issue in ordered if issue.severity == IssueSeverity.WARNING)
        return cls(
            is_valid=errors == 0,
            error_count=errors,
            warning_count=warnings,
            issues=ordered,
            stats=stats or {},
        )

    def issues_with_code(self, code: str) -> List[GraphIssue]:
        return [issue for issue in self.issues if issue.code == code]


class SCC(BaseModel):
    """One strongly connected component returned by Tarjan's algorithm."""

    nodes: List[str]

    @property
    def is_cycle(self) -> bool:
        return len(self.nodes) > 1


def _tarjan_scc(nodes: Sequence[str], adjacency: Dict[str, List[str]]) -> List[SCC]:
    """
    Iterative Tarjan strongly connected components.

    Iterative rather than recursive so a pathological graph cannot blow the
    interpreter stack, and every node list is sorted so results are reproducible.
    """
    index_counter = 0
    indices: Dict[str, int] = {}
    lowlink: Dict[str, int] = {}
    on_stack: Set[str] = set()
    stack: List[str] = []
    components: List[SCC] = []

    for root in nodes:
        if root in indices:
            continue
        work: List[Tuple[str, int]] = [(root, 0)]
        while work:
            node, child_index = work[-1]
            if child_index == 0:
                indices[node] = index_counter
                lowlink[node] = index_counter
                index_counter += 1
                stack.append(node)
                on_stack.add(node)
            children = adjacency.get(node, [])
            advanced = False
            while child_index < len(children):
                child = children[child_index]
                child_index += 1
                if child not in indices:
                    work[-1] = (node, child_index)
                    work.append((child, 0))
                    advanced = True
                    break
                if child in on_stack:
                    lowlink[node] = min(lowlink[node], indices[child])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                lowlink[parent] = min(lowlink[parent], lowlink[node])
            if lowlink[node] == indices[node]:
                component: List[str] = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                components.append(SCC(nodes=sorted(component)))
    return sorted(components, key=lambda component: component.nodes)


class CurriculumGraphValidator:
    """
    Validates a :class:`~curriculum.models.CurriculumGraph`.

    ``validate`` never mutates the graph.  Use :meth:`validate` output to decide
    what a teacher must fix; do not "repair" the graph automatically.
    """

    #: An accepted prerequisite edge with no evidence and low confidence is
    #: reported rather than trusted.  Documented threshold, not a learned value.
    MIN_ACCEPTED_PREREQUISITE_CONFIDENCE = 0.5

    #: Extraction methods that mean "a human decided this, not a pattern matcher".
    #: Such edges carry their provenance in the review ledger instead of a source
    #: excerpt, so they are not flagged as unsupported:
    #:
    #: * ``curriculum_review`` / ``teacher_authored`` -- accepted through
    #:   ``CurriculumReviewService``, which records who decided and when;
    #: * ``curriculum_spec`` -- declared in a ``seed.py`` spec, which is a
    #:   human-authored curriculum declaration (the spec file is the source, and
    #:   concepts seeded from it may carry their own ``source_refs``).
    HUMAN_AUTHORED_METHODS = {"curriculum_review", "teacher_authored", "curriculum_spec"}

    def validate(self, graph: CurriculumGraph) -> GraphValidationReport:
        issues: List[GraphIssue] = []
        issues.extend(self._check_duplicate_concepts(graph))
        issues.extend(self._check_relationships(graph))
        issues.extend(self._check_prerequisite_lists(graph))
        issues.extend(self._check_prerequisite_cycles(graph))
        issues.extend(self._check_orphans(graph))
        return GraphValidationReport.from_issues(issues, stats=self.stats(graph))

    # ------------------------------------------------------------------ stats
    def stats(self, graph: CurriculumGraph) -> Dict[str, Any]:
        concepts = list(graph.concepts.values())
        active = [
            concept
            for concept in concepts
            if _status(concept.status) != ConceptLifecycleStatus.DEPRECATED.value
        ]
        relationships = list(graph.relationships.values())
        prerequisite_edges = [rel for rel in relationships if rel.is_prerequisite]
        accepted = [rel for rel in relationships if rel.status_value == "accepted"]
        return {
            "concept_count": len(concepts),
            "active_concept_count": len(active),
            "deprecated_concept_count": len(concepts) - len(active),
            "relationship_count": len(relationships),
            "accepted_relationship_count": len(accepted),
            "prerequisite_edge_count": len(prerequisite_edges),
            "accepted_prerequisite_edge_count": len(
                [rel for rel in prerequisite_edges if rel.status_value == "accepted"]
            ),
            "concept_with_evidence_count": len(
                [concept for concept in concepts if concept.source_refs]
            ),
            "id_map_size": len(graph.id_map),
        }

    # ---------------------------------------------------------------- concepts
    def _active_concepts(self, graph: CurriculumGraph) -> List[CanonicalConcept]:
        return sorted(
            (
                concept
                for concept in graph.concepts.values()
                if _status(concept.status) != ConceptLifecycleStatus.DEPRECATED.value
            ),
            key=lambda concept: concept.concept_id,
        )

    def _check_duplicate_concepts(self, graph: CurriculumGraph) -> List[GraphIssue]:
        issues: List[GraphIssue] = []
        by_subject_name: Dict[Tuple[str, str], List[CanonicalConcept]] = {}
        for concept in self._active_concepts(graph):
            by_subject_name.setdefault((concept.subject_value, concept.normalized_name), []).append(concept)

        for (subject, name), group in sorted(by_subject_name.items(), key=lambda item: item[0]):
            if len(group) < 2:
                continue
            ids = sorted(concept.concept_id for concept in group)
            issues.append(
                GraphIssue(
                    code="DUPLICATE_CONCEPT_NAME",
                    severity=IssueSeverity.ERROR,
                    message=(
                        f"{len(group)} active concepts in subject '{subject}' share the normalized "
                        f"name '{name}': {ids}. Merge them or give them distinct names/aliases."
                    ),
                    subject_id=ids[0],
                    details={"subject": subject, "normalized_name": name, "concept_ids": ids},
                )
            )

        # Alias colliding with another concept's name or alias in the same subject
        # means two canonical records describe the same idea.
        surfaces: Dict[Tuple[str, str], List[Tuple[str, str]]] = {}
        for concept in self._active_concepts(graph):
            for entry in concept.surface_keys():
                surfaces.setdefault((concept.subject_value, entry["surface"]), []).append(
                    (concept.concept_id, entry["kind"])
                )
        for (subject, surface), owners in sorted(surfaces.items(), key=lambda item: item[0]):
            distinct = sorted({concept_id for concept_id, _ in owners})
            if len(distinct) < 2:
                continue
            kinds = sorted({kind for _, kind in owners})
            if kinds == ["alias"]:
                # Two concepts declaring the same alias: still a duplicate signal,
                # but with lower confidence than a name collision.
                code, severity = "DUPLICATE_CONCEPT_ALIAS", IssueSeverity.ERROR
            else:
                code, severity = "ALIAS_COLLIDES_WITH_CANONICAL_NAME", IssueSeverity.ERROR
            issues.append(
                GraphIssue(
                    code=code,
                    severity=severity,
                    message=(
                        f"Surface form '{surface}' in subject '{subject}' is claimed by concepts "
                        f"{distinct} ({'/'.join(kinds)}). They likely denote the same concept."
                    ),
                    subject_id=distinct[0],
                    details={"subject": subject, "surface": surface, "concept_ids": distinct, "kinds": kinds},
                )
            )
        return issues

    # ------------------------------------------------------------ relationships
    def _check_relationships(self, graph: CurriculumGraph) -> List[GraphIssue]:
        issues: List[GraphIssue] = []
        seen: Dict[Tuple[str, str, str], str] = {}
        for relationship in sorted(
            graph.relationships.values(), key=lambda rel: rel.relationship_id
        ):
            source_known = relationship.source in graph.concepts
            target_known = relationship.target in graph.concepts
            if not source_known:
                issues.append(
                    GraphIssue(
                        code="MISSING_SOURCE_CONCEPT",
                        severity=IssueSeverity.ERROR,
                        message=(
                            f"Relationship '{relationship.relationship_id}' has source "
                            f"'{relationship.source}' which is not a canonical concept."
                        ),
                        subject_id=relationship.relationship_id,
                        target_id=relationship.source,
                    )
                )
            if not target_known:
                issues.append(
                    GraphIssue(
                        code="MISSING_TARGET_CONCEPT",
                        severity=IssueSeverity.ERROR,
                        message=(
                            f"Relationship '{relationship.relationship_id}' has target "
                            f"'{relationship.target}' which is not a canonical concept."
                        ),
                        subject_id=relationship.relationship_id,
                        target_id=relationship.target,
                    )
                )
            if relationship.source == relationship.target:
                issues.append(
                    GraphIssue(
                        code="SELF_LOOP",
                        severity=IssueSeverity.ERROR,
                        message=(
                            f"Relationship '{relationship.relationship_id}' loops from "
                            f"'{relationship.source}' to itself."
                        ),
                        subject_id=relationship.relationship_id,
                        target_id=relationship.source,
                    )
                )
            if relationship.status_value != RelationshipStatusEnum.REJECTED.value:
                key = (relationship.source, relationship.type_value, relationship.target)
                if key in seen:
                    issues.append(
                        GraphIssue(
                            code="DUPLICATE_RELATIONSHIP",
                            severity=IssueSeverity.ERROR,
                            message=(
                                f"Edges '{seen[key]}' and '{relationship.relationship_id}' both assert "
                                f"{key[0]} --{key[1]}--> {key[2]}."
                            ),
                            subject_id=relationship.relationship_id,
                            target_id=seen[key],
                            details={"source": key[0], "type": key[1], "target": key[2]},
                        )
                    )
                else:
                    seen[key] = relationship.relationship_id

            if (
                relationship.status_value == RelationshipStatusEnum.ACCEPTED.value
                and not (relationship.evidence_ids or relationship.source_refs)
                and (relationship.extraction_method or "") not in self.HUMAN_AUTHORED_METHODS
            ):
                issues.append(
                    GraphIssue(
                        code="UNSUPPORTED_RELATIONSHIP",
                        severity=IssueSeverity.WARNING,
                        message=(
                            f"Accepted relationship '{relationship.relationship_id}' carries no source "
                            f"evidence; it is an assertion, not a sourced curriculum fact."
                        ),
                        subject_id=relationship.relationship_id,
                    )
                )
            if (
                relationship.is_prerequisite
                and relationship.status_value == RelationshipStatusEnum.ACCEPTED.value
                and relationship.confidence < self.MIN_ACCEPTED_PREREQUISITE_CONFIDENCE
            ):
                issues.append(
                    GraphIssue(
                        code="LOW_CONFIDENCE_PREREQUISITE",
                        severity=IssueSeverity.WARNING,
                        message=(
                            f"Accepted prerequisite '{relationship.relationship_id}' has confidence "
                            f"{relationship.confidence:.2f} below "
                            f"{self.MIN_ACCEPTED_PREREQUISITE_CONFIDENCE}."
                        ),
                        subject_id=relationship.relationship_id,
                    )
                )
            if relationship.source in graph.concepts and _status(
                graph.concepts[relationship.source].status
            ) == ConceptLifecycleStatus.DEPRECATED.value:
                issues.append(
                    GraphIssue(
                        code="EDGE_FROM_DEPRECATED_CONCEPT",
                        severity=IssueSeverity.WARNING,
                        message=(
                            f"Relationship '{relationship.relationship_id}' starts at deprecated concept "
                            f"'{relationship.source}'; rewrite it to the successor concept."
                        ),
                        subject_id=relationship.relationship_id,
                        target_id=relationship.source,
                    )
                )
        return issues

    # -------------------------------------------------------- prerequisite lists
    def _check_prerequisite_lists(self, graph: CurriculumGraph) -> List[GraphIssue]:
        """The concept-level list and the typed edge set must say the same thing."""
        issues: List[GraphIssue] = []
        backed: Set[Tuple[str, str]] = {
            (rel.source, rel.target)
            for rel in graph.relationships.values()
            if rel.is_prerequisite and rel.status_value != RelationshipStatusEnum.REJECTED.value
        }
        for concept in self._active_concepts(graph):
            for prereq_id in concept.prerequisite_concept_ids:
                if prereq_id not in graph.concepts:
                    issues.append(
                        GraphIssue(
                            code="MISSING_PREREQUISITE_CONCEPT",
                            severity=IssueSeverity.ERROR,
                            message=(
                                f"Concept '{concept.concept_id}' lists prerequisite '{prereq_id}' "
                                f"which is not a canonical concept."
                            ),
                            subject_id=concept.concept_id,
                            target_id=prereq_id,
                        )
                    )
                    continue
                if prereq_id == concept.concept_id:
                    issues.append(
                        GraphIssue(
                            code="SELF_LOOP",
                            severity=IssueSeverity.ERROR,
                            message=f"Concept '{concept.concept_id}' lists itself as a prerequisite.",
                            subject_id=concept.concept_id,
                            target_id=prereq_id,
                        )
                    )
                    continue
                if (prereq_id, concept.concept_id) not in backed:
                    issues.append(
                        GraphIssue(
                            code="PREREQUISITE_LIST_UNBACKED",
                            severity=IssueSeverity.ERROR,
                            message=(
                                f"Concept '{concept.concept_id}' lists prerequisite '{prereq_id}' but no "
                                f"'prerequisite_of' edge asserts it."
                            ),
                            subject_id=concept.concept_id,
                            target_id=prereq_id,
                        )
                    )

        for rel in sorted(
            (r for r in graph.relationships.values() if r.is_prerequisite),
            key=lambda r: (r.source, r.target),
        ):
            if rel.status_value == RelationshipStatusEnum.REJECTED.value:
                continue
            if rel.source == rel.target:
                continue  # already reported as SELF_LOOP
            if rel.target not in graph.concepts:
                continue  # already reported as MISSING_TARGET_CONCEPT
            if rel.source not in graph.concepts:
                continue
            dependents = graph.concepts[rel.target].prerequisite_concept_ids
            if rel.source not in dependents:
                issues.append(
                    GraphIssue(
                        code="PREREQUISITE_DIRECTION_MISMATCH",
                        severity=IssueSeverity.ERROR,
                        message=(
                            f"Edge '{rel.relationship_id}' asserts {rel.source} --prerequisite_of--> "
                            f"{rel.target}, but '{rel.target}'.prerequisite_concept_ids does not list "
                            f"'{rel.source}'."
                        ),
                        subject_id=rel.relationship_id,
                        target_id=rel.target,
                        details={"expected_in": rel.target, "missing": rel.source},
                    )
                )
        return issues

    # ------------------------------------------------------------------ cycles
    def prerequisite_cycles(self, graph: CurriculumGraph) -> List[List[str]]:
        """Cycles among prerequisite edges over non-deprecated concepts."""
        nodes = [concept.concept_id for concept in self._active_concepts(graph)]
        node_set = set(nodes)
        adjacency: Dict[str, List[str]] = {node: [] for node in nodes}
        for rel in sorted(graph.relationships.values(), key=lambda r: r.relationship_id):
            if not rel.is_prerequisite or rel.status_value == RelationshipStatusEnum.REJECTED.value:
                continue
            if rel.source in node_set and rel.target in node_set:
                adjacency[rel.source].append(rel.target)
        for node in nodes:
            adjacency[node].sort()
        cycles = [component.nodes for component in _tarjan_scc(nodes, adjacency) if component.is_cycle]
        return sorted(cycles, key=lambda cycle: cycle)

    def _check_prerequisite_cycles(self, graph: CurriculumGraph) -> List[GraphIssue]:
        issues: List[GraphIssue] = []
        for cycle in self.prerequisite_cycles(graph):
            issues.append(
                GraphIssue(
                    code="PREREQUISITE_CYCLE",
                    severity=IssueSeverity.ERROR,
                    message=(
                        "Prerequisite cycle: "
                        + " -> ".join(cycle + [cycle[0]])
                        + ". A learner cannot satisfy this ordering; a curriculum editor must break it."
                    ),
                    subject_id=cycle[0],
                    details={"cycle": cycle},
                )
            )
        return issues

    # ------------------------------------------------------------------ orphans
    def _check_orphans(self, graph: CurriculumGraph) -> List[GraphIssue]:
        connected: Set[str] = set()
        for rel in graph.relationships.values():
            if rel.status_value == RelationshipStatusEnum.REJECTED.value:
                continue
            connected.add(rel.source)
            connected.add(rel.target)
        for concept in graph.concepts.values():
            if concept.prerequisite_concept_ids:
                connected.add(concept.concept_id)
        issues: List[GraphIssue] = []
        active = self._active_concepts(graph)
        if len(active) > 1:
            for concept in active:
                if concept.concept_id not in connected:
                    issues.append(
                        GraphIssue(
                            code="ORPHAN_CONCEPT",
                            severity=IssueSeverity.WARNING,
                            message=(
                                f"Concept '{concept.concept_id}' ('{concept.name}') has no relationship "
                                f"to any other concept; prerequisite traversal cannot reach it."
                            ),
                            subject_id=concept.concept_id,
                        )
                    )
        return issues


# ------------------------------------------------------------------- traversal
def prerequisite_adjacency(
    graph: CurriculumGraph, concept_ids: Optional[Iterable[str]] = None
) -> Dict[str, List[str]]:
    """``A -> [B, ...]`` meaning "A must be learned before each B".  Deterministic."""
    allowed = set(concept_ids) if concept_ids is not None else set(graph.concepts)
    adjacency: Dict[str, List[str]] = {node: [] for node in sorted(allowed)}
    for rel in graph.prerequisite_edges(include_unreviewed=False):
        if rel.source in allowed and rel.target in allowed:
            adjacency.setdefault(rel.source, []).append(rel.target)
    for node in adjacency:
        adjacency[node] = sorted(set(adjacency[node]))
    return adjacency


def reverse_prerequisite_adjacency(
    graph: CurriculumGraph, concept_ids: Optional[Iterable[str]] = None
) -> Dict[str, List[str]]:
    """``B -> [A, ...]`` meaning "each A is a prerequisite of B"."""
    adjacency: Dict[str, List[str]] = {node: [] for node in sorted(prerequisite_adjacency(graph, concept_ids))}
    for source, targets in prerequisite_adjacency(graph, concept_ids).items():
        for target in targets:
            adjacency.setdefault(target, []).append(source)
    for node in adjacency:
        adjacency[node] = sorted(set(adjacency[node]))
    return adjacency


def prerequisite_closure(
    graph: CurriculumGraph, concept_id: str, max_depth: Optional[int] = None
) -> List[str]:
    """
    Every concept that must be learned before ``concept_id``, nearest first.

    Breadth-first with sorted neighbours, so the result is reproducible.  Uses
    *reviewed* prerequisite edges only: an unreviewed extraction guess must not
    decide a learner's path.
    """
    adjacency = reverse_prerequisite_adjacency(graph)
    start = graph.resolve_id(concept_id)
    if start is None:
        return []
    ordered: List[str] = []
    seen: Set[str] = {start}
    frontier: List[str] = [start]
    depth = 0
    while frontier:
        if max_depth is not None and depth >= max_depth:
            break
        following: List[str] = []
        for node in frontier:
            for parent in adjacency.get(node, []):
                if parent not in seen:
                    seen.add(parent)
                    ordered.append(parent)
                    following.append(parent)
        frontier = sorted(following)
        depth += 1
    return ordered


def dependent_closure(
    graph: CurriculumGraph, concept_id: str, max_depth: Optional[int] = None
) -> List[str]:
    """Every concept that depends on ``concept_id`` (mirror of the prerequisite closure)."""
    adjacency = prerequisite_adjacency(graph)
    start = graph.resolve_id(concept_id)
    if start is None:
        return []
    ordered: List[str] = []
    seen: Set[str] = {start}
    frontier: List[str] = [start]
    depth = 0
    while frontier:
        if max_depth is not None and depth >= max_depth:
            break
        following: List[str] = []
        for node in frontier:
            for child in adjacency.get(node, []):
                if child not in seen:
                    seen.add(child)
                    ordered.append(child)
                    following.append(child)
        frontier = sorted(following)
        depth += 1
    return ordered


def topological_order(
    graph: CurriculumGraph, concept_ids: Optional[Iterable[str]] = None
) -> List[str]:
    """
    Strict topological order over reviewed prerequisite edges (Kahn, min-heap).

    Raises :class:`PrerequisiteCycleError` rather than returning an arbitrary
    order when the prerequisite graph is cyclic.
    """
    adjacency = prerequisite_adjacency(graph, concept_ids)
    indegree: Dict[str, int] = {node: 0 for node in adjacency}
    for targets in adjacency.values():
        for target in targets:
            indegree[target] = indegree.get(target, 0) + 1
    ready = [node for node, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)
    order: List[str] = []
    while ready:
        node = heapq.heappop(ready)
        order.append(node)
        for target in adjacency.get(node, []):
            indegree[target] -= 1
            if indegree[target] == 0:
                heapq.heappush(ready, target)
    if len(order) != len(indegree):
        remaining = sorted(set(indegree) - set(order))
        cycles = CurriculumGraphValidator().prerequisite_cycles(graph)
        raise PrerequisiteCycleError(cycles or [remaining])
    return order


def derive_topological_depth(
    graph: CurriculumGraph, concept_ids: Optional[Iterable[str]] = None
) -> Dict[str, int]:
    """
    Derive the topological depth for each concept in the reviewed prerequisite DAG.

    Semantics:
    * Root concepts (no reviewed prerequisites) have depth 0.
    * A node's depth is 1 + max(depth of its direct reviewed prerequisites).
    * Supports multiple parents (longest prerequisite path).
    * Raises PrerequisiteCycleError if any prerequisite cycles exist.
    """
    order = topological_order(graph, concept_ids)
    rev_adj = reverse_prerequisite_adjacency(graph, concept_ids)
    depths: Dict[str, int] = {}
    for node in order:
        prereqs = rev_adj.get(node, [])
        if not prereqs:
            depths[node] = 0
        else:
            depths[node] = 1 + max(depths[p] for p in prereqs)
    return depths


def cycle_safe_topological_order(
    graph: CurriculumGraph, concept_ids: Optional[Iterable[str]] = None
) -> List[str]:
    """
    Topological order with cyclic nodes appended (sorted) instead of raising.

    This mirrors ``phase4.planning.prerequisite_resolver`` so the learning-path
    planner can still emit a deterministic order for a graph that a teacher has
    not finished cleaning up.
    """
    adjacency = prerequisite_adjacency(graph, concept_ids)
    indegree: Dict[str, int] = {node: 0 for node in adjacency}
    for targets in adjacency.values():
        for target in targets:
            indegree[target] = indegree.get(target, 0) + 1
    ready = [node for node, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)
    order: List[str] = []
    while ready:
        node = heapq.heappop(ready)
        order.append(node)
        for target in adjacency.get(node, []):
            indegree[target] -= 1
            if indegree[target] == 0:
                heapq.heappush(ready, target)
    cyclic = sorted(set(indegree) - set(order))
    return order + cyclic


def prerequisite_subgraph(
    graph: CurriculumGraph, concept_id: str, depth: Optional[int] = None
) -> Dict[str, Any]:
    """
    Slice of the graph around ``concept_id`` for the UI / planner.

    Returns ``{"concepts": [...], "relationships": [...]}`` sorted deterministically.
    """
    center = graph.resolve_id(concept_id)
    if center is None:
        return {"concepts": [], "relationships": []}
    included: Set[str] = {center}
    included.update(prerequisite_closure(graph, center, max_depth=depth))
    included.update(dependent_closure(graph, center, max_depth=depth))
    concepts = [graph.concepts[node].content_dict() for node in sorted(included)]
    relationships = [
        rel.content_dict()
        for rel in sorted(graph.relationships.values(), key=lambda r: r.relationship_id)
        if rel.source in included and rel.target in included
    ]
    return {"concepts": concepts, "relationships": relationships}


def _status(status: Any) -> str:
    return status.value if hasattr(status, "value") else str(status)


def _relationship_type_value(rel_type: Any) -> str:
    return rel_type.value if hasattr(rel_type, "value") else str(rel_type)


#: Convenience guard used by the review service before committing an edge.
PREREQUISITE_TYPE = RelationshipTypeEnum.PREREQUISITE_OF.value


def would_create_cycle(graph: CurriculumGraph, source: str, target: str) -> bool:
    """
    True when adding ``source --prerequisite_of--> target`` would create a cycle.

    The new edge closes a loop exactly when ``target`` already reaches ``source``
    through reviewed prerequisite edges.
    """
    if source == target:
        return True
    return target in set(prerequisite_closure(graph, source))
