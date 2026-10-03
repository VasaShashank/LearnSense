"""
Semantic Chunk Aggregator for LearnSense Phase 3.

Aggregates fine-grained structural blocks from Phase 1 StructuredDocuments
into coherent semantic chunks (300-500 words/tokens) grouped by section and page,
while maintaining full block-level provenance and citation metadata.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence
from pydantic import BaseModel, Field

from schemas.document import (
    BlockTypeEnum,
    DocumentBlock,
    DocumentPage,
    StructuredDocument,
)


class SemanticChunk(BaseModel):
    """
    A multi-block semantic unit preserving fine-grained block provenance.
    """

    chunk_id: str
    document_id: str
    page_indices: List[int] = Field(default_factory=list)
    block_ids: List[str] = Field(default_factory=list)
    section_id: Optional[str] = None
    section_title: Optional[str] = None
    text: str
    evidence_ids: List[str] = Field(default_factory=list)
    evidence_levels: List[str] = Field(default_factory=list)
    concept_ids: List[str] = Field(default_factory=list)
    roles: List[str] = Field(default_factory=list)
    block_types: List[str] = Field(default_factory=list)
    token_count: int = 0
    score: float = 0.0

    @property
    def primary_page(self) -> int:
        return self.page_indices[0] if self.page_indices else 0

    @property
    def primary_block_id(self) -> str:
        return self.block_ids[0] if self.block_ids else ""

    def citation(self) -> Dict[str, Any]:
        """Citation payload with provenance metadata."""
        excerpt = " ".join((self.text or "").split())
        quote = excerpt if len(excerpt) <= 320 else excerpt[:319].rstrip() + "…"
        return {
            "document_id": self.document_id,
            "page": self.primary_page + 1,
            "pages": [p + 1 for p in self.page_indices],
            "block_id": self.primary_block_id,
            "block_ids": self.block_ids,
            "section": self.section_title,
            "evidence_ids": self.evidence_ids,
            "quote": quote,
        }


class SemanticChunker:
    """
    Aggregates atomic document blocks into contextual semantic chunks.
    """

    def __init__(
        self,
        min_chunk_tokens: int = 80,
        target_chunk_tokens: int = 300,
        max_chunk_tokens: int = 500,
    ) -> None:
        self.min_chunk_tokens = min_chunk_tokens
        self.target_chunk_tokens = target_chunk_tokens
        self.max_chunk_tokens = max_chunk_tokens

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Rough token count estimation (~0.75 words per token)."""
        words = len(re.findall(r"\S+", text or ""))
        return max(1, int(words * 1.3))

    def chunk_document(
        self,
        structured_document: StructuredDocument,
        ekr: Optional[Any] = None,
    ) -> List[SemanticChunk]:
        """
        Produce a sequence of semantic chunks from a StructuredDocument.
        """
        document_id = getattr(structured_document, "document_id", "doc_unknown")
        section_titles = self._extract_section_titles(structured_document)
        evidence_by_block, concepts_by_block = self._extract_ekr_metadata(ekr)

        chunks: List[SemanticChunk] = []
        current_blocks: List[DocumentBlock] = []
        current_page_indices: List[int] = []
        current_section_id: Optional[str] = None
        current_section_title: Optional[str] = None
        current_text_parts: List[str] = []
        current_token_count = 0
        chunk_counter = 1

        def flush_current():
            nonlocal chunk_counter, current_blocks, current_page_indices
            nonlocal current_section_id, current_section_title, current_text_parts, current_token_count

            if not current_blocks:
                return

            full_text = "\n\n".join(t for t in current_text_parts if t.strip()).strip()
            if not full_text:
                current_blocks = []
                current_page_indices = []
                current_text_parts = []
                current_token_count = 0
                return

            all_ev_ids: List[str] = []
            all_ev_levels: List[str] = []
            all_c_ids: List[str] = []
            all_roles: List[str] = []
            all_btypes: List[str] = []

            for b in current_blocks:
                b_evs = evidence_by_block.get(b.block_id, [])
                for ev in b_evs:
                    all_ev_ids.append(getattr(ev, "evidence_id", str(ev)))
                    ev_lvl = getattr(ev, "level", None)
                    if ev_lvl:
                        all_ev_levels.append(getattr(ev_lvl, "value", str(ev_lvl)))
                all_c_ids.extend(concepts_by_block.get(b.block_id, []))
                if getattr(b, "role", None):
                    all_roles.append(b.role)
                btype_val = getattr(getattr(b, "type", None), "value", str(b.type))
                if btype_val:
                    all_btypes.append(btype_val)

            chunk = SemanticChunk(
                chunk_id=f"chk_sem_{document_id}_{chunk_counter:04d}",
                document_id=document_id,
                page_indices=sorted(set(current_page_indices)),
                block_ids=[b.block_id for b in current_blocks],
                section_id=current_section_id,
                section_title=current_section_title,
                text=full_text,
                evidence_ids=sorted(set(all_ev_ids)),
                evidence_levels=sorted(set(all_ev_levels)),
                concept_ids=sorted(set(all_c_ids)),
                roles=sorted(set(all_roles)),
                block_types=sorted(set(all_btypes)),
                token_count=current_token_count,
            )
            chunks.append(chunk)
            chunk_counter += 1

            current_blocks = []
            current_page_indices = []
            current_text_parts = []
            current_token_count = 0
            current_section_id = None
            current_section_title = None

        pages = getattr(structured_document, "pages", []) or []
        for page in pages:
            page_index = getattr(page, "page_index", 0)
            blocks = getattr(page, "blocks", []) or []

            for block in blocks:
                b_text = (getattr(getattr(block, "content", None), "text", "") or "").strip()
                if not b_text:
                    continue

                btype = getattr(block, "type", None)
                btype_str = getattr(btype, "value", str(btype)).lower()
                role_str = str(getattr(block, "role", "")).lower()

                if btype_str in ("page_number", "header", "footer", "watermark"):
                    continue

                is_heading = (
                    btype == BlockTypeEnum.HEADING
                    or "heading" in role_str
                    or role_str.startswith("heading_")
                )
                b_section_id = getattr(block, "section_id", None)
                b_section_title = section_titles.get(b_section_id or "")

                block_tokens = self._estimate_tokens(b_text)

                # Split condition 1: New heading block encounter when chunk has content
                if is_heading and current_token_count >= self.min_chunk_tokens:
                    flush_current()

                # Split condition 2: Section change when chunk has sufficient content
                elif (
                    b_section_id
                    and current_section_id
                    and b_section_id != current_section_id
                    and current_token_count >= self.min_chunk_tokens
                ):
                    flush_current()

                # Split condition 3: Max size exceeded
                elif current_token_count + block_tokens > self.max_chunk_tokens and current_blocks:
                    flush_current()

                # Add block to current working chunk
                current_blocks.append(block)
                if page_index not in current_page_indices:
                    current_page_indices.append(page_index)
                current_text_parts.append(b_text)
                current_token_count += block_tokens
                if not current_section_id and b_section_id:
                    current_section_id = b_section_id
                    current_section_title = b_section_title

        flush_current()
        return chunks

    @staticmethod
    def _extract_section_titles(structured_document: Any) -> Dict[str, str]:
        titles: Dict[str, str] = {}

        def walk(nodes: Sequence[Any]) -> None:
            for node in nodes or []:
                sec_id = getattr(node, "section_id", None)
                sec_title = getattr(node, "title", None)
                if sec_id and sec_title:
                    titles[sec_id] = sec_title
                walk(getattr(node, "children", []) or [])

        walk(getattr(structured_document, "outline", []) or [])
        return titles

    @staticmethod
    def _extract_ekr_metadata(ekr: Any) -> tuple[Dict[str, List[Any]], Dict[str, List[str]]]:
        evidence_by_block: Dict[str, List[Any]] = {}
        concepts_by_block: Dict[str, List[str]] = {}

        if ekr is None:
            return evidence_by_block, concepts_by_block

        for ev in getattr(ekr, "evidence", []) or []:
            b_id = getattr(ev, "block_id", None)
            if b_id:
                evidence_by_block.setdefault(b_id, []).append(ev)

        for mention in getattr(ekr, "mentions", []) or []:
            b_id = getattr(mention, "block_id", None)
            c_id = getattr(mention, "concept_id", None)
            if b_id and c_id:
                concepts_by_block.setdefault(b_id, []).append(c_id)

        return evidence_by_block, concepts_by_block
