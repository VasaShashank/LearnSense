"""
Mathematics Detector and Parser Engine for Taproot Phase 1.
Detects mathematical symbol density, CMEX/CMSY fonts, inline math spans vs display equations,
and generates LaTeX representation or crops equation image assets with MATH_UNPARSED warning.
Matches Section 12 & Section 18 of TAPROOT_PHASE_1_MASTER_IMPLEMENTATION_PLAN.md.
"""

import re
from typing import Dict, Any, List, Tuple, Optional
import fitz  # PyMuPDF
from ingestion.coordinate import CoordinateNormalizer
from schemas.document import (
    AssetTypeEnum,
    BlockContent,
    BlockStatusEnum,
    BlockTypeEnum,
    DocumentAsset,
    DocumentBlock,
    EngineInfo,
    ExtractionMethodEnum,
)


class MathExtractor:
    # Mathematical symbols regex
    MATH_SYMBOLS_PATTERN = r"[\u2200-\u22FF\u2A00-\u2AFF\u2100-\u214F\u0370-\u03FF=+\-*/^√∫∑∏αβγδεθλπσωΔ∇]"

    def __init__(self, confidence_threshold: float = 0.85):
        self.confidence_threshold = confidence_threshold

    def is_math_block(self, block: DocumentBlock) -> bool:
        """
        Determines if a block is a mathematical equation based on symbol density,
        fonts (CMEX/CMSY/MathJax), or equation numbering (e.g. '(1.1)').
        """
        text = block.content.text.strip()
        if not text:
            return False

        spans = block.content.structured_data.get("spans", []) if block.content.structured_data else []
        font_names = [s.get("font", "").lower() for s in spans]

        # Check font names
        if any("math" in f or "cmex" in f or "cmsy" in f or "symbol" in f for f in font_names):
            return True

        # Check symbol count ratio
        symbols = re.findall(self.MATH_SYMBOLS_PATTERN, text)
        if len(text) > 0 and (len(symbols) / len(text)) >= 0.25:
            return True

        # Check isolated equation number pattern e.g. "(1.2)" or "Eq. 3"
        if re.search(r"^\s*(\([0-9]+(\.[0-9]+)*\)|Eq\.\s*[0-9]+)\s*$", text):
            return True

        return False

    def process_math_blocks(
        self,
        blocks: List[DocumentBlock],
        fitz_page: fitz.Page,
        page_index: int,
        page_width: float,
        page_height: float,
        document_id: str,
    ) -> Tuple[List[DocumentBlock], List[DocumentAsset]]:
        """
        Scans page blocks for display equations:
        If math is native, isolates as BlockTypeEnum.EQUATION.
        If math parsing confidence is low or complex equation image, crops region as PNG asset,
        sets status to preserved_only, and attaches MATH_UNPARSED warning.
        """
        processed_blocks: List[DocumentBlock] = []
        math_assets: List[DocumentAsset] = []

        for idx, block in enumerate(blocks, start=1):
            if self.is_math_block(block):
                block.type = BlockTypeEnum.EQUATION
                block.role = "equation"
                block.extraction_method = ExtractionMethodEnum.MATH_PARSER

                # Reformat simple text to LaTeX representation if high confidence
                text = block.content.text.strip()
                if self._can_convert_to_latex(text):
                    latex_str = self._text_to_latex(text)
                    block.content.text = f"$${latex_str}$$"
                    block.confidence = 0.90
                    block.status = BlockStatusEnum.OK
                else:
                    # Fallback: Crop Equation Asset
                    block_id = block.block_id
                    crop_asset = self._create_math_crop_asset(
                        fitz_page, idx, block.bbox, page_index, document_id
                    )
                    block.extraction_method = ExtractionMethodEnum.PRESERVED
                    block.status = BlockStatusEnum.PRESERVED_ONLY
                    block.confidence = 0.0
                    block.asset_ids = [crop_asset.asset_id]
                    block.warnings.append("MATH_UNPARSED")
                    math_assets.append(crop_asset)

            processed_blocks.append(block)

        return processed_blocks, math_assets

    def _can_convert_to_latex(self, text: str) -> bool:
        """Determines if text is clean enough to format into LaTeX without ML vision."""
        if len(text) > 150:
            return False
        # Avoid complex multi-line matrices or unparsed OCR gibberish
        if "\n" in text and len(text.splitlines()) > 3:
            return False
        return True

    def _text_to_latex(self, text: str) -> str:
        """Simple deterministic text-to-LaTeX character converter."""
        text = text.replace("√", "\\sqrt")
        text = text.replace("∫", "\\int")
        text = text.replace("∑", "\\sum")
        text = text.replace("α", "\\alpha")
        text = text.replace("β", "\\beta")
        text = text.replace("θ", "\\theta")
        text = text.replace("π", "\\pi")
        text = text.replace("λ", "\\lambda")
        text = text.replace("Δ", "\\Delta")
        return text

    def _create_math_crop_asset(
        self,
        page: fitz.Page,
        eq_idx: int,
        canonical_bbox: List[float],
        page_index: int,
        document_id: str,
    ) -> DocumentAsset:
        asset_id = f"ast_eq_{page_index:02d}_{eq_idx:02d}"
        crop_rect = fitz.Rect(canonical_bbox[0], canonical_bbox[1], canonical_bbox[2], canonical_bbox[3])

        pix = page.get_pixmap(clip=crop_rect, dpi=200)
        img_bytes = pix.tobytes("png")
        sha256 = fitz.get_sha256(img_bytes)

        filename = f"{asset_id}.png"
        uri = f"documents/{document_id}/assets/{filename}"

        return DocumentAsset(
            asset_id=asset_id,
            type=AssetTypeEnum.EQUATION_CROP,
            page_index=page_index,
            bbox=canonical_bbox,
            uri=uri,
            sha256=sha256,
            is_decorative=False,
        )
