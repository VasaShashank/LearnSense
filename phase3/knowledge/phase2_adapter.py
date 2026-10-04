"""
Phase-2 → Phase-3 Knowledge Adapter and LearningContext.
Provides a clean abstraction over Phase 2 EducationalKnowledgeRepresentation (EKR)
and connects learner state to prerequisite graph analysis.
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
from phase3.learner.models import LearnerState


class ConceptView(BaseModel):
    concept_id: str
    canonical_name: str
    aliases: List[str] = Field(default_factory=list)
    type: str
    # Derived from the concept's real evidence excerpts in the uploaded document.
    # Never invented: empty when the source did not define the concept.
    description: str = ""
    skill_ids: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
    # Real document locations backing this concept, used for grounded citations.
    page_indices: List[int] = Field(default_factory=list)
    block_ids: List[str] = Field(default_factory=list)
    section_titles: List[str] = Field(default_factory=list)

    def citation(self) -> Dict[str, Any]:
        """Provenance payload derived entirely from the ingested document."""
        return {
            "concept_id": self.concept_id,
            "canonical_name": self.canonical_name,
            "pages": [p + 1 for p in self.page_indices],
            "block_ids": self.block_ids,
            "sections": self.section_titles,
            "evidence_ids": self.evidence_ids,
        }


class ConceptDefinitionView(BaseModel):
    """An ``AssessableItem`` that states a concept in the learner's own material."""

    item_id: str
    item_type: str
    concept_ids: List[str] = Field(default_factory=list)
    text: str = ""
    evidence_ids: List[str] = Field(default_factory=list)


class SkillView(BaseModel):
    skill_id: str
    action: str
    statement: str
    concept_ids: List[str] = Field(default_factory=list)


class PrerequisiteLink(BaseModel):
    source_concept_id: str  # Prerequisite concept
    target_concept_id: str  # Dependent concept
    confidence: float = 0.9
    evidence_ids: List[str] = Field(default_factory=list)


class LearningContext(BaseModel):
    document_id: str
    knowledge_document_id: str
    document_title: str = ""
    source_filename: str = ""
    chapters: List[Dict[str, Any]] = Field(default_factory=list)
    sections: List[Dict[str, Any]] = Field(default_factory=list)
    topics: List[Dict[str, Any]] = Field(default_factory=list)
    concepts: Dict[str, ConceptView] = Field(default_factory=dict)
    skills: Dict[str, SkillView] = Field(default_factory=dict)
    formulas: Dict[str, Formula] = Field(default_factory=dict)
    educational_units: Dict[str, EducationalUnit] = Field(default_factory=dict)
    assessable_items: Dict[str, AssessableItem] = Field(default_factory=dict)
    concept_definitions: List[ConceptDefinitionView] = Field(default_factory=list)
    evidence: Dict[str, Evidence] = Field(default_factory=dict)
    prerequisites: List[PrerequisiteLink] = Field(default_factory=list)
    trusted_relationships: List[Relationship] = Field(default_factory=list)

    def concept(self, concept_id: str) -> Optional[ConceptView]:
        return self.concepts.get(concept_id)

    def concepts_with_evidence(self) -> List[ConceptView]:
        """Only concepts that actually have source evidence behind them."""
        return [c for c in self.concepts.values() if c.evidence_ids]

    def get_upstream_weak_prerequisites(
        self,
        target_concept_id: str,
        learner_state: LearnerState,
        mastery_threshold: float = 0.5,
    ) -> List[Dict[str, Any]]:
        """
        Traces the prerequisite graph upwards to identify weak upstream concepts
        causing gaps in target_concept_id.
        """
        weak_gaps = []
        visited = set()

        def _trace(c_id: str):
            if c_id in visited:
                return
            visited.add(c_id)

            # Find prerequisites where target is c_id
            prereq_c_ids = [
                link.source_concept_id
                for link in self.prerequisites
                if link.target_concept_id == c_id
            ]

            for prereq_id in prereq_c_ids:
                c_state = learner_state.get_concept_state(prereq_id)
                mastery = c_state.mastery_probability
                if mastery < mastery_threshold:
                    c_view = self.concepts.get(prereq_id)
                    weak_gaps.append({
                        "prerequisite_concept_id": prereq_id,
                        "canonical_name": c_view.canonical_name if c_view else prereq_id,
                        "mastery_probability": mastery,
                        "target_concept_id": c_id,
                    })
                # Recurse upstream
                _trace(prereq_id)

        _trace(target_concept_id)
        return weak_gaps


