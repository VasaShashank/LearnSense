"""
Read-only canonical graph adapter for Person 3's learner-modeling surface (Person 2).

Person 3's ``src/integration/knowledge_graph_adapter.py`` defaults to loading a
*simulator* CSV (``data/synthetic jee/v3/concepts.csv``) whenever no graph is
supplied.  That is fine for their isolated unit tests, but in integrated
operation the learner model, readiness checks and remediation sequencing must
read the **canonical** curriculum graph this repository owns.  This module is
that boundary: it projects a ``CurriculumGraph`` onto the query surface Person
3's code already calls, with no CSV path and no synthetic fallback.

Surface (mirrors Person 3's method names and signatures where practical)
------------------------------------------------------------------------
``PrerequisiteGraph`` methods::

    contains, concept_ids (property), get_node-style lookups via get_concept,
    get_direct_prerequisites, get_direct_dependents,
    get_all_ancestor_prerequisites, get_all_descendant_dependents,
    detect_cycles, find_invalid_prerequisite_references, validate_graph,
    topological_sort, evaluate_prerequisite_readiness, get_remediation_sequence

``KnowledgeGraphAdapter`` aliases::

    get_concept, get_prerequisites, get_dependents, get_all_concept_ids

Documented deviations from Person 3's types (kept deliberately):
--------------------------------------------------------------
* ``get_concept`` returns the shared ``concept_schema.json`` record produced by
  ``CanonicalConcept.to_contract_record()`` -- the same contract Person 3
  validates -- instead of Person 3's ``ConceptNode`` dataclass.  Person 2 does
  not import or re-implement Person 3's models.
* ``validate_graph()`` returns Person 2's structured ``GraphValidationReport``
  instead of raising ``ValueError``; ``report.is_valid`` is the pass/fail bit.
* ``topological_sort()`` raises ``curriculum.graph.PrerequisiteCycleError`` on a
  cyclic edge set (canonical stores reject accepted cycles up front, so this is
  a guard, not an expected path).
* Canonical-only additions: ``resolve_concept_id`` (historical-id forwarding),
  ``graph_fingerprint`` / ``curriculum_id`` / ``syllabus_version`` (graph-version
  compatibility checks), and ``accepted_only`` (edge-review policy).

Edge and traversal policy
-------------------------
* Direction: ``A --prerequisite_of--> B`` means A must be learned before B, so
  ``get_direct_prerequisites(B)`` returns ``[A]`` -- identical to Person 3's
  convention, verified by ``tests/unit/curriculum/test_person3_reference_equivalence.py``.
* By default only **accepted** (reviewed) prerequisite edges feed traversal
  (``accepted_only=True``): an unreviewed extraction guess must not gate a
  learner's path.  The canonical validator's cycle rejection then guarantees the
  traversal universe is a DAG.
* Deprecated concepts never appear in traversal results (``concept_ids``,
  closures, readiness, remediation).  ``get_concept`` still returns a
  deprecated record -- inspecting history is allowed, learning from it is not.
* A historical id that was merged/replaced resolves forward to its successor
  (``graph.resolve_id``); an id that no longer resolves raises ``KeyError`` from
  the traversal methods (matching Person 3's "unknown concept" behaviour) and
  returns ``None`` from ``get_concept``.

Read-only guarantee
-------------------
The adapter never mutates the graph and never touches a repository.  Load it via
``from_repository`` (which raises ``CanonicalGraphUnavailableError`` when the
canonical graph is absent) or construct it directly from an in-memory
``CurriculumGraph``.  There is no constructor default and no CSV loader: an
unavailable canonical graph is an explicit failure, never a silent fall back to
synthetic data.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from curriculum.graph import CurriculumGraphValidator, GraphValidationReport
from curriculum.models import ConceptLifecycleStatus, CurriculumGraph

class _CanonicalConceptNode:
    """Canonical node view conforming to Person 3 ConceptNode interface.

    Exposes all fields of Person 3's ``ConceptNode`` and ``to_contract_dict()``,
    so that downstream callers (e.g. KnowledgeGraphAdapter, StudyPlan, Service)
    can access ``node.name``, ``node.concept_id``, ``node.prerequisite_concept_ids``,
    ``node.to_contract_dict()`` directly without missing-attribute errors.
    """

    __slots__ = ("_record",)

    def __init__(self, record: Dict[str, Any]) -> None:
        self._record = record

    @property
    def concept_id(self) -> str:
        return str(self._record.get("concept_id", ""))

    @property
    def name(self) -> str:
        return str(self._record.get("name", ""))

    @property
    def description(self) -> str:
        return str(self._record.get("description", ""))

    @property
    def subject(self) -> Optional[str]:
        return self._record.get("subject")

    @property
    def chapter_id(self) -> Optional[str]:
        return self._record.get("chapter_id")

    @property
    def topic_group(self) -> Optional[str]:
        meta = self._record.get("metadata") or {}
        return meta.get("topic_group") or self._record.get("chapter_id")

    @property
    def tags(self) -> List[str]:
        return list(self._record.get("tags", []))

    @property
    def status(self) -> str:
        return str(self._record.get("status", "active"))

    @property
    def prerequisite_concept_ids(self) -> List[str]:
        return list(self._record.get("prerequisite_concept_ids", []))

    @property
    def source_refs(self) -> List[Any]:
        return list(self._record.get("source_refs", []))

    @property
    def metadata(self) -> Dict[str, Any]:
        return dict(self._record.get("metadata") or {})

    def to_contract_dict(self) -> Dict[str, Any]:
        return dict(self._record)

    def __bool__(self) -> bool:
        return True


__all__ = [
    "CanonicalGraphUnavailableError",
    "KnowledgeGraphAdapter",
]

#: Lifecycle status that removes a concept from learner traversal.
_DEPRECATED_STATUS = ConceptLifecycleStatus.DEPRECATED.value


class CanonicalGraphUnavailableError(RuntimeError):
    """
    The canonical curriculum graph could not be loaded.

    Raised (never silently substituted) when integrated operation asks for the
    canonical graph and the repository holds none for the requested curriculum
    id.  Callers must seed or restore the canonical curriculum; the adapter will
    not stand in synthetic data.
    """


def _status(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


class KnowledgeGraphAdapter:
    """
    Read-only view of the canonical curriculum graph exposing Person 3's queries.

    Instances are cheap and stateless with respect to the graph: every query
    reads from the ``CurriculumGraph`` handed in at construction, so a snapshot
    taken by another writer is never mixed into an in-flight traversal.
    """

    def __init__(self, graph: CurriculumGraph, accepted_only: bool = True) -> None:
        if not isinstance(graph, CurriculumGraph):
            raise TypeError(
                "KnowledgeGraphAdapter requires a canonical CurriculumGraph; "
                f"got {type(graph).__name__}. Synthetic/CSV graphs are not accepted here."
            )
        self._graph = graph
        self._accepted_only = bool(accepted_only)
        self._validator = CurriculumGraphValidator()

    @classmethod
    def from_repository(
        cls,
        repository: Any,
        curriculum_id: str,
        accepted_only: bool = True,
    ) -> "KnowledgeGraphAdapter":
        """
        Load the canonical graph through Person 2's own repository boundary.

        ``repository`` is any object with ``load_graph(curriculum_id)`` (i.e. a
        ``CurriculumRepository``).  Raises ``CanonicalGraphUnavailableError``
        when no canonical graph is stored for ``curriculum_id``.
        """
        loader = getattr(repository, "load_graph", None)
        if not callable(loader):
            raise TypeError(
                "from_repository requires a repository exposing load_graph(curriculum_id)"
            )
        graph = loader(curriculum_id)
        if graph is None:
            available: List[str] = []
            lister = getattr(repository, "list_curriculum_ids", None)
            if callable(lister):
                try:
                    available = list(lister())
                except Exception:  # pragma: no cover - defensive; availability is advisory
                    available = []
            raise CanonicalGraphUnavailableError(
                f"No canonical curriculum graph stored for '{curriculum_id}'. "
                "Seed the curriculum (e.g. POST /api/curriculum/seed) or restore the "
                "graph file before integrated learner-model operation. "
                f"Stored curricula: {available or 'none'}"
            )
        return cls(graph, accepted_only=accepted_only)

    # ------------------------------------------------------------ graph facts
    @property
    def graph(self) -> CurriculumGraph:
        """The underlying canonical graph (read-only by convention)."""
        return self._graph

    @property
    def accepted_only(self) -> bool:
        return self._accepted_only

    @property
    def curriculum_id(self) -> str:
        return self._graph.curriculum_id

    @property
    def syllabus_version(self) -> str:
        return self._graph.syllabus_version

    def graph_fingerprint(self) -> str:
        """Deterministic content fingerprint for graph-version compatibility checks."""
        return self._graph.content_fingerprint()

    @property
    def fingerprint(self) -> str:
        """Deterministic content fingerprint property."""
        return self._graph.content_fingerprint()

    def resolve_concept_id(self, concept_id: str) -> Optional[str]:
        """Follow merged/replaced tombstones to the concept that carries the meaning now."""
        return self._graph.resolve_id((concept_id or "").strip())

    # ------------------------------------------------------------- universes
    def _active_ids(self) -> Set[str]:
        return {
            concept_id
            for concept_id, concept in self._graph.concepts.items()
            if _status(concept.status) != _DEPRECATED_STATUS
        }

    def _adjacency(self) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
        """``(prereq -> [dependents], dependent -> [prereqs])`` over the traversal universe."""
        allowed = self._active_ids()
        forward: Dict[str, List[str]] = {node: [] for node in sorted(allowed)}
        reverse: Dict[str, List[str]] = {node: [] for node in sorted(allowed)}
        for rel in self._graph.prerequisite_edges(include_unreviewed=not self._accepted_only):
            if rel.source in allowed and rel.target in allowed:
                forward[rel.source].append(rel.target)
                reverse[rel.target].append(rel.source)
        for node in forward:
            forward[node] = sorted(set(forward[node]))
        for node in reverse:
            reverse[node] = sorted(set(reverse[node]))
        return forward, reverse

    def _traversal_id(self, concept_id: str) -> str:
        """Resolve a query id onto the traversal universe or raise ``KeyError``."""
        raw = (concept_id or "").strip()
        resolved = self._graph.resolve_id(raw)
        if resolved is None:
            raise KeyError(
                f"Concept '{raw}' does not resolve to a canonical concept "
                "(removed, split, or never defined)"
            )
        if resolved not in self._graph.concepts:
            raise KeyError(f"Concept '{raw}' not found in canonical graph '{self.curriculum_id}'")
        if resolved not in self._active_ids():
            raise KeyError(
                f"Concept '{resolved}' is deprecated and does not participate in "
                "learner traversal; resolve it to its successor first"
            )
        return resolved

    # ------------------------------------------------------------- identity
    @property
    def concept_ids(self) -> List[str]:
        """Sorted concept ids of the traversal universe (deprecated excluded)."""
        return sorted(self._active_ids())

    def __len__(self) -> int:
        return len(self._active_ids())

    def contains(self, concept_id: str) -> bool:
        raw = (concept_id or "").strip()
        resolved = self._graph.resolve_id(raw)
        return resolved is not None and resolved in self._active_ids()

    # -------------------------------------------------------------- reading
    def get_concept(self, concept_id: str) -> Optional[Dict[str, Any]]:
        """
        Contract record for a canonical concept, or ``None`` when unknown.

        Follows merged/replaced ids to the successor.  A deprecated tombstone
        still returns its own record (with ``status == "deprecated"``) so
        callers can inspect history; traversal methods refuse it separately.
        """
        raw = (concept_id or "").strip()
        resolved = self._graph.resolve_id(raw)
        if resolved is None:
            return None
        concept = self._graph.concepts.get(resolved)
        if concept is None:
            return None
        return concept.to_contract_record()

    def get_node(self, concept_id: str) -> Optional["_CanonicalConceptNode"]:
        """Node view exposing ``to_contract_dict()``, for Person 3's adapter wrapping.

        Person 3's ``KnowledgeGraphAdapter.get_concept`` calls
        ``self._graph.get_node(concept_id)`` and then ``.to_contract_dict()``.
        Returning ``None`` for unknown ids matches both Person 3's graph
        (direct lookup) and this adapter's ``get_concept`` (which also resolves
        merged/replaced historical ids forward).
        """
        record = self.get_concept(concept_id)
        if record is None:
            return None
        return _CanonicalConceptNode(record)

    def get_direct_prerequisites(self, concept_id: str) -> List[str]:
        """Sorted direct prerequisites: ``A --prerequisite_of--> B`` => ``get_direct_prerequisites(B) == [A]``."""
        _, reverse = self._adjacency()
        return list(reverse[self._traversal_id(concept_id)])

    def get_direct_dependents(self, concept_id: str) -> List[str]:
        """Sorted direct dependents (the inverse of :meth:`get_direct_prerequisites`)."""
        forward, _ = self._adjacency()
        return list(forward[self._traversal_id(concept_id)])

    # Aliases matching Person 3's KnowledgeGraphAdapter method names.
    def get_prerequisites(self, concept_id: str) -> List[str]:
        return self.get_direct_prerequisites(concept_id)

    def get_dependents(self, concept_id: str) -> List[str]:
        return self.get_direct_dependents(concept_id)

    def get_all_ancestor_prerequisites(self, concept_id: str) -> Set[str]:
        """Every transitive prerequisite (ancestors), unsorted like Person 3's set API."""
        start = self._traversal_id(concept_id)
        _, reverse = self._adjacency()
        ancestors: Set[str] = set()
        stack = list(reverse[start])
        while stack:
            current = stack.pop()
            if current not in ancestors:
                ancestors.add(current)
                stack.extend(node for node in reverse[current] if node not in ancestors)
        return ancestors

    def get_all_descendant_dependents(self, concept_id: str) -> Set[str]:
        """Every transitive dependent (descendants)."""
        start = self._traversal_id(concept_id)
        forward, _ = self._adjacency()
        descendants: Set[str] = set()
        stack = list(forward[start])
        while stack:
            current = stack.pop()
            if current not in descendants:
                descendants.add(current)
                stack.extend(node for node in forward[current] if node not in descendants)
        return descendants

    # -------------------------------------------------------------- ordering
    def topological_sort(self) -> List[str]:
        """
        Deterministic curriculum order: every concept after its prerequisites.

        Kahn's algorithm with alphabetical tie-breaking, over the same edge set
        the traversal methods use.
        """
        forward, _ = self._adjacency()
        indegree: Dict[str, int] = {node: 0 for node in forward}
        for targets in forward.values():
            for target in targets:
                indegree[target] += 1
        ready = sorted(node for node, degree in indegree.items() if degree == 0)
        ordered: List[str] = []
        while ready:
            current = ready.pop(0)
            ordered.append(current)
            for target in forward[current]:
                indegree[target] -= 1
                if indegree[target] == 0:
                    ready.append(target)
            ready.sort()
        if len(ordered) != len(forward):
            raise RuntimeError(
                "Topological sort failed: the traversal edge set contains a cycle "
                "(run validate_graph() for the canonical report)"
            )
        return ordered

    def get_all_concept_ids(self) -> List[str]:
        """Topological order of all traversal-universe concepts (Person 3 adapter alias)."""
        return self.topological_sort()

    # ------------------------------------------------------------ validation
    def detect_cycles(self) -> List[List[str]]:
        """Cycles in the traversal edge set, each as a sorted list of concept ids."""
        forward, _ = self._adjacency()
        white, gray, black = 0, 1, 2
        color: Dict[str, int] = {node: white for node in forward}
        cycles: List[List[str]] = []

        def walk(node: str, path: List[str]) -> None:
            color[node] = gray
            path.append(node)
            for neighbor in forward[node]:
                if color[neighbor] == gray:
                    cycles.append(sorted(set(path[path.index(neighbor):] + [neighbor])))
                elif color[neighbor] == white:
                    walk(neighbor, path)
            path.pop()
            color[node] = black

        for node in sorted(forward):
            if color[node] == white:
                walk(node, [])
        unique = sorted({tuple(cycle) for cycle in cycles})
        return [list(cycle) for cycle in unique]

    def find_invalid_prerequisite_references(self) -> List[Tuple[str, str]]:
        """
        ``(dependent, missing_prerequisite)`` pairs over stored edges and lists.

        Covers both representations the canonical store keeps: relationship rows
        and each concept's ``prerequisite_concept_ids`` list, so a dangling
        reference cannot hide in one of them.
        """
        pairs: Set[Tuple[str, str]] = set()
        known = set(self._graph.concepts)
        for rel in self._graph.relationships.values():
            if rel.is_prerequisite and (rel.source not in known or rel.target not in known):
                if rel.source not in known:
                    pairs.add((rel.target, rel.source))
                if rel.target not in known:
                    pairs.add((rel.source, rel.target))
        for concept in self._graph.concepts.values():
            for prereq in concept.prerequisite_concept_ids:
                if prereq not in known:
                    pairs.add((concept.concept_id, prereq))
        return sorted(pairs)

    def validate_graph(self) -> GraphValidationReport:
        """Canonical validation report (errors invalidate; warnings do not)."""
        return self._validator.validate(self._graph)

    # ------------------------------------------------------------- readiness
    def evaluate_prerequisite_readiness(
        self,
        concept_id: str,
        learner_concept_mastery: Dict[str, float],
        mastery_threshold: float = 0.50,
        *,
        threshold: Optional[float] = None,
    ) -> Tuple[bool, Dict[str, str], List[str]]:
        """
        Whether all direct prerequisites of ``concept_id`` meet the threshold.

        Returns ``(is_ready, prerequisite_status_map, remediation_needed)`` with
        ``status_map[p]`` in ``{"satisfied", "unsatisfied", "unknown"}`` --
        "unknown" meaning the mastery vector has no estimate for ``p`` (never
        silently treated as mastered).  Same tuple shape as Person 3's
        ``PrerequisiteGraph.evaluate_prerequisite_readiness``.
        """
        if threshold is not None:
            mastery_threshold = threshold

        cid = self._traversal_id(concept_id)
        _, reverse = self._adjacency()
        direct = reverse[cid]
        if not direct:
            return True, {}, []
        status_map: Dict[str, str] = {}
        remediation_needed: List[str] = []
        for prereq in direct:
            if prereq not in learner_concept_mastery:
                status_map[prereq] = "unknown"
                remediation_needed.append(prereq)
            elif learner_concept_mastery[prereq] >= mastery_threshold:
                status_map[prereq] = "satisfied"
            else:
                status_map[prereq] = "unsatisfied"
                remediation_needed.append(prereq)
        return len(remediation_needed) == 0, status_map, remediation_needed

    def get_remediation_sequence(
        self,
        target_concept_id: str,
        learner_concept_mastery: Dict[str, float],
        mastery_threshold: float = 0.50,
    ) -> List[str]:
        """
        Topologically ordered transitive prerequisites below the threshold.

        Foundational concepts come first, so the caller can remediate in order.
        A mastery estimate of ``0.0`` and a missing estimate are treated the
        same as Person 3 does (below threshold -> needs remediation).
        """
        target = self._traversal_id(target_concept_id)
        ancestors = self.get_all_ancestor_prerequisites(target)
        broken = {
            concept_id
            for concept_id in ancestors
            if learner_concept_mastery.get(concept_id, 0.0) < mastery_threshold
        }
        if not broken:
            return []
        order = self.topological_sort()
        return [concept_id for concept_id in order if concept_id in broken]
