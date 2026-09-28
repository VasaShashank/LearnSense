"""
Shared test helpers that build a *real* mini document and retriever.

Phase 3 question generation is grounded in retrieved passages, so tests that exercise it
need an actual ``StructuredDocument`` for :class:`EvidenceRetriever` to index. Hand-built
EKRs with no blocks used to be enough only because the builder fabricated its questions.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from phase2.models import (
    AssessableItem,
    Concept,
    ConceptMention,
    ConfidenceBreakdown,
    EducationalKnowledgeRepresentation,
    EducationalUnit,
    Evidence,
    EvidenceKindEnum,
    EvidenceLevelEnum,
    SourceSpanReference,
    TextSpan,
)
from phase3.retrieval.evidence_retriever import EvidenceRetriever
from schemas.document import (
    BlockContent,
    BlockTypeEnum,
    DocumentBlock,
    DocumentMetadata,
    DocumentPage,
    ExtractionMethodEnum,
    ProcessingStatusEnum,
    SectionNode,
    SourceMetadata,
    StructuredDocument,
    TitleMetadata,
    TitleSourceEnum,
)

_EXTRACTION = ExtractionMethodEnum.NATIVE


def build_mini_document(
    document_id: str,
    blocks: List[tuple],
    section_title: str = "Integration",
    section_id: str = "sec_integration",
) -> StructuredDocument:
    """
    Build a one-page document.

    ``blocks`` is a list of ``(block_id, text, type)`` tuples.
    """
    document_blocks: List[DocumentBlock] = []
    for order, (block_id, text, block_type) in enumerate(blocks):
        document_blocks.append(
            DocumentBlock(
                block_id=block_id,
                type=block_type,
                role=block_type.value if hasattr(block_type, "value") else str(block_type),
                bbox=[0.0, 50.0 + order * 20, 612.0, 66.0 + order * 20],
                content=BlockContent(text=text, text_raw=text),
                reading_order=order,
                section_id=section_id,
                extraction_method=_EXTRACTION,
            )
        )

    return StructuredDocument(
        document_id=document_id,
        source=SourceMetadata(
            sha256=f"testsha_{document_id}",
            filename=f"{document_id}.pdf",
            size_bytes=sum(len(t) for _, t, _ in blocks),
        ),
        metadata=DocumentMetadata(
            page_count=1,
            title=TitleMetadata(value=section_title, source=TitleSourceEnum.INFERRED),
            processing_status=ProcessingStatusEnum.COMPLETED,
        ),
        pages=[
            DocumentPage(
                page_index=0,
                page_label="1",
                width=612.0,
                height=792.0,
                blocks=document_blocks,
            )
        ],
        outline=[
            SectionNode(
                section_id=section_id,
                title=section_title,
                level=1,
                page_start=0,
            )
        ],
    )


def build_ekr(
    document_id: str,
    document: StructuredDocument,
    concepts: List[tuple],
    evidence: Optional[List[tuple]] = None,
    units: Optional[List[EducationalUnit]] = None,
    assessable_items: Optional[List[AssessableItem]] = None,
) -> EducationalKnowledgeRepresentation:
    """
    Build an EKR whose evidence/mentions point at real blocks of ``document``.

    ``concepts`` is a list of ``(concept_id, canonical_name, block_id)``.
    ``evidence`` is a list of ``(evidence_id, block_id, excerpt)``.
    """
    ekr = EducationalKnowledgeRepresentation(
        knowledge_document_id=f"k_{document_id}",
        source_document_id=document_id,
        concepts=[
            Concept(
                concept_id=concept_id,
                canonical_name=name,
                confidence=ConfidenceBreakdown(value=0.95),
            )
            for concept_id, name, _ in concepts
        ],
        educational_units=units or [],
        assessable_items=assessable_items or [],
        evidence=[
            Evidence(
                evidence_id=evidence_id,
                block_id=block_id,
                span=TextSpan(start=0, end=len(excerpt)),
                excerpt=excerpt,
                level=EvidenceLevelEnum.EXPLICIT,
                kind=EvidenceKindEnum.EXPLICIT_STATEMENT,
            )
            for evidence_id, block_id, excerpt in (evidence or [])
        ],
        mentions=[
            ConceptMention(
                mention_id=f"mn_{concept_id}",
                concept_id=concept_id,
                block_id=block_id,
                span=TextSpan(start=0, end=10),
                surface_form=name,
            )
            for concept_id, name, block_id in concepts
        ],
    )
    return ekr


def build_retriever(
    document_id: str,
    document: StructuredDocument,
    concepts: List[tuple],
    evidence: Optional[List[tuple]] = None,
) -> EvidenceRetriever:
    """Convenience wrapper producing a document, EKR and retriever in one call."""
    ekr = build_ekr(document_id, document, concepts, evidence)
    return EvidenceRetriever(document, ekr)


__all__ = [
    "BlockTypeEnum",
    "SourceSpanReference",
    "TextSpan",
    "EducationalUnit",
    "AssessableItem",
    "build_mini_document",
    "build_ekr",
    "build_retriever",
    "grounded_payload",
]


def grounded_payload(chunks, concept_id: str, count: int = 2) -> Dict[str, Any]:
    """
    Build an LLM payload whose questions are genuinely answerable from ``chunks``.

    The question, the correct option and the explanation are all lifted from the real
    passage text, so the grounding checks in
    :class:`~phase3.question_bank.validator.QuestionBankValidator` pass for the right
    reason. Distractors are negated variants of the real sentence rather than filler,
    because the builder now rejects questions that share no vocabulary with their
    citation.

    Each returned question is textually distinct so deduplication is not what makes a
    test pass.
    """
    questions = []
    for chunk in chunks:
        if len(questions) >= count:
            break
        for sentence in _sentences(chunk.text):
            if len(questions) >= count:
                break
            stem = sentence.rstrip(".")
            if len(stem) < 25:
                continue
            lowered = stem[:1].lower() + stem[1:]
            questions.append(
                {
                    "question_text": f"According to the passage, what does this state: {lowered}?",
                    "options": [
                        stem,
                        f"The passage says instead that {lowered} is always false",
                        f"The passage denies that {lowered} applies here",
                        f"The passage never mentions {lowered}",
                    ],
                    "correct_answer": stem,
                    "explanation": f"The passage states: {sentence}",
                    "evidence_refs": [f"E{_chunk_index(chunks, chunk)}"],
                    "concept_id": concept_id,
                    "difficulty": 0.3 + (0.1 * len(questions)),
                }
            )
    return {"questions": questions}


def _chunk_index(chunks, target) -> int:
    for i, chunk in enumerate(chunks, start=1):
        if chunk is target or chunk.chunk_id == target.chunk_id:
            return i
    return 1


def _sentences(text: str) -> List[str]:
    # Blocks often contain hard line breaks as well as sentence punctuation.
    flattened = re.sub(r"\s*\n+\s*", " ", (text or "").strip())
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", flattened) if s.strip()]
