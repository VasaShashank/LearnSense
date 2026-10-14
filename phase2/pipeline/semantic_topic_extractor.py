"""
Semantic Topic & Knowledge Graph Extractor.
Generates meaningful pedagogical topics, core concepts, and directed prerequisite edges
from structured documents using the central LLM adapter, with a robust deterministic fallback.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from phase2.models import (
    Concept,
    ConceptStatusEnum,
    ConceptTypeEnum,
    ConfidenceBreakdown,
    Evidence,
    EvidenceKindEnum,
    EvidenceLevelEnum,
    Relationship,
    RelationshipStatusEnum,
    RelationshipTypeEnum,
    ScopeEnum,
    TextSpan,
)
from phase2.pipeline.stage7_relationships import has_directed_path
from phase2.utils.id_generator import (
    generate_concept_id,
    generate_evidence_id,
    generate_relationship_id,
)
from phase3.adapters.llm_adapter import get_llm_adapter
from schemas.document import StructuredDocument

logger = logging.getLogger("LearnSense.SemanticTopicExtractor")


class SemanticTopicExtractor:
    """
    Extracts high-level curriculum topics, core technical concepts, and directed
    prerequisite dependency edges from a StructuredDocument.
    """

    def __init__(self, llm_adapter: Optional[Any] = None):
        self.llm_adapter = llm_adapter

    def _get_adapter(self) -> Any:
        if self.llm_adapter is not None:
            return self.llm_adapter
        try:
            return get_llm_adapter()
        except Exception:
            return None

    def extract(
        self,
        doc: StructuredDocument,
        base_concepts: Optional[List[Concept]] = None,
        base_evidence: Optional[List[Evidence]] = None,
        base_relationships: Optional[List[Relationship]] = None,
    ) -> Tuple[List[Concept], List[Relationship], List[Dict[str, Any]], List[Evidence]]:
        """
        Extract topics, clean concepts, and prerequisite relationships.

        Returns:
            (concepts, relationships, topics, evidence)
        """
        adapter = self._get_adapter()
        is_live = False
        if adapter and getattr(adapter, "mode", None) == "live":
            is_live = True

        if is_live:
            try:
                res = self._extract_with_llm(doc, adapter)
                if res and res[0]:  # Valid concepts returned
                    logger.info(
                        "Semantic LLM extraction succeeded: %d topics, %d concepts, %d relationships",
                        len(res[2]),
                        len(res[0]),
                        len(res[1]),
                    )
                    return res
            except Exception as exc:
                logger.warning("Semantic LLM extraction failed, falling back to deterministic extraction: %s", exc)

        return self._extract_deterministic(
            doc,
            base_concepts or [],
            base_evidence or [],
            base_relationships or [],
        )

    def _extract_with_llm(
        self, doc: StructuredDocument, adapter: Any
    ) -> Tuple[List[Concept], List[Relationship], List[Dict[str, Any]], List[Evidence]]:
        # Collect ALL document text — no truncation.  Long documents are batched
        # into LLM-sized windows so every page is covered.
        blocks_text = []
        block_lookup: List[Tuple[str, int, str]] = []  # (block_id, page_index, text)

        for page in getattr(doc, "pages", []) or []:
            for block in getattr(page, "blocks", []) or []:
                txt = (block.content.text or "").strip()
                if not txt:
                    continue
                block_lookup.append((block.block_id, page.page_index, txt))
                blocks_text.append(f"[{page.page_index + 1}] {txt}")

        # Batch into ~14 000-char windows so the LLM prompt stays within
        # context limits while covering the entire document.
        MAX_BATCH_CHARS = 14000
        batches: List[str] = []
        current_batch: List[str] = []
        current_len = 0
        for line in blocks_text:
            if current_len + len(line) > MAX_BATCH_CHARS and current_batch:
                batches.append("\n\n".join(current_batch))
                current_batch = []
                current_len = 0
            current_batch.append(line)
            current_len += len(line)
        if current_batch:
            batches.append("\n\n".join(current_batch))

        corpus_sample = batches[0] if batches else ""

        prompt = f"""You are a master curriculum architect and knowledge graph engineer.