class Phase2Adapter:
    """
    Adapter converting Phase 2 EKR to a Phase 3 ``LearningContext``.

    Pass the originating ``StructuredDocument`` as ``structured_document`` so concept
    descriptions, page numbers and section titles can be resolved against the real
    document. Without it the context still works but carries no page-level provenance
    and no human-readable section titles.
    """

    @staticmethod
    def adapt(
        ekr: EducationalKnowledgeRepresentation,
        structured_document: Any = None,
        semantic_topics: Optional[List[Dict[str, Any]]] = None,
    ) -> LearningContext:
        # block_id -> (page_index, section_title, block_text)
        block_index: Dict[str, tuple] = {}
        section_titles: Dict[str, str] = {}
        document_title = ""
        source_filename = ""
        page_count = 0

        if structured_document is not None:
            md = getattr(structured_document, "metadata", None)
            if md is not None and getattr(md, "title", None) is not None:
                document_title = getattr(md.title, "value", "") or ""
            source_filename = getattr(getattr(structured_document, "source", None), "filename", "") or ""
            page_count = getattr(md, "page_count", 0) or 0

            def _walk(nodes) -> None:
                for node in nodes or []:
                    section_titles[node.section_id] = node.title
                    _walk(getattr(node, "children", []) or [])

            _walk(getattr(structured_document, "outline", []) or [])

            for page in getattr(structured_document, "pages", []) or []:
                for block in getattr(page, "blocks", []) or []:
                    block_index[block.block_id] = (
                        page.page_index,
                        section_titles.get(block.section_id or "", None),
                        (block.content.text or "").strip(),
                    )

        ev_map: Dict[str, Evidence] = {e.evidence_id: e for e in ekr.evidence}

        def _provenance(evidence_ids) -> tuple:
            pages: List[int] = []
            block_ids: List[str] = []
            titles: List[str] = []
            excerpts: List[str] = []
            for ev_id in evidence_ids or []:
                ev = ev_map.get(ev_id)
                if ev is None:
                    continue
                block_ids.append(ev.block_id)
                excerpt = (ev.excerpt or "").strip()
                if excerpt:
                    excerpts.append(excerpt)
                located = block_index.get(ev.block_id)
                if located is None:
                    continue
                page_index, sec_title, _ = located
                if page_index not in pages:
                    pages.append(page_index)
                if sec_title and sec_title not in titles:
                    titles.append(sec_title)
            pages.sort()
            return pages, block_ids, titles, excerpts

        def _describe(excerpts: List[str], block_text: str) -> str:
            """Prefer a definitional sentence from the source; never fabricate one."""
            for excerpt in excerpts:
                for sentence in excerpt.replace("\n", " ").split(". "):
                    sentence = sentence.strip().rstrip(".")
                    low = sentence.lower()
                    if not sentence:
                        continue
                    if any(
                        low.startswith(prefix)
                        for prefix in (
                            "a ", "an ", "the ", "is ", "are ", "refers to",
                            "is defined", "is called", "means ", "consists of",
                        )
                    ) and len(sentence) > 25:
                        return sentence if len(sentence) <= 300 else sentence[:299] + "…"
            for text in (excerpts, [block_text]):
                for candidate in text:
                    candidate = (candidate or "").strip()
                    if len(candidate) > 40:
                        return candidate if len(candidate) <= 300 else candidate[:299] + "…"
            return ""

        concepts_map: Dict[str, ConceptView] = {}
        for c in ekr.concepts:
            pages, block_ids, titles, excerpts = _provenance(c.evidence_ids)
            block_text = next(
                (block_index[b][2] for b in block_ids if b in block_index), ""
            )
            concepts_map[c.concept_id] = ConceptView(
                concept_id=c.concept_id,
                canonical_name=c.canonical_name,
                aliases=[a.text for a in c.aliases],
                type=c.type.value if hasattr(c.type, "value") else str(c.type),
                description=getattr(c, "description", "") or _describe(excerpts, block_text),
                skill_ids=c.skill_ids,
                evidence_ids=c.evidence_ids,
                page_indices=pages,
                block_ids=block_ids,
                section_titles=titles,
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

        sections: List[Dict[str, Any]] = []
        seen_sections = set()
        for sec in ekr.sections:
            seen_sections.add(sec.section_id)
            sections.append({
                "section_id": sec.section_id,
                "status": sec.semantic_status.value if hasattr(sec.semantic_status, "value") else str(sec.semantic_status),
                "title": section_titles.get(sec.section_id, ""),
                "warnings": [w.model_dump() for w in (sec.warnings or [])],
            })

        if semantic_topics:
            topics: List[Dict[str, Any]] = [
                {
                    "topic_id": str(t.get("topic_id") or f"topic_{idx}"),
                    "title": str(t.get("title") or f"Topic {idx}"),
                    "concept_ids": [cid for cid in t.get("concept_ids", []) if cid in concepts_map],
                }
                for idx, t in enumerate(semantic_topics, start=1)
                if any(cid in concepts_map for cid in t.get("concept_ids", []))
            ]
        else:
            topic_concepts: Dict[str, List[str]] = {}
            for unit in ekr.educational_units:
                # A unit with no section is keyed by its own unit_id, not by a shared
                # "default_topic" bucket: collapsing every section-less unit into one
                # invented topic would show the learner a label that is in no document.
                sec_id = unit.section_id or f"unit_{unit.unit_id}"
                topic_concepts.setdefault(sec_id, [])
                for link in unit.concept_links:
                    if link.concept_id not in topic_concepts[sec_id]:
                        topic_concepts[sec_id].append(link.concept_id)

            topics = []
            for top_id, c_ids in topic_concepts.items():
                # Real section title when the document had one; otherwise derive a readable
                # label from the concepts it actually contains (never a generic constant).
                # Rank by evidence count so the label reflects the topic's core concept,
                # and cap the join so 20-concept buckets don't become paragraph labels.
                title = section_titles.get(top_id)
                if not title:
                    ranked = sorted(
                        [c for c in c_ids if c in concepts_map],
                        key=lambda c: -len(concepts_map[c].evidence_ids or []),
                    )
                    if not ranked:
                        title = top_id.replace("_", " ").title()
                    elif len(ranked) <= 3:
                        title = " & ".join(concepts_map[c].canonical_name for c in ranked)
                    else:
                        first = concepts_map[ranked[0]].canonical_name
                        title = f"{first} +{len(ranked) - 1} more"
                topics.append({"topic_id": top_id, "title": title, "concept_ids": c_ids})

        definitions: List[ConceptDefinitionView] = []
        for item in ekr.assessable_items:
            item_type = item.item_type.value if hasattr(item.item_type, "value") else str(item.item_type)
            if "definition" not in item_type.lower():
                continue
            pages, block_ids, titles, excerpts = _provenance(item.evidence_ids)
            text = excerpts[0] if excerpts else ""
            if not text:
                text = next((block_index[b][2] for b in block_ids if b in block_index), "")
            definitions.append(
                ConceptDefinitionView(
                    item_id=item.item_id,
                    item_type=item_type,
                    concept_ids=item.concept_ids,
                    text=text,
                    evidence_ids=item.evidence_ids,
                )
            )

        chapter_title = (
            section_titles.get(next(iter(section_titles))) if len(section_titles) == 1 else None
        ) or document_title or source_filename or "Document"

        chapters = [{
            "chapter_id": "ch_1",
            "title": chapter_title,
            "topic_ids": [t["topic_id"] for t in topics],
        }]

        return LearningContext(
            document_id=ekr.source_document_id,
            knowledge_document_id=ekr.knowledge_document_id,
            document_title=document_title,
            source_filename=source_filename,
            chapters=chapters,
            sections=sections,
            topics=topics,
            concepts=concepts_map,
            skills=skills_map,
            formulas=formulas_map,
            educational_units=units_map,
            assessable_items=items_map,
            concept_definitions=definitions,
            evidence=ev_map,
            prerequisites=prereqs,
            trusted_relationships=trusted_rels,
        )
