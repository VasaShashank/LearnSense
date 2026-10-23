"""
Bridges from the canonical curriculum graph to existing platform types (Person 2).

Person 3 owns mastery, BKT, grading and recommendations.  Person 4 owns the
visualisation.  Neither should have to learn a second graph format to consume the
canonical curriculum, so this module translates *out* of ``curriculum`` and into
the read-only view models those workstreams already use:

* ``phase3.knowledge.phase2_adapter.ConceptView`` / ``PrerequisiteLink`` /
  ``LearningContext`` -- what the Phase 4 planner, the question bank and the
  gap analysis already traverse, and
* ``phase2.models.Relationship`` -- what Phase 5 validators and Phase 6 APIs
  expect.

Nothing here is a new data model; it is a one-way projection.  The canonical
graph stays the source of truth, and no learner state is written back.

``LearningContext.document_id`` is set to ``curriculum:<curriculum_id>`` so a
curriculum-derived context can never be mistaken for a per-document extraction
result when both are logged or cached side by side.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from phase2.models import Relationship as Phase2Relationship
from phase3.knowledge.phase2_adapter import (
    ConceptView,
    LearningContext,
    PrerequisiteLink,
)

from curriculum.models import ConceptLifecycleStatus, CurriculumGraph

__all__ = [
    "concept_id_resolver",
    "curriculum_to_concept_views",
    "curriculum_to_learning_context",
    "curriculum_to_phase2_relationships",
    "curriculum_to_prerequisite_links",
]

#: Prefix used to namespace a curriculum-derived document id.
CURRICULUM_DOCUMENT_PREFIX = "curriculum:"


def _status(status: Any) -> str:
    return status.value if hasattr(status, "value") else str(status)


def _active_concepts(graph: CurriculumGraph) -> List[str]:
    """Sorted concept ids of everything a consumer should be able to traverse."""
    return sorted(
        concept_id
        for concept_id, concept in graph.concepts.items()
        if _status(concept.status) != ConceptLifecycleStatus.DEPRECATED.value
    )


def curriculum_to_concept_views(graph: CurriculumGraph) -> Dict[str, ConceptView]:
    """
    Project canonical concepts onto the read-only ``ConceptView``.

    Evidence ids, pages, blocks and sections are taken from each concept's real
    ``source_refs``.  Concepts with no source evidence keep empty lists rather
    than borrowing another concept's provenance.
    """
    views: Dict[str, ConceptView] = {}
    for concept_id in _active_concepts(graph):
        concept = graph.concepts[concept_id]
        page_indices: List[int] = []
        block_ids: List[str] = []
        section_titles: List[str] = []
        evidence_ids: List[str] = []
        for ref in concept.source_refs:
            provenance = ref.provenance or {}
            page = provenance.get("page_index")
            if isinstance(page, int) and page not in page_indices:
                page_indices.append(page)
            for block_id in provenance.get("block_ids") or []:
                if block_id not in block_ids:
                    block_ids.append(block_id)
            section = provenance.get("section_title")
            if section and section not in section_titles:
                section_titles.append(section)
            for evidence_id in provenance.get("evidence_ids") or []:
                if evidence_id not in evidence_ids:
                    evidence_ids.append(evidence_id)
        views[concept_id] = ConceptView(
            concept_id=concept.concept_id,
            canonical_name=concept.name,
            aliases=list(concept.aliases),
            type="canonical_concept",
            description=concept.description,
            skill_ids=[],
            evidence_ids=evidence_ids,
            page_indices=page_indices,
            block_ids=block_ids,
            section_titles=section_titles,
        )
    return views


def curriculum_to_prerequisite_links(
    graph: CurriculumGraph, accepted_only: bool = True
) -> List[PrerequisiteLink]:
    """
    Project accepted ``prerequisite_of`` edges onto ``PrerequisiteLink``.

    Direction is preserved: ``A --prerequisite_of--> B`` becomes
    ``source=A, target=B`` ("A must come before B"), matching the convention
    ``phase4.planning`` already assumes.

    Edges touching deprecated concepts are skipped: the planner should walk the
    current curriculum, not the historical one.
    """
    active = set(_active_concepts(graph))
    links: List[PrerequisiteLink] = []
    for relationship in sorted(
        graph.relationships.values(), key=lambda rel: rel.relationship_id
    ):
        if not relationship.is_prerequisite:
            continue
        if accepted_only and relationship.status_value != "accepted":
            continue
        if relationship.source not in active or relationship.target not in active:
            continue
        links.append(
            PrerequisiteLink(
                source_concept_id=relationship.source,
                target_concept_id=relationship.target,
                confidence=relationship.confidence,
                evidence_ids=list(relationship.evidence_ids),
            )
        )
    # Deterministic order: (target, source) matches the traversal order the
    # planner uses when it walks prerequisites of a target concept.
    return sorted(links, key=lambda link: (link.target_concept_id, link.source_concept_id))


def curriculum_to_phase2_relationships(
    graph: CurriculumGraph, accepted_only: bool = False
) -> List[Phase2Relationship]:
    """Project every typed edge onto ``phase2.models.Relationship``."""
    relationships: List[Phase2Relationship] = []
    for relationship_id in sorted(graph.relationships):
        relationship = graph.relationships[relationship_id]
        if accepted_only and relationship.status_value != "accepted":
            continue
        relationships.append(relationship.to_phase2_relationship())
    return relationships


def curriculum_to_learning_context(
    graph: CurriculumGraph,
    document_id: Optional[str] = None,
    title: str = "",
    accepted_only: bool = True,
) -> LearningContext:
    """
    Build a ``LearningContext`` whose knowledge is the *canonical curriculum*.

    This lets the Phase 4 planner, the question bank and the gap analysis run
    against the curated curriculum instead of only against the last uploaded
    document.  Skills, formulas, educational units and assessable items are left
    empty: those are document-derived artifacts, and fabricating them for a
    curriculum-level context would misrepresent where they came from.
    """
    active = _active_concepts(graph)
    concepts = curriculum_to_concept_views(graph)
    prerequisites = curriculum_to_prerequisite_links(graph, accepted_only=accepted_only)
    relationships = curriculum_to_phase2_relationships(graph, accepted_only=accepted_only)
    return LearningContext(
        document_id=document_id or f"{CURRICULUM_DOCUMENT_PREFIX}{graph.curriculum_id}",
        knowledge_document_id=graph.curriculum_id,
        document_title=title or graph.title or graph.curriculum_id,
        source_filename="",
        chapters=[
            {"chapter_id": concept.chapter_id, "title": concept.chapter_id}
            for concept in _chapter_concepts(graph, active)
        ],
        sections=[],
        topics=[
            {"concept_id": concept_id, "topic_path": graph.concepts[concept_id].topic_path}
            for concept_id in active
            if graph.concepts[concept_id].topic_path
        ],
        concepts=concepts,
        skills={},
        formulas={},
        educational_units={},
        assessable_items={},
        concept_definitions=[],
        evidence={},
        prerequisites=prerequisites,
        trusted_relationships=relationships,
    )


def concept_id_resolver(graph: CurriculumGraph) -> Callable[[str], Optional[str]]:
    """
    A resolver for historical concept references (for Person 3).

    Returns a callable that maps any stored concept id to the id that now carries
    its meaning, or ``None`` when it no longer resolves.  Attach it to learner
    attempts, question banks and review notes so they survive merges and
    deprecations without being rewritten in place.
    """
    return graph.resolve_id


def _chapter_concepts(graph: CurriculumGraph, concept_ids: List[str]) -> List[Any]:
    seen: Dict[str, Any] = {}
    for concept_id in concept_ids:
        chapter_id = graph.concepts[concept_id].chapter_id
        if chapter_id and chapter_id not in seen:
            seen[chapter_id] = graph.concepts[concept_id]
    return list(seen.values())
