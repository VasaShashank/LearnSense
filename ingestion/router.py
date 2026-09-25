"""
Escalation Router for Taproot Phase 1 Ingestion.
Executes the 4-rung progressive processing escalation ladder:
Rung 1: Native Text Extraction -> Rung 2: Layout Analysis -> Rung 3: Tesseract OCR -> Rung 4: Preserved Asset Fallback.
Matches Section 11 & Section 15 of TAPROOT_PHASE_1_MASTER_IMPLEMENTATION_PLAN.md.
"""

from typing import Dict, Any, List, Tuple, Optional
import fitz  # PyMuPDF
from extraction.figures import FigureExtractor
from extraction.layout import LayoutAnalyzer
from extraction.math import MathExtractor
from extraction.ocr import OCREngine
from extraction.structure import EducationalStructureTagger
from extraction.tables import TableExtractor
from extraction.text import NativeTextExtractor
from ingestion.inspector import PageInspectionMetrics
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


class EscalationRouter:
    def __init__(
        self,
        text_extractor: Optional[NativeTextExtractor] = None,
        layout_analyzer: Optional[LayoutAnalyzer] = None,
        ocr_engine: Optional[OCREngine] = None,
        table_extractor: Optional[TableExtractor] = None,
        math_extractor: Optional[MathExtractor] = None,
        figure_extractor: Optional[FigureExtractor] = None,
        structure_tagger: Optional[EducationalStructureTagger] = None,
    ):
        self.text_extractor = text_extractor or NativeTextExtractor()
        self.layout_analyzer = layout_analyzer or LayoutAnalyzer()
        self.ocr_engine = ocr_engine or OCREngine()
        self.table_extractor = table_extractor or TableExtractor()
        self.math_extractor = math_extractor or MathExtractor()
        self.figure_extractor = figure_extractor or FigureExtractor()
        self.structure_tagger = structure_tagger or EducationalStructureTagger()

    def route_and_extract_page(
        self,
        page: fitz.Page,
        page_idx: int,
        metrics: PageInspectionMetrics,
        pdf_path: str,
        document_id: str,
        body_font_size: float = 10.0,
    ) -> Tuple[List[DocumentBlock], List[DocumentAsset]]:
        """
        Executes progressive routing based on page_type metrics:
        - blank: Return empty list
        - native/hybrid: Rung 1 (Native) -> Rung 2 (Layout) -> Table/Math/Figure -> Structure Tagging
        - scanned/garbled: Rung 3 (Tesseract OCR) -> Table/Math/Figure -> Structure Tagging
        """
        if metrics.page_type == "blank":
            return [], []

        page_width, page_height = metrics.width, metrics.height
        extracted_blocks: List[DocumentBlock] = []
        page_assets: List[DocumentAsset] = []

        # RUNG 1 vs RUNG 3 Routing Decision
        if metrics.page_type in ("native", "hybrid"):
            # Rung 1: Native Text Extraction
            extracted_blocks = self.text_extractor.extract_page_blocks(
                page, page_width=page_width, page_height=page_height, rotation=metrics.rotation_applied
            )
        else: # "scanned" or "garbled"
            # Rung 3: Tesseract OCR Engine Override
            extracted_blocks = self.ocr_engine.process_scanned_page(
                page, page_width=page_width, page_height=page_height
            )

        # Rung 2: Layout Analysis & Reading Order Sorting
        if extracted_blocks:
            extracted_blocks = self.layout_analyzer.analyze_page_layout(
                extracted_blocks, page_width=page_width, page_height=page_height, body_font_size=body_font_size
            )

        # Specialized Tool 1: Table Extractor
        tbl_blocks, tbl_assets = self.table_extractor.extract_page_tables(
            pdf_path=pdf_path,
            page_index=page_idx,
            fitz_page=page,
            page_width=page_width,
            page_height=page_height,
            document_id=document_id,
        )
        if tbl_blocks:
            extracted_blocks.extend(tbl_blocks)
            page_assets.extend(tbl_assets)

        # Specialized Tool 2: Math Extractor
        extracted_blocks, math_assets = self.math_extractor.process_math_blocks(
            extracted_blocks, page, page_idx, page_width, page_height, document_id
        )
        page_assets.extend(math_assets)

        # Specialized Tool 3: Figure Extractor & Caption Association
        fig_assets, extracted_blocks = self.figure_extractor.extract_page_figures_and_diagrams(
            page, page_idx, page_width, page_height, document_id, extracted_blocks
        )
        page_assets.extend(fig_assets)

        # Educational Structure Tagging
        extracted_blocks = self.structure_tagger.tag_page_structures(extracted_blocks, page_height)

        # Re-sort final blocks into reading order
        extracted_blocks = self.layout_analyzer._sort_reading_order(extracted_blocks, page_width)
        for idx, block in enumerate(extracted_blocks, start=1):
            block.reading_order = idx

        return extracted_blocks, page_assets
