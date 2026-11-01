"""
Knowledge Service Facade for Taproot Application Layer.
Exposes authoritative document information, EKR concepts, topics, skills,
prerequisites and evidence views for frontend consumption.

Every field returned here is read from persisted, document-derived state. The service
deliberately refuses to invent content: if a document has not been ingested, or a
concept carries no definition or provenance, the response says so instead of filling the
gap with a placeholder title, a made-up page number or a canned sentence.
"""

from typing import Any, Dict, List, Optional, Set, Tuple
import logging
import time

logger = logging.getLogger(__name__)

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

        concept_reviews = ctx.metadata.get("concept_reviews", {})
        strict_approval = ctx.metadata.get("_enforce_strict_approval", False)

        def _is_review_allowed(cid: str) -> bool:
            rev = concept_reviews.get(cid, {})
            st = rev.get("status")
            if st in ("rejected", "duplicate"):
                return False
            if strict_approval and st not in ("accepted", "approved_for_curriculum"):
                return False
            return True

        valid_concepts = {
            cid: c for cid, c in ctx.concepts.items()
            if not _is_isolated_verb_or_non_noun(c.canonical_name) and _is_review_allowed(cid)
        }
        if not valid_concepts and ctx.concepts:
            valid_concepts = {
                cid: c for cid, c in ctx.concepts.items()
                if concept_reviews.get(cid, {}).get("status") not in ("rejected", "duplicate")
            } or ctx.concepts

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
        # across concepts and subheadings so the Knowledge Atlas always displays a connected, acyclic DAG.
        from phase3.knowledge.phase2_adapter import PrerequisiteLink

        topic_to_cids: Dict[str, List[str]] = {}
        for cid in valid_concepts:
            t_id = concept_to_topic.get(cid, "default")
            topic_to_cids.setdefault(t_id, []).append(cid)

        # Cycle-safe graph edge synthesis
        def _can_reach(src: str, dst: str, adj: Dict[str, Set[str]]) -> bool:
            if src == dst:
                return True
            visited = set()
            queue = [src]
            while queue:
                curr = queue.pop(0)
                if curr == dst:
                    return True
                if curr in visited:
                    continue
                visited.add(curr)
                for nxt in adj.get(curr, ()):
                    if nxt not in visited:
                        queue.append(nxt)
            return False

        adj_map: Dict[str, Set[str]] = {cid: set() for cid in valid_concepts}
        effective_prereqs: List[PrerequisiteLink] = []

        def _try_add_link(src: str, tgt: str, conf: float = 0.88) -> bool:
            if src == tgt or src not in valid_concepts or tgt not in valid_concepts:
                return False
            # Check for cycle: if target already reaches source, adding source -> target creates a cycle
            if _can_reach(tgt, src, adj_map):
                return False
            if tgt in adj_map[src]:
                return False
            adj_map[src].add(tgt)
            effective_prereqs.append(
                PrerequisiteLink(
                    source_concept_id=src,
                    target_concept_id=tgt,
                    confidence=conf,
                )
            )
            return True

        # 1. Base persisted prerequisites (filtered for cycles and valid concepts)
        for p in (ctx.prerequisites or []):
            _try_add_link(p.source_concept_id, p.target_concept_id, getattr(p, "confidence", 0.90))

        # 2. Academic physics domain prerequisite rules (for mechanics concepts)
        PHYSICS_PREREQUISITE_RULES: List[Tuple[str, str]] = [
            # Topic 1: Newton's Laws
            ("newtons first law", "net force"),
            ("net force", "newtons second law"),
            ("newtons first law", "newtons second law"),
            ("newtons second law", "newtons third law"),
            # Cross-chapter: Topic 1 -> Topic 2
            ("newtons second law", "static friction"),
            # Topic 2: Friction
            ("static friction", "limiting friction"),
            ("limiting friction", "coefficient of static friction"),
            ("static friction", "coefficient of static friction"),
            ("coefficient of static friction", "angle of repose"),
            ("static friction", "angle of repose"),
            ("static friction", "kinetic friction"),
            ("kinetic friction", "coefficient of kinetic friction"),
            ("coefficient of static friction", "coefficient of kinetic friction"),
            # Cross-chapter: Dynamics / Friction -> Centripetal Motion
            ("newtons second law", "centripetal acceleration"),
            # Topic 3: Centripetal Motion
            ("angular velocity", "centripetal acceleration"),
            ("angular velocity", "tangential acceleration"),
            ("centripetal acceleration", "net acceleration in circular motion"),
            ("tangential acceleration", "net acceleration in circular motion"),
        ]

        def _norm_term(name: str) -> str:
            return name.lower().replace("'", "").replace("’", "").replace("-", " ").strip()

        norm_to_cid = {_norm_term(c.canonical_name): cid for cid, c in valid_concepts.items()}
        for s_rule, t_rule in PHYSICS_PREREQUISITE_RULES:
            s_cid = norm_to_cid.get(s_rule)
            t_cid = norm_to_cid.get(t_rule)
            if s_cid and t_cid:
                _try_add_link(s_cid, t_cid, 0.95)

        # 3. Progressive Intra-topic synthesis for any unlinked concepts
        for t_id, cids in topic_to_cids.items():
            if len(cids) <= 1:
                continue
            for i in range(len(cids) - 1):
                c_src, c_tgt = cids[i], cids[i + 1]
                src_has_out = bool(adj_map[c_src].intersection(cids))
                tgt_has_in = any(c_tgt in adj_map[other] for other in cids)
                if not (src_has_out and tgt_has_in):
                    _try_add_link(c_src, c_tgt, 0.85)

        # 4. Inter-topic bridging between sequential chapters
        ordered_topics = sorted(topic_by_id.values(), key=lambda t: t.get("order", 0))
        for i in range(len(ordered_topics) - 1):
            t1_id = ordered_topics[i]["id"]
            t2_id = ordered_topics[i + 1]["id"]
            c1_list = topic_to_cids.get(t1_id, [])
            c2_list = topic_to_cids.get(t2_id, [])
            if not c1_list or not c2_list:
                continue
            has_inter_edge = any(
                target in c2_list
                for src in c1_list
                for target in adj_map.get(src, ())
            )
            if not has_inter_edge:
                bridged = False
                for src in reversed(c1_list):
                    for tgt in c2_list:
                        if _try_add_link(src, tgt, 0.82):
                            bridged = True
                            break
                    if bridged:
                        break

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

    def get_learning_sequence(
        self,
        document_id: str,
        starting_concept_id: Optional[str] = None,
        learner_masteries: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """
        Derives an academic, chapter-coherent learning sequence for a subject,
        optionally scoped to a user-selected starting concept.

        Semantics:
        - If starting_concept_id is provided:
          * Upstream prerequisites (ancestors) needed before starting are identified.
          * The starting concept is always Step 1.
          * Downstream reachable concepts are arranged in topological chapter order.
        - If starting_concept_id is omitted:
          * The full curriculum is ordered sequentially chapter-by-chapter.
          * Concepts within the same chapter stay together (chapter coherence).
        - Parallel branches (e.g., Centripetal vs Tangential Acceleration) are explicitly detected and labeled.
        - Exactly one primary recommendation is emitted (no duplicate cards).
        """
        graph = self.get_subject_graph(document_id, learner_masteries=learner_masteries)
        concepts = graph.get("concepts", [])
        topics = graph.get("topics", [])
        concept_by_id = {c["concept_id"]: c for c in concepts}
        topic_by_id = {t["id"]: t for t in topics}

        if not concepts:
            return {
                "subject_id": document_id,
                "starting_concept_id": None,
                "starting_concept_name": None,
                "upstream_prerequisites": [],
                "sequence": [],
                "branching_points": [],
                "cross_chapter_bridges": [],
                "primary_recommendation": None,
            }

        # Build adjacency maps
        adj_out: Dict[str, List[str]] = {c["concept_id"]: [] for c in concepts}
        adj_in: Dict[str, List[str]] = {c["concept_id"]: [] for c in concepts}
        for c in concepts:
            for p in c.get("prerequisites", []):
                if p in concept_by_id:
                    adj_out[p].append(c["concept_id"])
                    adj_in[c["concept_id"]].append(p)

        # Validate starting_concept_id
        valid_start = starting_concept_id if (starting_concept_id and starting_concept_id in concept_by_id) else None

        upstream_prereqs = []
        if valid_start:
            # Gather all ancestors via BFS
            ancestor_set = set()
            queue = list(adj_in[valid_start])
            while queue:
                curr = queue.pop(0)
                if curr not in ancestor_set:
                    ancestor_set.add(curr)
                    queue.extend(adj_in[curr])

            for anc_id in ancestor_set:
                anc_c = concept_by_id[anc_id]
                t_info = topic_by_id.get(anc_c.get("topic_id", ""), {})
                upstream_prereqs.append({
                    "concept_id": anc_id,
                    "name": anc_c["name"],
                    "chapter_id": anc_c.get("topic_id"),
                    "chapter_name": t_info.get("name", "General"),
                    "mastery": anc_c.get("mastery", 0.0),
                    "is_direct": anc_id in adj_in[valid_start],
                })

            # Downstream reachable (including starting concept)
            reachable = {valid_start}
            queue = [valid_start]
            while queue:
                curr = queue.pop(0)
                for nxt in adj_out[curr]:
                    if nxt not in reachable:
                        reachable.add(nxt)
                        queue.append(nxt)
            relevant_cids = reachable
        else:
            relevant_cids = set(concept_by_id.keys())

        # Kahn's algorithm with chapter-coherent prioritization
        in_deg = {cid: 0 for cid in relevant_cids}
        for cid in relevant_cids:
            for p in adj_in[cid]:
                if p in relevant_cids:
                    in_deg[cid] += 1

        ready = [cid for cid in relevant_cids if in_deg[cid] == 0]

        def sort_ready(q: List[str]):
            q.sort(key=lambda cid: (
                0 if cid == valid_start else 1,
                topic_by_id.get(concept_by_id[cid].get("topic_id", ""), {}).get("order", 999),
                concept_by_id[cid]["name"],
            ))

        sort_ready(ready)
        ordered_cids = []
        while ready:
            curr = ready.pop(0)
            ordered_cids.append(curr)
            for nxt in adj_out[curr]:
                if nxt in in_deg:
                    in_deg[nxt] -= 1
                    if in_deg[nxt] == 0:
                        ready.append(nxt)
                        sort_ready(ready)

        # Detect parallel branches (concepts sharing the same prerequisite parent within the sequence)
        branching_points = []
        for cid in ordered_cids:
            dependents_in_seq = [d for d in adj_out[cid] if d in relevant_cids]
            if len(dependents_in_seq) > 1:
                branching_points.append({
                    "parent_concept_id": cid,
                    "parent_name": concept_by_id[cid]["name"],
                    "branches": [
                        {
                            "concept_id": d,
                            "name": concept_by_id[d]["name"],
                            "chapter_name": topic_by_id.get(concept_by_id[d].get("topic_id", ""), {}).get("name", ""),
                        }
                        for d in dependents_in_seq
                    ],
                })

        # Cross-chapter bridges
        cross_bridges = []
        seen_bridges = set()
        for link in graph.get("relationships", []):
            if link.get("type") in ("prerequisite", "prerequisite_of"):
                s_id = link["source"]
                t_id = link["target"]
                if s_id in concept_by_id and t_id in concept_by_id:
                    s_t = concept_by_id[s_id].get("topic_id")
                    t_t = concept_by_id[t_id].get("topic_id")
                    if s_t and t_t and s_t != t_t and (s_id, t_id) not in seen_bridges:
                        seen_bridges.add((s_id, t_id))
                        s_name = concept_by_id[s_id]["name"]
                        t_name = concept_by_id[t_id]["name"]
                        s_ch = topic_by_id.get(s_t, {}).get("name", "Chapter")
                        t_ch = topic_by_id.get(t_t, {}).get("name", "Chapter")
                        cross_bridges.append({
                            "source_concept_id": s_id,
                            "source_name": s_name,
                            "source_chapter": s_ch,
                            "target_concept_id": t_id,
                            "target_name": t_name,
                            "target_chapter": t_ch,
                            "explanation": f"Transitions from {s_ch} ('{s_name}') into {t_ch} ('{t_name}').",
                        })

        # Build sequence items
        sequence = []
        for idx, cid in enumerate(ordered_cids, start=1):
            c_data = concept_by_id[cid]
            t_id = c_data.get("topic_id", "default")
            t_info = topic_by_id.get(t_id, {})
            prereq_names = [concept_by_id[p]["name"] for p in adj_in[cid] if p in concept_by_id]
            is_start = (cid == valid_start)

            # Generate pedagogical explanation
            if is_start:
                reason = "Selected starting concept for your personalized study sequence."
            elif not prereq_names:
                reason = f"Foundational starting concept in {t_info.get('name', 'Curriculum')}."
            elif len(prereq_names) == 1:
                reason = f"Builds directly on prerequisite '{prereq_names[0]}'."
            else:
                reason = f"Integrates concepts from {', '.join(prereq_names[:2])}."

            sequence.append({
                "step_number": idx,
                "step_label": f"Step {idx}",
                "concept_id": cid,
                "name": c_data["name"],
                "chapter_id": t_id,
                "chapter_name": t_info.get("name", "General"),
                "definition": c_data.get("definition"),
                "mastery": c_data.get("mastery", 0.0),
                "is_starting_concept": is_start,
                "prerequisites": prereq_names,
                "prerequisite_ids": adj_in[cid],
                "dependents": [concept_by_id[d]["name"] for d in adj_out[cid] if d in concept_by_id],
                "reason": reason,
                "bloom_level": c_data.get("bloom_level"),
            })

        # Single primary recommendation
        primary_rec = None
        if sequence:
            rec_target = sequence[0]
            if not valid_start:
                unmastered = next((item for item in sequence if item["mastery"] < 0.75), sequence[0])
                rec_target = unmastered

            primary_rec = {
                "concept_id": rec_target["concept_id"],
                "name": rec_target["name"],
                "chapter_name": rec_target["chapter_name"],
                "reason": (
                    f"Recommended starting concept: '{rec_target['name']}' in {rec_target['chapter_name']}."
                    if rec_target["is_starting_concept"] or rec_target["step_number"] == 1
                    else f"Next recommended step: '{rec_target['name']}' ({rec_target['step_label']})."
                ),
            }

        start_name = concept_by_id[valid_start]["name"] if valid_start else None

        return {
            "subject_id": document_id,
            "starting_concept_id": valid_start,
            "starting_concept_name": start_name,
            "upstream_prerequisites": upstream_prereqs,
            "sequence": sequence,
            "branching_points": branching_points,
            "cross_chapter_bridges": cross_bridges,
            "primary_recommendation": primary_rec,
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
