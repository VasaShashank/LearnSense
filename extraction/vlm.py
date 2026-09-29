"""
VLM Extraction Engine & Schema Validator for LearnSense Document Intelligence.

Transforms rendered page images into validated canonical DocumentBlock structures
with verified coordinates, provenance metadata, and strict block-type classification.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple
import fitz  # PyMuPDF

from adapters.vlm_adapter import VLMAdapter, get_vlm_adapter
from schemas.document import (
    BlockContent,
    BlockStatusEnum,
    BlockTypeEnum,
    DocumentBlock,
    EngineInfo,
    ExtractionMethodEnum,
)

logger = logging.getLogger("LearnSense.VLMEngine")


class VLMEngine:
    """
    Orchestrates visual extraction via VLM and maps raw visual responses into
    canonical, validated DocumentBlock instances.
    """

    def __init__(self, vlm_adapter: Optional[VLMAdapter] = None, render_dpi: int = 150):
        self.vlm_adapter = vlm_adapter or get_vlm_adapter()
        self.render_dpi = render_dpi

    def process_visual_page(
        self,
        page: fitz.Page,
        page_width: float,
        page_height: float,
        page_index: int = 0,
        context_hint: str = "",
    ) -> List[DocumentBlock]:
        """
        Renders the page at visual analysis resolution, invokes the VLM adapter,
        and converts responses to validated DocumentBlocks.
        """
        # Render image for VLM
        dpi_scale = self.render_dpi / 72.0
        mat = fitz.Matrix(dpi_scale, dpi_scale)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img_bytes = pix.tobytes("png")

        raw_blocks = self.vlm_adapter.extract_visual_blocks(
            image_bytes=img_bytes,
            page_index=page_index,
            page_width=page_width,
            page_height=page_height,
            context_hint=context_hint,
        )

        return self.validate_and_normalize_blocks(
            raw_blocks=raw_blocks,
            page_width=page_width,
            page_height=page_height,
            page_index=page_index,
        )

    def validate_and_normalize_blocks(
        self,
        raw_blocks: List[Dict[str, Any]],
        page_width: float,
        page_height: float,
        page_index: int,
    ) -> List[DocumentBlock]:
        """
        Validates structure, enforces bbox constraints within page boundaries,
        and standardizes block schemas.
        """
        validated_blocks: List[DocumentBlock] = []

        type_mapping = {
            "heading": BlockTypeEnum.HEADING,
            "title": BlockTypeEnum.HEADING,
            "header": BlockTypeEnum.HEADER,
            "paragraph": BlockTypeEnum.PARAGRAPH,
            "body": BlockTypeEnum.PARAGRAPH,
            "figure": BlockTypeEnum.FIGURE,
            "diagram": BlockTypeEnum.FIGURE,
            "chart": BlockTypeEnum.FIGURE,
            "table": BlockTypeEnum.TABLE,
            "equation": BlockTypeEnum.EQUATION,
            "formula": BlockTypeEnum.EQUATION,
            "math": BlockTypeEnum.EQUATION,
            "list_item": BlockTypeEnum.LIST_ITEM,
            "caption": BlockTypeEnum.CAPTION,
            "code": BlockTypeEnum.CODE,
            "sidebar": BlockTypeEnum.SIDEBAR,
        }

        for idx, raw in enumerate(raw_blocks, start=1):
            text = str(raw.get("text", "")).strip()
            if not text:
                continue

            # Validate / map block type
            raw_type = str(raw.get("type", "paragraph")).lower()
            block_type = type_mapping.get(raw_type, BlockTypeEnum.PARAGRAPH)

            # Validate & normalize bounding box
            raw_bbox = raw.get("bbox")
            if isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) == 4:
                try:
                    x0 = max(0.0, min(page_width, float(raw_bbox[0])))
                    y0 = max(0.0, min(page_height, float(raw_bbox[1])))
                    x1 = max(x0 + 1.0, min(page_width, float(raw_bbox[2])))
                    y1 = max(y0 + 1.0, min(page_height, float(raw_bbox[3])))
                    bbox = [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)]
                except (ValueError, TypeError):
                    bbox = [0.0, 0.0, page_width, page_height]
            else:
                bbox = [0.0, 0.0, page_width, page_height]

            confidence = float(raw.get("confidence", 0.90))
            confidence = max(0.0, min(1.0, confidence))

            block_id = f"blk_p{page_index:04d}_vlm_{idx:04d}"
            role = str(raw.get("role", "body"))

            structured_data = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else None

            doc_block = DocumentBlock(
                block_id=block_id,
                type=block_type,
                role=role,
                bbox=bbox,
                content=BlockContent(text=text, text_raw=text, structured_data=structured_data),
                reading_order=idx,
                extraction_method=ExtractionMethodEnum.VLM,
                engine=EngineInfo(name="VLM", version=getattr(self.vlm_adapter, "model", "vlm-1.0")),
                confidence=confidence,
                status=BlockStatusEnum.OK if confidence >= 0.70 else BlockStatusEnum.OK_LOW_CONFIDENCE,
            )
            validated_blocks.append(doc_block)

        return validated_blocks
