"""
Pass B Document-Level Aggregator and Outline Section Tree Builder for Taproot Phase 1.
Performs cross-page passes:
1. Classifies repeated headers, footers, and page numbers based on position frequency across pages.
2. Connects cross-page paragraph continuation links (continues_from / continues_to).
3. Builds hierarchical document outline section tree (SectionNode).
4. Reconciles physical page_index with printed page_label.
5. Assembles canonical StructuredDocument output.
Matches Section 10 & Section 11 of TAPROOT_PHASE_1_MASTER_IMPLEMENTATION_PLAN.md.
"""

from collections import Counter
import re
from typing import Dict, Any, List, Optional, Tuple
import fitz  # PyMuPDF
from schemas.document import (
    BlockTypeEnum,
    DocumentBlock,
    DocumentMetadata,
    DocumentPage,
    DocumentWarning,
    ProcessingStatusEnum,
    SectionNode,
    SourceMetadata,
    StructuredDocument,
    TitleMetadata,
    TitleSourceEnum,
)


class PassBAggregator:
    def __init__(self):
        pass

    def process_document(
        self,
        document_id: str,
        source_meta: SourceMetadata,
        pages: List[DocumentPage],
        pdf_outline_toc: Optional[List[Tuple[int, str, int]]] = None,  # [(level, title, page_num)]
    ) -> StructuredDocument:
        """
        Executes Pass B cross-page aggregation on extracted page blocks.
        """
        if not pages:
            # Empty pages fallback
            doc_meta = DocumentMetadata(
                page_count=0,
                title=TitleMetadata(value=source_meta.filename, source=TitleSourceEnum.INFERRED),
                processing_status=ProcessingStatusEnum.COMPLETED,
            )
            return StructuredDocument(
                document_id=document_id,
                source=source_meta,
                metadata=doc_meta,
                outline=[],
                pages=[],
            )

        # 1. Classify Repeated Headers, Footers, and Page Numbers
        self._classify_repeated_header_footer_page_numbers(pages)

        # 2. Connect Cross-Page Block Continuity Links
        self._connect_cross_page_continuity(pages)

        # 3. Build Outline Section Tree
        outline = self._build_section_tree(pages, pdf_outline_toc)

        # 4. Infer Document Title
        title_val, title_src = self._infer_document_title(pages, source_meta.filename, pdf_outline_toc)

        # 5. Check Document-Level Warnings
        document_warnings = self._collect_document_warnings(pages)
        status = ProcessingStatusEnum.COMPLETED_WITH_WARNINGS if document_warnings else ProcessingStatusEnum.COMPLETED

        doc_meta = DocumentMetadata(
            page_count=len(pages),
            title=TitleMetadata(value=title_val, source=title_src),
            processing_status=status,
        )

        return StructuredDocument(
            document_id=document_id,
            source=source_meta,
            metadata=doc_meta,
            outline=outline,
            pages=pages,
            warnings=document_warnings,
        )

    def _classify_repeated_header_footer_page_numbers(self, pages: List[DocumentPage]) -> None:
        """
        Detects running headers (top margin band) and footers/page numbers (bottom margin band)
        that repeat across > 30% of pages. Tags them with roles 'header', 'footer', or 'page_number'
        without deleting them.
        """
        num_pages = len(pages)
        if num_pages < 2:
            return

        header_texts = []
        footer_texts = []

        for page in pages:
            height = page.height
            top_margin = height * 0.12     # Top 12%
            bottom_margin = height * 0.88  # Bottom 12%

            for block in page.blocks:
                y0, y1 = block.bbox[1], block.bbox[3]
                text_clean = block.content.text.strip()

                if y1 <= top_margin and text_clean:
                    header_texts.append(text_clean)
                elif y0 >= bottom_margin and text_clean:
                    footer_texts.append(text_clean)

        header_counts = Counter(header_texts)
        footer_counts = Counter(footer_texts)

        repeating_headers = {txt for txt, count in header_counts.items() if count >= max(2, int(num_pages * 0.3))}
        repeating_footers = {txt for txt, count in footer_counts.items() if count >= max(2, int(num_pages * 0.3))}

        # Assign block roles
        for page in pages:
            height = page.height
            top_margin = height * 0.12
            bottom_margin = height * 0.88

            for block in page.blocks:
                y0, y1 = block.bbox[1], block.bbox[3]
                text_clean = block.content.text.strip()

                # Page Number Check (isolated numbers or 'Page X of Y' in margins)
                if (y1 <= top_margin or y0 >= bottom_margin) and re.match(r"^(\d+|Page\s+\d+(\s+of\s+\d+)?)$", text_clean, re.I):
                    block.type = BlockTypeEnum.PAGE_NUMBER
                    block.role = "page_number"
                    # Also set printed page label if found in bottom margin
                    if y0 >= bottom_margin and re.match(r"^\d+$", text_clean):
                        page.page_label = text_clean
                    continue

                if y1 <= top_margin and text_clean in repeating_headers:
                    block.type = BlockTypeEnum.HEADER
                    block.role = "header"
                elif y0 >= bottom_margin and text_clean in repeating_footers:
                    block.type = BlockTypeEnum.FOOTER
                    block.role = "footer"

    def _connect_cross_page_continuity(self, pages: List[DocumentPage]) -> None:
        """
        Links paragraphs that break across page boundaries.
        If a page ends with a body block lacking terminal punctuation ('.', '!', '?')
        and the next page starts with a lowercase/body block, link them via continues_to / continues_from.
        """
        for i in range(len(pages) - 1):
            page_curr = pages[i]
            page_next = pages[i + 1]

            # Find last body block on current page
            curr_body_blocks = [b for b in page_curr.blocks if b.type == BlockTypeEnum.PARAGRAPH and b.role == "body"]
            next_body_blocks = [b for b in page_next.blocks if b.type == BlockTypeEnum.PARAGRAPH and b.role == "body"]

            if not curr_body_blocks or not next_body_blocks:
                continue

            last_block = curr_body_blocks[-1]
            first_block = next_body_blocks[0]

            last_text = last_block.content.text.strip()
            first_text = first_block.content.text.strip()

            if last_text and first_text:
                # Check if last sentence is incomplete (doesn't end with ., !, ?)
                if not last_text[-1] in ".!?:;" and first_text[0].islower():
                    last_block.continues_to = first_block.block_id
                    first_block.continues_from = last_block.block_id

    def _build_section_tree(
        self,
        pages: List[DocumentPage],
        pdf_outline_toc: Optional[List[Tuple[int, str, int]]] = None,
    ) -> List[SectionNode]:
        """
        Builds document SectionNode hierarchy from detected heading blocks and PDF bookmarks.
        """
        sections: List[SectionNode] = []
        sec_counter = 1

        # 1. Use PDF Bookmarks if available
        if pdf_outline_toc:
            for level, title, page_num in pdf_outline_toc:
                node = SectionNode(
                    section_id=f"sec_{sec_counter:03d}",
                    title=title,
                    level=level,
                    page_start=max(1, page_num),
                )
                sections.append(node)
                sec_counter += 1
            return self._nest_sections(sections)

        # 2. Derive from detected HEADING blocks across pages
        for page in pages:
            for block in page.blocks:
                if block.type == BlockTypeEnum.HEADING:
                    level = 1
                    if block.role == "heading_l2":
                        level = 2
                    elif block.role == "heading_l3":
                        level = 3

                    sec_id = f"sec_{sec_counter:03d}"
                    block.section_id = sec_id

                    node = SectionNode(
                        section_id=sec_id,
                        title=block.content.text.strip(),
                        level=level,
                        page_start=page.page_index + 1,
                    )
                    sections.append(node)
                    sec_counter += 1

        return self._nest_sections(sections)

    def _nest_sections(self, flat_sections: List[SectionNode]) -> List[SectionNode]:
        """Converts flat list of section nodes into a nested tree based on level."""
        if not flat_sections:
            return []

        root_nodes: List[SectionNode] = []
        stack: List[SectionNode] = []

        for node in flat_sections:
            while stack and stack[-1].level >= node.level:
                stack.pop()

            if stack:
                stack[-1].children.append(node)
            else:
                root_nodes.append(node)

            stack.append(node)

        return root_nodes

    def _infer_document_title(
        self,
        pages: List[DocumentPage],
        fallback_filename: str,
        pdf_outline_toc: Optional[List[Tuple[int, str, int]]] = None,
    ) -> Tuple[str, TitleSourceEnum]:
        # 1. First H1 heading on Page 1
        if pages and pages[0].blocks:
            for b in pages[0].blocks:
                if b.type == BlockTypeEnum.HEADING and b.role == "heading_l1":
                    return b.content.text.strip(), TitleSourceEnum.INFERRED

        # 2. First bookmark title
        if pdf_outline_toc:
            return pdf_outline_toc[0][1], TitleSourceEnum.PDF_METADATA

        # 3. Fallback to filename
        clean_title = fallback_filename.rsplit(".", 1)[0].replace("_", " ").title()
        return clean_title, TitleSourceEnum.INFERRED

    def _collect_document_warnings(self, pages: List[DocumentPage]) -> List[DocumentWarning]:
        warnings = []
        for page in pages:
            if page.status == "ok_low_confidence":
                warnings.append(
                    DocumentWarning(
                        code="LOW_OCR_CONFIDENCE",
                        severity="low",
                        page_index=page.page_index,
                        message=f"Page {page.page_index + 1} processed with low confidence.",
                    )
                )
            for block in page.blocks:
                for w_code in block.warnings:
                    warnings.append(
                        DocumentWarning(
                            code=w_code,
                            severity="medium",
                            page_index=page.page_index,
                            block_id=block.block_id,
                            message=f"Warning on block {block.block_id}: {w_code}",
                        )
                    )
        return warnings
