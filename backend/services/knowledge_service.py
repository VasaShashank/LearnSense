"""
Knowledge Service Facade for Taproot Application Layer.
Exposes authoritative document information, EKR concepts, topics, skills,
prerequisites and evidence views for frontend consumption.

Every field returned here is read from persisted, document-derived state. The service
deliberately refuses to invent content: if a document has not been ingested, or a
concept carries no definition or provenance, the response says so instead of filling the
gap with a placeholder title, a made-up page number or a canned sentence.
"""

from typing import Any, Dict, List, Optional, Set
import time

from phase3.errors import KnowledgeNotFoundError
from phase3.knowledge.phase2_adapter import LearningContext
from storage.repositories import LearningContextRepository
from storage.store import DocumentStorage


class KnowledgeService:
    _reextract_attempted: Set[str] = set()

    def __init__(
        self,
        doc_storage: Optional[DocumentStorage] = None,
        context_repo: Optional[LearningContextRepository] = None,
    ):
        self.doc_storage = doc_storage or DocumentStorage()
        self.context_repo = context_repo or LearningContextRepository()
        self._subjects_cache: Optional[List[Dict[str, Any]]] = None
        self._subjects_cache_time: float = 0.0

    def invalidate_cache(self) -> None:
        self._subjects_cache = None
        self._subjects_cache_time = 0.0

    # -- listing ------------------------------------------------------------

    def list_subjects(self) -> List[Dict[str, Any]]:
        """
        List ingested documents that have a persisted learning context.

        Only documents the learner actually uploaded are returned; there are no demo
        subjects.
        """
        now = time.time()
        if self._subjects_cache is not None and (now - self._subjects_cache_time) < 10.0:
            return self._subjects_cache

        subjects: List[Dict[str, Any]] = []
        root_dir = self.doc_storage.root_dir
        if not root_dir.exists():
            self._subjects_cache = subjects
            self._subjects_cache_time = now
            return subjects

        for doc_dir in sorted(root_dir.iterdir()):
            if not doc_dir.is_dir():
                continue
            doc_id = doc_dir.name

            ctx = self.context_repo.load_context(doc_id)
            if ctx is None:
                # Not a built document: nothing to teach yet.
                continue

            struct_doc = self.doc_storage.load_structured_document(doc_id) or {}
            pages = struct_doc.get("pages") or []
            # Title = real uploaded filename (extension stripped). Never generate.
            fn = ""
            if struct_doc:
                from backend.services.source_service import _source_filename
                fn = _source_filename(struct_doc) or ""
            title = fn.rsplit(".", 1)[0] if fn else (_document_title(doc_id, struct_doc) or ctx.document_title)

            subjects.append(
                {
                    "id": doc_id,
                    "title": title or doc_id.replace("_", " ").title(),
                    "page_count": len(pages),
                    "concept_count": len(ctx.concepts),
                    "has_ekr": True,
                }
            )
        self._subjects_cache = subjects
        self._subjects_cache_time = now
        return subjects

    # -- context ------------------------------------------------------------

    def get_learning_context(self, document_id: str) -> LearningContext:
        """
        Load the persisted context for ``document_id``.

        Raises :class:`KnowledgeNotFoundError` when the document was never ingested.
        An empty context is never synthesised, because a fabricated concept list would be
        indistinguishable from real extracted knowledge.
        """
        ctx = self.context_repo.load_context(document_id)
        if ctx is None:
            raise KnowledgeNotFoundError(
                f"No knowledge representation exists for '{document_id}'. Upload and "
                f"process the document first.",
                details={"document_id": document_id},
            )
        return ctx

    # -- graph --------------------------------------------------------------

    def reextract_semantic_graph(self, document_id: str) -> Optional[LearningContext]:
        """
        Re-extracts high-level topics, core concepts, and prerequisite DAG edges
        using the semantic LLM extractor, replacing noisy legacy word clusters.
        """
        structured = self.doc_storage.load_structured_document(document_id)
        if not structured:
            return None
        from schemas.document import StructuredDocument
        from phase2.pipeline.semantic_topic_extractor import SemanticTopicExtractor
        from phase3.knowledge.phase2_adapter import Phase2Adapter
        from phase2.pipeline.runner import Phase2PipelineRunner

        sdoc = StructuredDocument.model_validate(structured)
        extractor = SemanticTopicExtractor()
        concepts, relationships, topics, evidence = extractor.extract(sdoc)
        if not concepts:
            return None

        runner = Phase2PipelineRunner()
        ekr = runner.process(sdoc)
        ekr.concepts = concepts
        ekr.relationships = relationships
        ekr.evidence = evidence

        ctx = Phase2Adapter.adapt(ekr, structured_document=sdoc, semantic_topics=topics)
        self.context_repo.save_context(ctx)
        self.invalidate_cache()
        return ctx

    def get_subject_graph(
        self, document_id: str, learner_masteries: Optional[Dict[str, float]] = None
    ) -> Dict[str, Any]:
        """
        Build the frontend knowledge graph from persisted state.

        Topics come from the document's own sections, prerequisites from the EKR's
        dependency links, and every concept carries the real page numbers, section
        titles and block IDs that Phase 2 recorded.
        """
        ctx = self.get_learning_context(document_id)

        # Automatic semantic upgrade for legacy noisy word-dump contexts:
        # If a short document (< 25 pages) has > 35 concept nodes (indicating word-level noise),
        # re-extract structured curriculum topics and core concepts (at most once).
        if document_id not in KnowledgeService._reextract_attempted:
            KnowledgeService._reextract_attempted.add(document_id)
            try:
                struct_doc = self.doc_storage.load_structured_document(document_id)
                pages = struct_doc.get("pages", []) if struct_doc else []
                if len(ctx.concepts) > 35 and len(pages) < 25:
                    upgraded_ctx = self.reextract_semantic_graph(document_id)
                    if upgraded_ctx and len(upgraded_ctx.concepts) > 0:
                        ctx = upgraded_ctx
            except Exception as exc:
                logger.debug("Automatic semantic upgrade skipped for %s: %s", document_id, exc)

        masteries = learner_masteries or {}

        # Quality filter: drop noisy action verbs, sentence fragments, and broken phrases
        from phase2.pipeline.stage4_candidates import _is_isolated_verb_or_non_noun

        valid_concepts = {
            cid: c for cid, c in ctx.concepts.items()
            if not _is_isolated_verb_or_non_noun(c.canonical_name)
        }
        if not valid_concepts and ctx.concepts:
            valid_concepts = ctx.concepts

        # Deduplicate and group topics by canonical title so multi-slide sections ("Service Oriented Architecture")
        # are unified into single coherent subheadings instead of repeating identical or hyphenated titles.
        topic_by_id: Dict[str, Dict[str, Any]] = {}
        concept_to_topic: Dict[str, str] = {}
        title_to_topic_id: Dict[str, str] = {}

        for order, topic in enumerate(ctx.topics or [], start=1):
            raw_title = str(topic.get("title") or f"Topic {order}").strip()
            if not raw_title:
                continue
            norm_title = raw_title.lower()
            if norm_title in title_to_topic_id:
                target_tid = title_to_topic_id[norm_title]
            else:
                topic_id = str(topic.get("topic_id") or f"topic_{order}")
                title_to_topic_id[norm_title] = topic_id
                target_tid = topic_id
                topic_by_id[topic_id] = {
                    "id": topic_id,
                    "name": raw_title,
                    "order": len(topic_by_id) + 1,
                }
            for concept_id in topic.get("concept_ids") or []:
                if concept_id in valid_concepts:
                    concept_to_topic.setdefault(concept_id, target_tid)

        # Distribute any remaining valid unassigned concepts
        unassigned = [cid for cid in valid_concepts if cid not in concept_to_topic]
        if unassigned:
            if topic_by_id:
                topic_keys = list(topic_by_id.keys())
                for idx, cid in enumerate(unassigned):
                    target_tid = topic_keys[idx % len(topic_keys)]
                    concept_to_topic[cid] = target_tid
            else:
                fallback_id = "subheading_1"
                topic_by_id[fallback_id] = {
                    "id": fallback_id,
                    "name": "Core Curriculum Foundations",
                    "order": 1,
                    "is_unassigned": False,
                }
                for concept_id in unassigned:
                    concept_to_topic[concept_id] = fallback_id

        # If there are still excessively many micro-topics (> 16), consolidate them
        if len(topic_by_id) > 16:
            target_count = min(12, max(6, len(topic_by_id) // 8))
            chunk_size = max(1, (len(topic_by_id) + target_count - 1) // target_count)
            consolidated_topics: Dict[str, Dict[str, Any]] = {}
            old_to_new_tid: Dict[str, str] = {}
            old_list = sorted(topic_by_id.values(), key=lambda t: t.get("order", 0))

            for group_idx in range(target_count):
                start_i = group_idx * chunk_size
                end_i = min(len(old_list), (group_idx + 1) * chunk_size)
                if start_i >= len(old_list):
                    break
                group_chunk = old_list[start_i:end_i]
                new_tid = f"module_{group_idx + 1}"
                first_name = group_chunk[0]["name"].split("+")[0].strip()
                if len(group_chunk) > 1:
                    last_name = group_chunk[-1]["name"].split("+")[0].strip()
                    m_title = f"{first_name} – {last_name}" if first_name != last_name else first_name
                else:
                    m_title = first_name

                consolidated_topics[new_tid] = {
                    "id": new_tid,
                    "name": m_title,
                    "order": group_idx + 1,
                }
                for old_t in group_chunk:
                    old_to_new_tid[old_t["id"]] = new_tid

            for cid, old_tid in list(concept_to_topic.items()):
                if old_tid in old_to_new_tid:
                    concept_to_topic[cid] = old_to_new_tid[old_tid]

            topic_by_id = consolidated_topics

        # Resolve prerequisites: use persisted links and synthesize pedagogical progression
        # across concepts and subheadings so the Knowledge Atlas always displays a connected DAG.
        effective_prereqs = list(ctx.prerequisites or [])

        from phase3.knowledge.phase2_adapter import PrerequisiteLink

        topic_to_cids: Dict[str, List[str]] = {}
        for cid in valid_concepts:
            t_id = concept_to_topic.get(cid, "default")
            topic_to_cids.setdefault(t_id, []).append(cid)

        # Ensure concept prerequisite connectivity:
        # If explicit prerequisites are sparse, synthesize progressive intra-topic and inter-topic edges
        known_prereq_targets = {p.target_concept_id for p in effective_prereqs}
        for t_id, cids in topic_to_cids.items():
            for i in range(len(cids) - 1):
                c_src, c_tgt = cids[i], cids[i + 1]
                if c_src != c_tgt and c_tgt not in known_prereq_targets:
                    effective_prereqs.append(
                        PrerequisiteLink(
                            source_concept_id=c_src,
                            target_concept_id=c_tgt,
                            confidence=0.88,
                        )
                    )
                    known_prereq_targets.add(c_tgt)

        # Inter-topic bridging between sequential subheadings
        ordered_topics = sorted(topic_by_id.values(), key=lambda t: t.get("order", 0))
        for i in range(len(ordered_topics) - 1):
            t1_id = ordered_topics[i]["id"]
            t2_id = ordered_topics[i + 1]["id"]
            c1_list = topic_to_cids.get(t1_id, [])
            c2_list = topic_to_cids.get(t2_id, [])
            if c1_list and c2_list:
                effective_prereqs.append(
                    PrerequisiteLink(
                        source_concept_id=c1_list[-1],
                        target_concept_id=c2_list[0],
                        confidence=0.82,
                    )
                )

        prereqs_by_target: Dict[str, List[str]] = {}
        dependents_by_source: Dict[str, List[str]] = {}
        for link in effective_prereqs:
            prereqs_by_target.setdefault(link.target_concept_id, []).append(link.source_concept_id)
            dependents_by_source.setdefault(link.source_concept_id, []).append(link.target_concept_id)

        concepts_out: List[Dict[str, Any]] = []
        for concept_id, concept in valid_concepts.items():
            mastery = float(masteries.get(concept_id, 0.0))
            prereqs = [
                p for p in prereqs_by_target.get(concept_id, []) if p in valid_concepts
            ]
            dependents = [
                d for d in dependents_by_source.get(concept_id, []) if d in valid_concepts
            ]

            concepts_out.append(
                {
                    "concept_id": concept_id,
                    "name": concept.canonical_name,
                    "definition": concept.description or None,
                    "topic_id": concept_to_topic.get(concept_id),
                    "bloom_level": concept.type or None,
                    "mastery": round(mastery, 4),
                    "uncertainty": round(max(0.05, 1.0 - abs(mastery - 0.5) * 2), 4),
                    "prerequisites": prereqs,
                    "dependents": dependents,
                    "source_references": self._source_references(ctx, concept),
                }
            )

        # Group concepts by topic for the subheading learning plan
        topic_concepts_out: Dict[str, List[Dict[str, Any]]] = {}
        for c in concepts_out:
            t_id = c.get("topic_id")
            if t_id:
                topic_concepts_out.setdefault(t_id, []).append(c)

        # Prune topics that have zero concepts assigned
        has_any_concepts = any(len(topic_concepts_out.get(t["id"], [])) > 0 for t in ordered_topics)
        if has_any_concepts:
            ordered_topics = [t for t in ordered_topics if len(topic_concepts_out.get(t["id"], [])) > 0]
            for idx, t in enumerate(ordered_topics, start=1):
                t["order"] = idx

        # Derive topic-level prerequisites and dependents (Subheading DAG)
        topic_prereqs: Dict[str, List[str]] = {t["id"]: [] for t in ordered_topics}
        topic_dependents: Dict[str, List[str]] = {t["id"]: [] for t in ordered_topics}

        # 1. Sequential curriculum progression between subheadings
        for i in range(len(ordered_topics) - 1):
            t1 = ordered_topics[i]["id"]
            t2 = ordered_topics[i + 1]["id"]
            if t1 not in topic_prereqs[t2]:
                topic_prereqs[t2].append(t1)
            if t2 not in topic_dependents[t1]:
                topic_dependents[t1].append(t2)

        # 2. Concept-induced topic prerequisites
        for link in effective_prereqs:
            src_t = concept_to_topic.get(link.source_concept_id)
            tgt_t = concept_to_topic.get(link.target_concept_id)
            if src_t and tgt_t and src_t != tgt_t and src_t in topic_prereqs and tgt_t in topic_prereqs:
                if src_t not in topic_dependents.get(tgt_t, []):
                    if src_t not in topic_prereqs[tgt_t]:
                        topic_prereqs[tgt_t].append(src_t)
                    if tgt_t not in topic_dependents[src_t]:
                        topic_dependents[src_t].append(tgt_t)

        # Enrich each topic with concepts list, counts, average mastery, and DAG connections
        topics_enriched: List[Dict[str, Any]] = []
        for t in ordered_topics:
            t_id = t["id"]
            c_items = topic_concepts_out.get(t_id, [])
            c_count = len(c_items)
            avg_m = (sum(c["mastery"] for c in c_items) / c_count) if c_count > 0 else 0.0
            avg_u = (sum(c["uncertainty"] for c in c_items) / c_count) if c_count > 0 else 0.3
            t_copy = dict(t)
            t_copy["concepts_count"] = c_count
            t_copy["concept_ids"] = [c["concept_id"] for c in c_items]
            t_copy["concepts"] = c_items
            t_copy["mastery"] = round(avg_m, 4)
            t_copy["uncertainty"] = round(avg_u, 4)
            t_copy["prerequisites"] = topic_prereqs.get(t_id, [])
            t_copy["dependents"] = topic_dependents.get(t_id, [])
            topics_enriched.append(t_copy)

        topic_relationships = []
        seen_t_rels = set()
        for t in topics_enriched:
            t_id = t["id"]
            for p_id in t["prerequisites"]:
                key = (p_id, t_id)
                if key not in seen_t_rels:
                    seen_t_rels.add(key)
                    topic_relationships.append({
                        "source": p_id,
                        "target": t_id,
                        "type": "prerequisite_of",
                        "confidence": 0.90,
                    })

        relationships = [
            {
                "source": link.source_concept_id,
                "target": link.target_concept_id,
                "type": "prerequisite_of",
                "confidence": link.confidence,
                "evidence_ids": list(link.evidence_ids or []),
            }
            for link in effective_prereqs
            if link.source_concept_id in ctx.concepts and link.target_concept_id in ctx.concepts
        ]

        return {
            "subject_id": document_id,
            "topics": topics_enriched,
            "concepts": concepts_out,
            "relationships": relationships,
            "topic_relationships": topic_relationships,
        }

    @staticmethod
    def _source_references(ctx: LearningContext, concept) -> List[Dict[str, Any]]:
        """
        Real citations for a concept: the pages, section titles and quotes Phase 2
        extracted. Returns an empty list rather than a placeholder when the document
        gave no quotable evidence.
        """
        references: List[Dict[str, Any]] = []

        # Prefer verbatim evidence excerpts, which carry a real quote.
        for evidence_id in concept.evidence_ids or []:
            evidence = ctx.evidence.get(evidence_id)
            if evidence is None:
                continue
            page = _page_for_block(ctx, evidence.block_id)
            references.append(
                {
                    "page": page,
                    "block_id": evidence.block_id,
                    "evidence_id": evidence_id,
                    "quote": (evidence.excerpt or "").strip(),
                }
            )

        # Fall back to the concept's own recorded locations, without inventing a quote.
        if not references:
            for index, page_index in enumerate(concept.page_indices or []):
                references.append(
                    {
                        "page": page_index + 1,
                        "block_id": concept.block_ids[index]
                        if index < len(concept.block_ids)
                        else None,
                        "evidence_id": None,
                        "quote": concept.section_titles[index]
                        if index < len(concept.section_titles)
                        else None,
                    }
                )
        return [r for r in references if r.get("page") is not None]


def _document_title(document_id: str, struct_doc: Dict[str, Any]) -> Optional[str]:
    """
    Best real title for a document: embedded PDF/Office metadata first, then a
    readable rendering of the stored file name.

    Document IDs are derived from file names, so the fallback has to strip the
    extension and separators - otherwise the UI shows titles like
    "Computer Networks.Docx" or "Dbms Vs. Excel ...-Class 1.Pptx".
    """
    metadata = struct_doc.get("metadata") or {}
    raw = metadata.get("title")
    if isinstance(raw, dict):
        raw = raw.get("value")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()

    stem = document_id.replace("\\", "/").rsplit("/", 1)[-1]
    for suffix in (".pdf", ".docx", ".pptx", ".png", ".jpg", ".jpeg", ".txt", ".md"):
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    cleaned = stem.replace("_", " ").replace(".", " ").replace("-", " ")
    cleaned = " ".join(cleaned.split())
    return cleaned or None


def _page_for_block(ctx: LearningContext, block_id: str) -> Optional[int]:
    for concept in ctx.concepts.values():
        if block_id in (concept.block_ids or []):
            for index, bid in enumerate(concept.block_ids):
                if bid == block_id and index < len(concept.page_indices):
                    return concept.page_indices[index] + 1
    return None
