"""
Knowledge Service Facade for Taproot Application Layer.
Exposes authoritative document information, EKR concepts, topics, skills,
prerequisites and evidence views for frontend consumption.

Every field returned here is read from persisted, document-derived state. The service
deliberately refuses to invent content: if a document has not been ingested, or a
concept carries no definition or provenance, the response says so instead of filling the
gap with a placeholder title, a made-up page number or a canned sentence.
"""

from typing import Any, Dict, List, Optional

from phase3.errors import KnowledgeNotFoundError
from phase3.knowledge.phase2_adapter import LearningContext
from storage.repositories import LearningContextRepository
from storage.store import DocumentStorage


class KnowledgeService:
    def __init__(
        self,
        doc_storage: Optional[DocumentStorage] = None,
        context_repo: Optional[LearningContextRepository] = None,
    ):
        self.doc_storage = doc_storage or DocumentStorage()
        self.context_repo = context_repo or LearningContextRepository()

    # -- listing ------------------------------------------------------------

    def list_subjects(self) -> List[Dict[str, Any]]:
        """
        List ingested documents that have a persisted learning context.

        Only documents the learner actually uploaded are returned; there are no demo
        subjects.
        """
        subjects: List[Dict[str, Any]] = []
        root_dir = self.doc_storage.root_dir
        if not root_dir.exists():
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
        masteries = learner_masteries or {}

        # Real topics, keyed by id so concepts can be attached to them.
        topic_by_id: Dict[str, Dict[str, Any]] = {}
        concept_to_topic: Dict[str, str] = {}
        for order, topic in enumerate(ctx.topics or [], start=1):
            topic_id = str(topic.get("topic_id") or f"topic_{order}")
            topic_by_id[topic_id] = {
                "id": topic_id,
                "name": str(topic.get("title") or topic_id.replace("_", " ").title()),
                "order": order,
            }
            for concept_id in topic.get("concept_ids") or []:
                concept_to_topic.setdefault(concept_id, topic_id)

        # §2 #25: Concepts that no topic references are grouped under an explicit
        # "Unassigned Concepts" label — never presented as a curriculum topic.
        unassigned = [cid for cid in ctx.concepts if cid not in concept_to_topic]
        if unassigned:
            fallback_id = f"unassigned_{ctx.document_id}"
            topic_by_id[fallback_id] = {
                "id": fallback_id,
                "name": "Unassigned Concepts",
                "order": len(topic_by_id) + 1,
                "is_unassigned": True,
            }
            for concept_id in unassigned:
                concept_to_topic[concept_id] = fallback_id

        prereqs_by_target: Dict[str, List[str]] = {}
        dependents_by_source: Dict[str, List[str]] = {}
        for link in ctx.prerequisites or []:
            prereqs_by_target.setdefault(link.target_concept_id, []).append(link.source_concept_id)
            dependents_by_source.setdefault(link.source_concept_id, []).append(link.target_concept_id)

        concepts_out: List[Dict[str, Any]] = []
        for concept_id, concept in ctx.concepts.items():
            mastery = float(masteries.get(concept_id, 0.0))
            prereqs = [
                p for p in prereqs_by_target.get(concept_id, []) if p in ctx.concepts
            ]
            dependents = [
                d for d in dependents_by_source.get(concept_id, []) if d in ctx.concepts
            ]

            concepts_out.append(
                {
                    "concept_id": concept_id,
                    "name": concept.canonical_name,
                    # The source-derived description, or None when the document did not
                    # provide one. A generic sentence would be indistinguishable from a
                    # real definition in the UI.
                    "definition": concept.description or None,
                    "topic_id": concept_to_topic.get(concept_id),
                    "bloom_level": concept.type or None,
                    "mastery": round(mastery, 4),
                    "uncertainty": round(max(0.05, 1.0 - abs(mastery - 0.5) * 2), 4),
                    "prerequisites": prereqs,
                    "dependents": dependents,
                    # Real locations only: pages and block IDs recorded by Phase 2.
                    "source_references": self._source_references(ctx, concept),
                }
            )

        relationships = [
            {
                "source": link.source_concept_id,
                "target": link.target_concept_id,
                "type": "prerequisite_of",
                "confidence": link.confidence,
                "evidence_ids": list(link.evidence_ids or []),
            }
            for link in ctx.prerequisites or []
            if link.source_concept_id in ctx.concepts and link.target_concept_id in ctx.concepts
        ]

        return {
            "subject_id": document_id,
            "topics": list(topic_by_id.values()),
            "concepts": concepts_out,
            "relationships": relationships,
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