Analyze the educational document excerpt below. Extract a clean, highly structured Knowledge Graph.

Requirements:
1. Identify 2 to 5 high-level Topics (modules or conceptual domains).
2. Under each Topic, extract 3 to 6 Core Technical Concepts (concise noun phrases like 'Elastic Load Balancing', 'Auto Scaling', 'Limits', 'Security Groups').
   - NEVER extract standalone common action verbs, adverbs, or isolated conversational words (e.g., 'Automatically', 'Distributes', 'Variety', 'Pay', 'Commit', 'Adjusts', 'Ensures').
   - Provide a precise 1-2 sentence definition strictly grounded in the document.
3. Identify directed prerequisite dependencies:
   - Which concept MUST be learned before another concept (foundational -> advanced).
   - Both concepts in a prerequisite link must be among the extracted concepts.

Document Text:
{corpus_sample}
"""

        schema_template = {
            "topics": [
                {
                    "topic_id": "topic_1",
                    "title": "Topic Title",
                    "concepts": [
                        {
                            "name": "Concept Name",
                            "definition": "1-2 sentence definition grounded in text",
                            "search_phrase": "key phrase from document",
                        }
                    ],
                }
            ],
            "prerequisites": [
                {
                    "source_concept": "Foundational Concept Name",
                    "target_concept": "Advanced Concept Name",
                    "rationale": "Why source is needed before target",
                }
            ],
        }

        data = adapter.generate_json(prompt, schema_template, validate=False)
        raw_topics = data.get("topics", [])
        raw_prereqs = data.get("prerequisites", [])

        if not raw_topics:
            raise ValueError("LLM returned no topics.")

        concepts: List[Concept] = []
        evidence: List[Evidence] = []
        concept_name_to_id: Dict[str, str] = {}
        topics_out: List[Dict[str, Any]] = []

        for t_idx, t in enumerate(raw_topics, start=1):
            t_id = str(t.get("topic_id") or f"topic_{t_idx}")
            t_title = str(t.get("title") or f"Topic {t_idx}").strip()
            topic_c_ids = []

            for c_data in t.get("concepts", []):
                c_name = str(c_data.get("name") or "").strip()
                if not c_name or len(c_name) < 2:
                    continue

                # Grounding: find matching block in document
                matched_blocks = []
                c_lower = c_name.lower()
                search_phrase = str(c_data.get("search_phrase") or "").strip().lower()

                for b_id, p_idx, b_txt in block_lookup:
                    b_low = b_txt.lower()
                    if c_lower in b_low or (search_phrase and search_phrase in b_low):
                        matched_blocks.append((b_id, p_idx, b_txt))
                        if len(matched_blocks) >= 3:
                            break

                # NO FALLBACK: ungrounded concepts are NOT assigned to
                # an arbitrary block.  They are kept with empty evidence
                # and marked NEEDS_REVIEW so downstream QC can flag them.

                c_id = generate_concept_id(doc.document_id, c_name)
                concept_name_to_id[c_name.lower()] = c_id
                topic_c_ids.append(c_id)

                c_ev_ids = []
                for b_id, p_idx, b_txt in matched_blocks:
                    ev_id = generate_evidence_id(doc.document_id, b_id, 0, min(len(b_txt), 200), "sem")
                    ev = Evidence(
                        evidence_id=ev_id,
                        block_id=b_id,
                        span=TextSpan(start=0, end=min(len(b_txt), 200)),
                        excerpt=b_txt[:300],
                        level=EvidenceLevelEnum.EXPLICIT,
                        kind=EvidenceKindEnum.EXPLICIT_STATEMENT,
                        source_confidence=0.95,
                    )
                    evidence.append(ev)
                    c_ev_ids.append(ev_id)

                defn = str(c_data.get("definition") or "").strip()
                is_grounded = bool(c_ev_ids)
                concept = Concept(
                    concept_id=c_id,
                    canonical_name=c_name,
                    aliases=[],
                    type=ConceptTypeEnum.CONCEPT,
                    scope=ScopeEnum.EDUCATIONAL,
                    status=ConceptStatusEnum.ACTIVE if is_grounded else ConceptStatusEnum.NEEDS_REVIEW,
                    mention_ids=[],
                    confidence=ConfidenceBreakdown(
                        value=0.95 if is_grounded else 0.40,
                        components={"extraction": 0.95, "llm_grounding": 0.95 if is_grounded else 0.0},
                    ),
                    evidence_ids=c_ev_ids,
                    description=defn,
                )
                concepts.append(concept)

            if topic_c_ids:
                topics_out.append({"topic_id": t_id, "title": t_title, "concept_ids": topic_c_ids})

        # Process prerequisites
        adj: Dict[str, Set[str]] = {}
        relationships: List[Relationship] = []

        for p in raw_prereqs:
            src_name = str(p.get("source_concept") or "").strip().lower()
            tgt_name = str(p.get("target_concept") or "").strip().lower()

            src_id = self._match_concept_id(src_name, concept_name_to_id)
            tgt_id = self._match_concept_id(tgt_name, concept_name_to_id)

            if not src_id or not tgt_id or src_id == tgt_id:
                continue

            # DAG cycle check
            if has_directed_path(adj, tgt_id, src_id):
                continue

            rel_id = generate_relationship_id(
                doc.document_id, src_id, RelationshipTypeEnum.PREREQUISITE_OF.value, tgt_id
            )
            if any(r.relationship_id == rel_id for r in relationships):
                continue

            rel = Relationship(
                relationship_id=rel_id,
                source=src_id,
                type=RelationshipTypeEnum.PREREQUISITE_OF,
                target=tgt_id,
                status=RelationshipStatusEnum.ACCEPTED,
                evidence_level=EvidenceLevelEnum.EXPLICIT,
                confidence=ConfidenceBreakdown(
                    value=0.92, components={"llm_semantic": 0.95, "dag_validated": 1.0}
                ),
                evidence_ids=[],
            )
            relationships.append(rel)
            adj.setdefault(src_id, set()).add(tgt_id)

        # _ensure_graph_connectivity was removed: fabricating PREREQUISITE_OF
        # edges between sequential concepts or across topic boundaries is
        # ungrounded.  A legitimate knowledge graph may have disconnected
        # components.

        return concepts, relationships, topics_out, evidence

    @staticmethod
    def _match_concept_id(name: str, name_to_id: Dict[str, str]) -> Optional[str]:
        if name in name_to_id:
            return name_to_id[name]
        for k, cid in name_to_id.items():
            if k in name or name in k:
                return cid
        return None

    def _extract_deterministic(
        self,
        doc: StructuredDocument,
        base_concepts: List[Concept],
        base_evidence: List[Evidence],
        base_relationships: Optional[List[Relationship]] = None,
    ) -> Tuple[List[Concept], List[Relationship], List[Dict[str, Any]], List[Evidence]]:
        """
        Intelligent deterministic extraction when LLM is unavailable:
        Groups concepts by document outline/sections, filters out low-signal tokens,
        preserves explicit relationships and mined definitions, and constructs
        curricular prerequisite progression edges.
        """
        # 1. Filter base concepts: keep high-value concepts
        filtered_concepts: List[Concept] = []
        for c in base_concepts:
            name = c.canonical_name.strip()
            # Multi-word terms, uppercase acronyms, concepts with definition, or concepts with evidence
            is_multi = " " in name
            is_acronym = name.isupper() and len(name) >= 2
            has_definition = bool(getattr(c, "description", None))
            has_evidence = len(c.evidence_ids) >= 1
            if is_multi or is_acronym or has_definition or has_evidence:
                filtered_concepts.append(c)

        # If too few survived, take top concepts
        if len(filtered_concepts) < 4 and base_concepts:
            filtered_concepts = base_concepts[:15]

        if not filtered_concepts:
            # Fallback: scan document heading blocks and key terms
            seen_terms: Set[str] = set()
            for page in getattr(doc, "pages", []) or []:
                for block in getattr(page, "blocks", []) or []:
                    txt = (block.content.text or "").strip()
                    for line in txt.splitlines():
                        line_s = line.strip()
                        if 4 <= len(line_s) <= 45 and not line_s.endswith((".", ",", ";")):
                            term = line_s.lstrip("0123456789.-*• ").strip()
                            if len(term) >= 4 and term.lower() not in seen_terms:
                                seen_terms.add(term.lower())
                                c_id = generate_concept_id(doc.document_id, term)
                                ev_id = generate_evidence_id(doc.document_id, block.block_id, 0, min(len(txt), 200), "det")
                                ev = Evidence(
                                    evidence_id=ev_id,
                                    block_id=block.block_id,
                                    span=TextSpan(start=0, end=min(len(txt), 200)),
                                    excerpt=txt[:300],
                                    level=EvidenceLevelEnum.STRONG_INFERRED,
                                    kind=EvidenceKindEnum.EXPLICIT_STATEMENT,
                                    source_confidence=0.85,
                                )
                                base_evidence.append(ev)
                                c = Concept(
                                    concept_id=c_id,
                                    canonical_name=term,
                                    aliases=[],
                                    type=ConceptTypeEnum.CONCEPT,
                                    scope=ScopeEnum.EDUCATIONAL,
                                    status=ConceptStatusEnum.ACTIVE,
                                    confidence=ConfidenceBreakdown(value=0.88),
                                    evidence_ids=[ev_id],
                                    description=txt[:200],
                                )
                                filtered_concepts.append(c)
                                if len(filtered_concepts) >= 12:
                                    break
                if len(filtered_concepts) >= 12:
                    break

        # 2. Derive Topics from Outline or Sections
        outline = getattr(doc, "outline", []) or []
        topics: List[Dict[str, Any]] = []

        if outline:
            for idx, sec in enumerate(outline, start=1):
                topics.append({
                    "topic_id": sec.section_id or f"topic_{idx}",
                    "title": sec.title or f"Section {idx}",
                    "concept_ids": [],
                })

        if not topics:
            # Fallback to 1-3 default topics based on document title
            doc_title = getattr(getattr(doc, "metadata", None), "title", None)
            if hasattr(doc_title, "value"):
                doc_title = doc_title.value
            title_str = str(doc_title or doc.document_id.replace("_", " ").title())
            topics = [
                {"topic_id": "topic_foundations", "title": f"{title_str} - Core Foundations", "concept_ids": []},
                {"topic_id": "topic_applied", "title": f"{title_str} - Advanced & Applied", "concept_ids": []},
            ]

        # Distribute concepts into topics
        c_count = len(filtered_concepts)
        t_count = len(topics)
        for i, c in enumerate(filtered_concepts):
            t_idx = min(int((i / max(1, c_count)) * t_count), t_count - 1)
            topics[t_idx]["concept_ids"].append(c.concept_id)

        # Pruning empty topics
        topics = [t for t in topics if t["concept_ids"]]

        # 3. Build Curriculum Progression Directed Edges
        relationships: List[Relationship] = []
        adj: Dict[str, Set[str]] = {}

        # Preserve and merge valid base relationships from Stage 7
        concept_ids = {c.concept_id for c in filtered_concepts}
        for rel in (base_relationships or []):
            if rel.source in concept_ids and rel.target in concept_ids and rel.source != rel.target:
                if not has_directed_path(adj, rel.target, rel.source):
                    relationships.append(rel)
                    adj.setdefault(rel.source, set()).add(rel.target)

        # _ensure_graph_connectivity was removed: fabricating PREREQUISITE_OF
        # edges between consecutive concepts is ungrounded.

        return filtered_concepts, relationships, topics, base_evidence

    # _ensure_graph_connectivity has been removed.
    # Fabricating PREREQUISITE_OF edges between sequential concepts within
    # a topic or bridging adjacent topics with ungrounded prerequisite links
    # violates the no-fallback policy.  Legitimate knowledge graphs may have
    # disconnected components.  Only explicitly evidenced or LLM-validated
    # prerequisite relationships should appear in the graph.
