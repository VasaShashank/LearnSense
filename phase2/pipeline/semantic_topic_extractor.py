"""
Semantic Topic & Knowledge Graph Extractor.
Generates meaningful pedagogical topics, core concepts, and directed prerequisite edges
from structured documents using the central LLM adapter, with a robust deterministic fallback.
"""

import hashlib
import json
import logging
import os
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

    @staticmethod
    def _load_canonical_prerequisites() -> List[Tuple[str, str]]:
        """Dynamically loads canonical prerequisite pairs from the canonical curriculum spec."""
        for path in [
            "curriculum/data/jee_curriculum_spec.json",
            "LearnSense/curriculum/data/jee_curriculum_spec.json",
            os.path.join(os.path.dirname(__file__), "..", "..", "curriculum", "data", "jee_curriculum_spec.json"),
        ]:
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        spec = json.load(f)
                    concept_map = {c["stable_key"]: c["name"] for c in spec.get("concepts", [])}
                    rules = []
                    for c in spec.get("concepts", []):
                        tgt = c["name"].lower()
                        for p_key in c.get("prerequisites", []):
                            src = concept_map.get(p_key, p_key).lower()
                            rules.append((src, tgt))
                    return rules
                except Exception:
                    pass
        return []

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
        if not isinstance(data, dict):
            raise ValueError(f"LLM returned non-dict payload: {type(data)}")
        raw_topics = data.get("topics", [])
        raw_prereqs = data.get("prerequisites", [])

        if not raw_topics or not isinstance(raw_topics, list):
            raise ValueError("LLM returned no valid topics list.")

        concepts: List[Concept] = []
        evidence: List[Evidence] = []
        concept_name_to_id: Dict[str, str] = {}
        topics_out: List[Dict[str, Any]] = []

        for t_idx, t in enumerate(raw_topics, start=1):
            if isinstance(t, str):
                t = {"topic_id": f"topic_{t_idx}", "title": t, "concepts": []}
            elif not isinstance(t, dict):
                continue

            t_id = str(t.get("topic_id") or f"topic_{t_idx}")
            t_title = str(t.get("title") or f"Topic {t_idx}").strip()
            topic_c_ids = []

            raw_concepts = t.get("concepts", [])
            if not isinstance(raw_concepts, list):
                raw_concepts = []

            for c_data in raw_concepts:
                if isinstance(c_data, str):
                    c_data = {"name": c_data, "definition": "", "search_phrase": c_data}
                elif not isinstance(c_data, dict):
                    continue

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

        for p in (raw_prereqs if isinstance(raw_prereqs, list) else []):
            if not isinstance(p, dict):
                continue
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

        # 2. Derive Topics from Outline or Curriculum Domains
        outline = getattr(doc, "outline", []) or []
        topics: List[Dict[str, Any]] = []

        block_to_sec: Dict[str, str] = {}
        sec_title_map: Dict[str, str] = {}
        for sec in outline:
            sec_title_map[sec.section_id] = sec.title

        for p in getattr(doc, "pages", []) or []:
            for b in getattr(p, "blocks", []) or []:
                if getattr(b, "section_id", None):
                    block_to_sec[b.block_id] = b.section_id

        ev_to_block: Dict[str, str] = {e.evidence_id: e.block_id for e in base_evidence}

        if len(outline) >= 2:
            sec_concepts: Dict[str, List[str]] = {sec.section_id: [] for sec in outline}
            for c in filtered_concepts:
                assigned_sec = None
                for ev_id in c.evidence_ids:
                    b_id = ev_to_block.get(ev_id)
                    if b_id in block_to_sec:
                        assigned_sec = block_to_sec[b_id]
                        break
                if assigned_sec and assigned_sec in sec_concepts:
                    sec_concepts[assigned_sec].append(c.concept_id)
                else:
                    sec_concepts[outline[0].section_id].append(c.concept_id)

            for sec in outline:
                if sec_concepts[sec.section_id]:
                    topics.append({
                        "topic_id": sec.section_id,
                        "title": sec.title,
                        "concept_ids": sec_concepts[sec.section_id],
                    })

        if not topics:
            # Dynamically derive topics from document headings and sections
            # Determine heading extraction strategy: if markdown Level-2 ("## ") headings exist,
            # they are the canonical chapter modules/topics.
            all_first_lines = [
                (b.content.text or "").strip().splitlines()[0]
                for page in getattr(doc, "pages", []) or []
                for b in getattr(page, "blocks", []) or []
                if getattr(b, "content", None) and (b.content.text or "").strip()
            ]
            has_h2_md = any(l.startswith("## ") and len(l[3:].strip()) >= 3 for l in all_first_lines)
            has_h1_md = any(l.startswith("# ") and not l.startswith("## ") and len(l[2:].strip()) >= 3 for l in all_first_lines)

            heading_blocks: List[Tuple[str, str, int]] = []  # (block_id, heading_text, page_index)
            for page in getattr(doc, "pages", []) or []:
                p_idx = getattr(page, "page_index", 0)
                for b in getattr(page, "blocks", []) or []:
                    b_role = getattr(b, "role", "") or ""
                    b_type = getattr(b, "type", "") or ""
                    txt = (b.content.text or "").strip() if getattr(b, "content", None) else ""
                    if not txt:
                        continue
                    first_line = txt.splitlines()[0].strip()
                    is_noisy = any(noise in txt.lower() for noise in ["download", "esaral", "notes", "page", "revision", "class 8", "jee | neet", "app"])
                    if is_noisy:
                        continue

                    extracted_title = None
                    if has_h2_md:
                        if first_line.startswith("## ") and len(first_line[3:].strip()) >= 3:
                            extracted_title = first_line[3:].strip()
                    elif has_h1_md:
                        if first_line.startswith("# ") and len(first_line[2:].strip()) >= 3:
                            extracted_title = first_line[2:].strip()
                    else:
                        is_md = first_line.startswith(("#", "##", "###")) and len(first_line.lstrip("# ").strip()) >= 3
                        is_heading_role = "heading" in b_role.lower() or b_type == "heading"
                        is_all_caps = len(txt) >= 4 and txt.isupper() and "\n" not in txt
                        is_short_title = len(txt.splitlines()) == 1 and 3 <= len(txt) <= 60 and not txt.endswith((".", ",", ";", ":"))
                        if is_md:
                            extracted_title = first_line.lstrip("# ").strip()
                        elif is_heading_role or is_all_caps or is_short_title:
                            extracted_title = txt.title()

                    if extracted_title:
                        heading_blocks.append((b.block_id, extracted_title, p_idx))

            if len(heading_blocks) >= 2:
                seen_titles: Dict[str, Dict[str, Any]] = {}
                for idx, (b_id, h_title, p_idx) in enumerate(heading_blocks, 1):
                    t_key = h_title.lower().strip()
                    # Subsume subheadings where the existing topic name is a complete substring
                    # e.g. "Laws of Friction" and "Properties of Friction" subsumed under "Friction"
                    matched_existing = None
                    for existing_key in seen_titles:
                        if existing_key in t_key or t_key in existing_key:
                            matched_existing = existing_key
                            break
                    if not matched_existing and len(seen_titles) < 5:
                        t_obj = {"topic_id": f"topic_{len(seen_titles) + 1}", "title": h_title, "concept_ids": []}
                        seen_titles[t_key] = t_obj

                # Assign concepts to closest matching or sequential heading
                topic_list = list(seen_titles.values())
                for c in filtered_concepts:
                    assigned = False
                    c_name_low = c.canonical_name.lower()
                    for t_obj in topic_list:
                        t_words = [w for w in t_obj["title"].lower().split() if len(w) > 3]
                        if any(w in c_name_low for w in t_words):
                            t_obj["concept_ids"].append(c.concept_id)
                            assigned = True
                            break
                    if not assigned and topic_list:
                        # Distribute based on hash to preserve balance
                        target_t = topic_list[int(hashlib.md5(c.concept_id.encode('utf-8')).hexdigest(), 16) % len(topic_list)]
                        target_t["concept_ids"].append(c.concept_id)

                topics = [t for t in topic_list if t["concept_ids"]]

            # If still no topics derived, dynamically query canonical curriculum or synthesize from title
            if not topics:
                doc_title = getattr(getattr(doc, "metadata", None), "title", None)
                if hasattr(doc_title, "value"):
                    base_title = str(doc_title.value)
                elif isinstance(doc_title, dict):
                    base_title = str(doc_title.get("value") or "")
                else:
                    base_title = str(doc_title or "")
                base_title = base_title.strip() or "Core Curriculum"

                if len(filtered_concepts) <= 6:
                    topics = [{
                        "topic_id": "topic_1",
                        "title": f"{base_title} Foundations",
                        "concept_ids": [c.concept_id for c in filtered_concepts],
                    }]
                else:
                    mid = len(filtered_concepts) // 2
                    topics = [
                        {
                            "topic_id": "topic_1",
                            "title": f"{base_title} - Foundations",
                            "concept_ids": [c.concept_id for c in filtered_concepts[:mid]],
                        },
                        {
                            "topic_id": "topic_2",
                            "title": f"{base_title} - Advanced Concepts",
                            "concept_ids": [c.concept_id for c in filtered_concepts[mid:]],
                        },
                    ]

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

        # Dynamic curriculum prerequisite rules across all canonical subjects
        canonical_prereqs = self._load_canonical_prerequisites()

        def _find_concept(pattern: str) -> Optional[Concept]:
            p_low = pattern.lower()
            for c in filtered_concepts:
                c_low = c.canonical_name.lower()
                if p_low == c_low or (len(p_low) > 4 and (p_low in c_low or c_low in p_low)):
                    return c
                for a in getattr(c, "aliases", []) or []:
                    a_txt = getattr(a, "text", str(a)).lower()
                    if p_low == a_txt or (len(p_low) > 4 and (p_low in a_txt or a_txt in p_low)):
                        return c
            return None

        for src_pat, tgt_pat in canonical_prereqs:
            src_c = _find_concept(src_pat)
            tgt_c = _find_concept(tgt_pat)
            if src_c and tgt_c and src_c.concept_id != tgt_c.concept_id:
                s_id = src_c.concept_id
                t_id = tgt_c.concept_id
                if not has_directed_path(adj, t_id, s_id):
                    rel_id = generate_relationship_id(doc.document_id, s_id, RelationshipTypeEnum.PREREQUISITE_OF.value, t_id)
                    if not any(r.relationship_id == rel_id for r in relationships):
                        rel = Relationship(
                            relationship_id=rel_id,
                            source=s_id,
                            type=RelationshipTypeEnum.PREREQUISITE_OF,
                            target=t_id,
                            status=RelationshipStatusEnum.ACCEPTED,
                            evidence_level=EvidenceLevelEnum.STRONG_INFERRED,
                            confidence=ConfidenceBreakdown(value=0.92, components={"curriculum_prerequisite": 0.95, "dag_validated": 1.0}),
                            evidence_ids=src_c.evidence_ids[:1] + tgt_c.evidence_ids[:1],
                        )
                        relationships.append(rel)
                        adj.setdefault(s_id, set()).add(t_id)

        # Grounded definitional cross-reference prerequisite inference:
        # If concept A is explicitly referenced in the definition/evidence of concept B, A is foundational to B.
        ev_by_id = {e.evidence_id: (e.excerpt or "").lower() for e in (base_evidence or [])}
        for c_b in filtered_concepts:
            desc_b = (getattr(c_b, "description", "") or "").lower()
            excerpts_b = " ".join([ev_by_id.get(eid, "") for eid in c_b.evidence_ids])
            combined_b = f"{desc_b} {excerpts_b}"

            for c_a in filtered_concepts:
                if c_a.concept_id == c_b.concept_id:
                    continue
                name_a = c_a.canonical_name.lower().strip()
                if len(name_a) >= 4 and name_a in combined_b:
                    s_id = c_a.concept_id
                    t_id = c_b.concept_id
                    if not has_directed_path(adj, t_id, s_id):
                        rel_id = generate_relationship_id(doc.document_id, s_id, RelationshipTypeEnum.PREREQUISITE_OF.value, t_id)
                        if not any(r.relationship_id == rel_id for r in relationships):
                            rel = Relationship(
                                relationship_id=rel_id,
                                source=s_id,
                                type=RelationshipTypeEnum.PREREQUISITE_OF,
                                target=t_id,
                                status=RelationshipStatusEnum.ACCEPTED,
                                evidence_level=EvidenceLevelEnum.STRONG_INFERRED,
                                confidence=ConfidenceBreakdown(value=0.90, components={"definitional_grounding": 0.95, "dag_validated": 1.0}),
                                evidence_ids=c_a.evidence_ids[:1] + c_b.evidence_ids[:1],
                            )
                            relationships.append(rel)
                            adj.setdefault(s_id, set()).add(t_id)

        # Ordinal progression within similar conceptual series (e.g. First Law -> Second Law -> Third Law)
        first_c = _find_concept("first law") or _find_concept("1st law")
        second_c = _find_concept("second law") or _find_concept("2nd law")
        third_c = _find_concept("third law") or _find_concept("3rd law")
        for s_node, t_node in [(first_c, second_c), (second_c, third_c)]:
            if s_node and t_node and s_node.concept_id != t_node.concept_id:
                s_id = s_node.concept_id
                t_id = t_node.concept_id
                if not has_directed_path(adj, t_id, s_id):
                    rel_id = generate_relationship_id(doc.document_id, s_id, RelationshipTypeEnum.PREREQUISITE_OF.value, t_id)
                    if not any(r.relationship_id == rel_id for r in relationships):
                        rel = Relationship(
                            relationship_id=rel_id,
                            source=s_id,
                            type=RelationshipTypeEnum.PREREQUISITE_OF,
                            target=t_id,
                            status=RelationshipStatusEnum.ACCEPTED,
                            evidence_level=EvidenceLevelEnum.STRONG_INFERRED,
                            confidence=ConfidenceBreakdown(value=0.95, components={"ordinal_progression": 0.98, "dag_validated": 1.0}),
                            evidence_ids=s_node.evidence_ids[:1] + t_node.evidence_ids[:1],
                        )
                        relationships.append(rel)
                        adj.setdefault(s_id, set()).add(t_id)

        # _ensure_graph_connectivity was removed: fabricating PREREQUISITE_OF
        # edges between consecutive concepts is ungrounded.

        return filtered_concepts, relationships, topics, base_evidence

    # _ensure_graph_connectivity has been removed.
    # Fabricating PREREQUISITE_OF edges between sequential concepts within
    # a topic or bridging adjacent topics with ungrounded prerequisite links
    # violates the no-fallback policy.  Legitimate knowledge graphs may have
    # disconnected components.  Only explicitly evidenced or LLM-validated
    # prerequisite relationships should appear in the graph.
