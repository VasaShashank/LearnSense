"""
Phase-2 → Phase-3 Knowledge Adapter and LearningContext.
Provides a clean abstraction over Phase 2 EducationalKnowledgeRepresentation (EKR).
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from phase2.models import (
    EducationalKnowledgeRepresentation,
    Concept,
    Skill,
    EducationalUnit,
    AssessableItem,
    Formula,
    Relationship,
    Evidence,
    RelationshipTypeEnum,
)


class ConceptView(BaseModel):
    concept_id: str
    canonical_name: str
    aliases: List[str] = Field(default_factory=list)
    type: str
    skill_ids: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)


class SkillView(BaseModel):
    skill_id: str
    action: str
    statement: str
    concept_ids: List[str] = Field(default_factory=list)


class PrerequisiteLink(BaseModel):
    source_concept_id: str
    target_concept_id: str
    confidence: float
    evidence_ids: List[str] = Field(default_factory=list)


class LearningContext(BaseModel):
    document_id: str
    knowledge_document_id: str
    chapters: List[Dict[str, Any]] = Field(default_factory=list)
    sections: List[Dict[str, Any]] = Field(default_factory=list)
    topics: List[Dict[str, Any]] = Field(default_factory=list)
    concepts: Dict[str, ConceptView] = Field(default_factory=dict)
    skills: Dict[str, SkillView] = Field(default_factory=dict)
    formulas: Dict[str, Formula] = Field(default_factory=dict)
    educational_units: Dict[str, EducationalUnit] = Field(default_factory=dict)
    assessable_items: Dict[str, AssessableItem] = Field(default_factory=dict)
    evidence: Dict[str, Evidence] = Field(default_factory=dict)
    prerequisites: List[PrerequisiteLink] = Field(default_factory=list)
    trusted_relationships: List[Relationship] = Field(default_factory=list)


class Phase2Adapter:
    """Adapter converting Phase 2 EKR to Phase 3 LearningContext."""

    @staticmethod
    def adapt(ekr: EducationalKnowledgeRepresentation) -> LearningContext:
        concepts_map: Dict[str, ConceptView] = {}
        for c in ekr.concepts:
            concepts_map[c.concept_id] = ConceptView(
                concept_id=c.concept_id,
                canonical_name=c.canonical_name,
                aliases=[a.text for a in c.aliases],
                type=c.type.value if hasattr(c.type, "value") else str(c.type),
                skill_ids=c.skill_ids,
                evidence_ids=c.evidence_ids,
            )

        skills_map: Dict[str, SkillView] = {}
        for s in ekr.skills:
            skills_map[s.skill_id] = SkillView(
                skill_id=s.skill_id,
                action=s.action.value if hasattr(s.action, "value") else str(s.action),
                statement=s.statement,
                concept_ids=s.concept_ids,
            )

        formulas_map = {f.formula_id: f for f in ekr.formulas}
        units_map = {u.unit_id: u for u in ekr.educational_units}
        items_map = {item.item_id: item for item in ekr.assessable_items}
        ev_map = {e.evidence_id: e for e in ekr.evidence}

        prereqs: List[PrerequisiteLink] = []
        trusted_rels: List[Relationship] = []

        trusted_rel_ids = set()
        if ekr.views and ekr.views.trusted:
            trusted_rel_ids = set(ekr.views.trusted.get("relationship_ids", []))

        for rel in ekr.relationships:
            if trusted_rel_ids and rel.relationship_id in trusted_rel_ids:
                trusted_rels.append(rel)
            rel_type = rel.type.value if hasattr(rel.type, "value") else str(rel.type)
            if rel_type == RelationshipTypeEnum.PREREQUISITE_OF.value:
                prereqs.append(
                    PrerequisiteLink(
                        source_concept_id=rel.source,
                        target_concept_id=rel.target,
                        confidence=rel.confidence.value if rel.confidence else 1.0,
                        evidence_ids=rel.evidence_ids,
                    )
                )

        # Build sections & topics from section statuses and educational units
        sections: List[Dict[str, Any]] = []
        topics: List[Dict[str, Any]] = []
        seen_sections = set()
        for sec in ekr.sections:
            seen_sections.add(sec.section_id)
            sections.append({"section_id": sec.section_id, "status": sec.semantic_status})

        # Infer chapters / topics if not explicitly structured
        topic_concepts: Dict[str, List[str]] = {}
        for unit in ekr.educational_units:
            sec_id = unit.section_id or "default_topic"
            if sec_id not in topic_concepts:
                topic_concepts[sec_id] = []
            for link in unit.concept_links:
                if link.concept_id not in topic_concepts[sec_id]:
                    topic_concepts[sec_id].append(link.concept_id)

        for top_id, c_ids in topic_concepts.items():
            topics.append({
                "topic_id": top_id,
                "title": top_id.replace("_", " ").title(),
                "concept_ids": c_ids,
            })

        chapters = [{"chapter_id": "ch_1", "title": "Main Chapter", "topic_ids": [t["topic_id"] for t in topics]}]

        return LearningContext(
            document_id=ekr.source_document_id,
            knowledge_document_id=ekr.knowledge_document_id,
            chapters=chapters,
            sections=sections,
            topics=topics,
            concepts=concepts_map,
            skills=skills_map,
            formulas=formulas_map,
            educational_units=units_map,
            assessable_items=items_map,
            evidence=ev_map,
            prerequisites=prereqs,
            trusted_relationships=trusted_rels,
        )
