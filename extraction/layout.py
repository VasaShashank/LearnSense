"""
Layout Analysis Engine for Taproot Phase 1.
Detects single/multi-column layouts, calculates reading order indices, calculates document font histograms,
and assigns block types (heading H1/H2/H3, paragraph, list_item, code).
Matches Section 11 & Section 15 of TAPROOT_PHASE_1_MASTER_IMPLEMENTATION_PLAN.md.
"""

import re
from typing import Dict, Any, List, Tuple
from schemas.document import BlockTypeEnum, DocumentBlock


class LayoutAnalyzer:
    def __init__(self):
        pass

    def analyze_page_layout(
        self,
        blocks: List[DocumentBlock],
        page_width: float,
        page_height: float,
        body_font_size: float = 10.0,
    ) -> List[DocumentBlock]:
        """
        Processes extracted blocks for a single page:
        1. Classifies block types (heading, paragraph, list_item, code) based on font metrics & regex patterns.
        2. Detects column bands (single-column vs multi-column).
        3. Sorts blocks into deterministic logical reading order.
        """
        if not blocks:
            return []

        # 1. Refine Block Types & Heading Levels
        for block in blocks:
            self._refine_block_type(block, body_font_size)

        # 2. Determine Layout & Sort Reading Order
        sorted_blocks = self._sort_reading_order(blocks, page_width)

        # 3. Assign 1-based reading_order index
        for idx, block in enumerate(sorted_blocks, start=1):
            block.reading_order = idx

        return sorted_blocks

    def _refine_block_type(self, block: DocumentBlock, body_font_size: float) -> None:
        text = block.content.text.strip()
        spans = block.content.structured_data.get("spans", []) if block.content.structured_data else []

        # Calculate average font size for this block
        font_sizes = [s.get("size", body_font_size) for s in spans] if spans else [body_font_size]
        avg_font_size = sum(font_sizes) / len(font_sizes) if font_sizes else body_font_size

        # Check for list item pattern (e.g., "1. ", "a) ", "• ", "- ")
        list_pattern = r"^(\d+[\.\)]|[a-zA-Z][\.\)]|[\u2022\u25e6\u2013\u2014\-*])\s+"
        if re.match(list_pattern, text):
            block.type = BlockTypeEnum.LIST_ITEM
            return

        # Check for code block pattern (monospace font or indentation)
        font_names = [s.get("font", "").lower() for s in spans]
        if any("mono" in f or "courier" in f or "code" in f for f in font_names):
            block.type = BlockTypeEnum.CODE
            return

        # Check for Heading based on font size threshold formula from Section 11:
        # Score = w1*(S_block/S_body) + w2*IsBold + w3*HasNumbering
        is_bold = any("bold" in f or "black" in f for f in font_names)
        numbering_pattern = r"^(\d+(\.\d+)*)\s+[A-Z]"
        has_numbering = bool(re.match(numbering_pattern, text))

        size_ratio = avg_font_size / max(body_font_size, 1.0)

        if size_ratio >= 1.15 or is_bold or (has_numbering and len(text) < 100):
            block.type = BlockTypeEnum.HEADING
            # Role stores heading level tag (e.g. "heading_l1", "heading_l2", "heading_l3")
            if size_ratio >= 1.6 or (size_ratio >= 1.3 and is_bold):
                block.role = "heading_l1"
            elif size_ratio >= 1.25 or is_bold:
                block.role = "heading_l2"
            else:
                block.role = "heading_l3"
            return

        # Default to paragraph
        block.type = BlockTypeEnum.PARAGRAPH
        block.role = "body"

    def _sort_reading_order(self, blocks: List[DocumentBlock], page_width: float) -> List[DocumentBlock]:
        """
        Sorts blocks by column layout:
        Detects if page is multi-column by analyzing horizontal bounding box overlaps.
        """
        midpoint = page_width / 2.0

        # Classify blocks into Left Column, Right Column, or Full Width
        left_column = []
        right_column = []
        full_width = []

        for block in blocks:
            x0, y0, x1, y1 = block.bbox
            width = x1 - x0

            if width > page_width * 0.65:
                full_width.append(block)
            elif x1 <= midpoint + 20:
                left_column.append(block)
            elif x0 >= midpoint - 20:
                right_column.append(block)
            else:
                # Spans middle boundary
                left_column.append(block)

        # If both left and right columns have multiple blocks, it's a 2-column layout
        if len(left_column) >= 2 and len(right_column) >= 2:
            # Sort full width / top headers first, then left column top-to-bottom, then right column top-to-bottom
            left_sorted = sorted(left_column, key=lambda b: b.bbox[1])
            right_sorted = sorted(right_column, key=lambda b: b.bbox[1])
            full_sorted = sorted(full_width, key=lambda b: b.bbox[1])

            # Merge based on vertical positions
            result = []
            for fw in full_sorted:
                # Append left column blocks that appear above this full-width block
                while left_sorted and left_sorted[0].bbox[1] < fw.bbox[1]:
                    result.append(left_sorted.pop(0))
                while right_sorted and right_sorted[0].bbox[1] < fw.bbox[1]:
                    result.append(right_sorted.pop(0))
                result.append(fw)

            result.extend(left_sorted)
            result.extend(right_sorted)
            return result

        # Default Single-Column sort (top-to-bottom, left-to-right)
        return sorted(blocks, key=lambda b: (b.bbox[1], b.bbox[0]))

    @staticmethod
    def calculate_document_body_font_size(page_blocks_list: List[List[DocumentBlock]]) -> float:
        """Calculates statistical mode for body font size across document native blocks."""
        font_sizes = []
        for blocks in page_blocks_list:
            for block in blocks:
                spans = block.content.structured_data.get("spans", []) if block.content.structured_data else []
                for s in spans:
                    size = s.get("size")
                    if size:
                        font_sizes.append(round(size, 1))

        if not font_sizes:
            return 10.0

        # Return statistical mode (most frequent font size)
        from collections import Counter
        counts = Counter(font_sizes)
        return counts.most_common(1)[0][0]
