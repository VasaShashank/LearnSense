"""
Curriculum / graph versioning (Person 2).

Snapshots are *content addressed*: ``content_checksum`` is the graph's
deterministic fingerprint and ``version_id`` is derived from it.  Two machines
that hold the same graph therefore produce the same version id, which is what
makes the evaluation fixtures and the Person 3 integration reproducible.

Historical references
---------------------
Learner attempts, question-to-concept references and teacher notes must keep
their meaning when the curriculum changes.  Snapshots keep the full graph as it
was, and :meth:`CurriculumVersioning.resolve_at` answers "what did concept X mean
in version Y" without consulting the live graph.  For the *live* graph the
``id_map`` on :class:`~curriculum.models.CurriculumGraph` resolves merged,
replaced and removed ids.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from curriculum.ids import generate_version_id
from curriculum.models import CanonicalConcept, ConceptLifecycleStatus, CurriculumGraph, utc_now_iso
from curriculum.repository import CurriculumRepository


class CurriculumVersion(BaseModel):
    """Metadata for one immutable curriculum snapshot."""

    model_config = ConfigDict(extra="forbid")

    version_id: str
    curriculum_id: str
    syllabus_version: str
    content_checksum: str
    concept_count: int = 0
    relationship_count: int = 0
    created_at: str = Field(default_factory=utc_now_iso)
    created_by: str = "curriculum_pipeline"
    parent_version_id: Optional[str] = None
    note: str = ""
    deprecated_concept_ids: List[str] = Field(default_factory=list)
    replaced_concept_ids: Dict[str, str] = Field(default_factory=dict)


class CurriculumSnapshot(BaseModel):
    """An immutable (version metadata + graph) pair."""

    model_config = ConfigDict(extra="forbid")

    version: CurriculumVersion
    graph: CurriculumGraph


class CurriculumVersioning:
    """Create, store and query immutable curriculum snapshots."""

    def __init__(self, repository: Optional[CurriculumRepository] = None):
        self.repository = repository or CurriculumRepository()

    # ----------------------------------------------------------------- create
    def snapshot(
        self,
        graph: CurriculumGraph,
        created_by: str = "curriculum_pipeline",
        note: str = "",
        parent_version_id: Optional[str] = None,
    ) -> CurriculumSnapshot:
        """
        Build a snapshot in memory.  Deterministic: the same graph content always
        yields the same ``version_id`` and ``content_checksum``.
        """
        checksum = graph.content_fingerprint()
        deprecated = sorted(
            concept.concept_id
            for concept in graph.concepts.values()
            if _status(concept.status) == ConceptLifecycleStatus.DEPRECATED.value
        )
        replaced = {
            entry.old_id: entry.current_id
            for entry in graph.id_map
            if entry.relation in {"merged_into", "replaced_by"} and entry.current_id
        }
        version = CurriculumVersion(
            version_id=generate_version_id(graph.curriculum_id, checksum),
            curriculum_id=graph.curriculum_id,
            syllabus_version=graph.syllabus_version,
            content_checksum=checksum,
            concept_count=len(graph.concepts),
            relationship_count=len(graph.relationships),
            created_by=created_by,
            parent_version_id=parent_version_id,
            note=note,
            deprecated_concept_ids=deprecated,
            replaced_concept_ids=replaced,
        )
        return CurriculumSnapshot(version=version, graph=graph.model_copy(deep=True))

    def commit(self, snapshot: CurriculumSnapshot) -> Path:
        """Persist a snapshot.  Re-committing an identical graph is a no-op write."""
        return self.repository.save_snapshot(snapshot)

    # ------------------------------------------------------------------ query
    def list_versions(self, curriculum_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.repository.list_snapshots(curriculum_id)

    def load(self, version_id: str) -> Optional[CurriculumSnapshot]:
        return self.repository.load_snapshot(version_id)

    def resolve_at(self, concept_id: str, version_id: str) -> Optional[CanonicalConcept]:
        """
        Resolve a concept reference *as it was* in a stored version.

        Returns ``None`` when the concept did not exist (or had already been
        merged away) in that version, so callers can distinguish "unknown
        concept" from "concept renamed since".
        """
        snapshot = self.load(version_id)
        if snapshot is None:
            return None
        resolved = snapshot.graph.resolve_id(concept_id)
        if resolved is None:
            return None
        return snapshot.graph.concepts.get(resolved)

    def diff(self, from_version_id: str, to_version_id: str) -> Dict[str, Any]:
        """Structured difference between two stored versions."""
        older = self.load(from_version_id)
        newer = self.load(to_version_id)
        if older is None or newer is None:
            missing = [v for v, s in ((from_version_id, older), (to_version_id, newer)) if s is None]
            raise KeyError(f"Unknown curriculum version(s): {', '.join(missing)}")
        return diff_graphs(older.graph, newer.graph)


def diff_graphs(older: CurriculumGraph, newer: CurriculumGraph) -> Dict[str, Any]:
    """Concept/relationship delta between two graphs (order independent)."""
    old_concepts = older.concepts
    new_concepts = newer.concepts
    added = sorted(set(new_concepts) - set(old_concepts))
    removed = sorted(set(old_concepts) - set(new_concepts))
    modified = sorted(
        concept_id
        for concept_id in set(old_concepts) & set(new_concepts)
        if old_concepts[concept_id].content_dict() != new_concepts[concept_id].content_dict()
    )
    renamed = {
        concept_id: {
            "from": old_concepts[concept_id].name,
            "to": new_concepts[concept_id].name,
        }
        for concept_id in modified
        if old_concepts[concept_id].name != new_concepts[concept_id].name
    }
    old_rel = older.relationships
    new_rel = newer.relationships
    return {
        "concepts_added": added,
        "concepts_removed": removed,
        "concepts_modified": modified,
        "concepts_renamed": renamed,
        "relationships_added": sorted(set(new_rel) - set(old_rel)),
        "relationships_removed": sorted(set(old_rel) - set(new_rel)),
        "relationships_modified": sorted(
            rel_id
            for rel_id in set(old_rel) & set(new_rel)
            if old_rel[rel_id].content_dict() != new_rel[rel_id].content_dict()
        ),
        "id_map_added": sorted(
            entry.old_id for entry in newer.id_map if entry.old_id not in {e.old_id for e in older.id_map}
        ),
        "concept_count_delta": len(new_concepts) - len(old_concepts),
        "relationship_count_delta": len(new_rel) - len(old_rel),
        "fingerprint_changed": older.content_fingerprint() != newer.content_fingerprint(),
    }


def _status(status: Any) -> str:
    return status.value if hasattr(status, "value") else str(status)
