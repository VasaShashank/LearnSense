"""
OCR Processing Engine and FastText Language Detector for Taproot Phase 1.
Processes scanned page renders at 300 DPI, executes Tesseract OCR, detects Hindi/English languages,
and tags low-confidence blocks with LOW_OCR_CONFIDENCE warnings.
Matches Section 12 & Section 16 of TAPROOT_PHASE_1_MASTER_IMPLEMENTATION_PLAN.md.
"""

from typing import Dict, Any, List, Optional
import fitz  # PyMuPDF
from adapters.tesseract_adapter import TesseractOCRAdapter
from ingestion.coordinate import CoordinateNormalizer
from schemas.document import (
    BlockContent,
    BlockStatusEnum,
    BlockTypeEnum,
    DocumentBlock,
    EngineInfo,
    ExtractionMethodEnum,
)


class OCREngine:
    def __init__(
        self,
        ocr_adapter: Optional[TesseractOCRAdapter] = None,
        confidence_threshold: float = 0.60,
    ):
        self.ocr_adapter = ocr_adapter or TesseractOCRAdapter()
        self.confidence_threshold = confidence_threshold

    def process_scanned_page(
        self,
        page: fitz.Page,
        page_width: float,
        page_height: float,
        target_dpi: int = 300,
        languages: Optional[List[str]] = None,
    ) -> List[DocumentBlock]:
        """
        Renders target scanned page at 300 DPI, runs Tesseract OCR, applies language detection,
        normalizes bounding boxes to 72 DPI top-left points space, and attaches low-confidence warnings.
        """
        # Render high-res 300 DPI image for OCR
        dpi_scale = target_dpi / 72.0
        mat = fitz.Matrix(dpi_scale, dpi_scale)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img_bytes = pix.tobytes("png")

        ocr_results = self.ocr_adapter.ocr_image(img_bytes, languages=languages)

        if not ocr_results:
            # Fallback block if OCR returns empty or fails
            return [
                DocumentBlock(
                    block_id="blk_ocr_0001",
                    type=BlockTypeEnum.PARAGRAPH,
                    role="body",
                    bbox=[0.0, 0.0, page_width, page_height],
                    content=BlockContent(text="", text_raw=""),
                    extraction_method=ExtractionMethodEnum.OCR,
                    engine=EngineInfo(name="TesseractOCR", version="5.0"),
                    confidence=0.0,
                    status=BlockStatusEnum.FAILED,
                    warnings=["LOW_OCR_CONFIDENCE"],
                )
            ]

        # Group OCR word bounding boxes into block paragraphs
        blocks = self._group_ocr_results_into_blocks(ocr_results, dpi_scale, page_width, page_height)
        return blocks

    def detect_block_language(self, text: str) -> str:
        """
        Detects block language: 'hi' for Devanagari Unicode range (U+0900-U+097F),
        'en' for Latin script, or 'hi+en' for mixed bilingual content.
        """
        if not text:
            return "en"

        has_devanagari = any("\u0900" <= c <= "\u097f" for c in text)
        has_latin = any("a" <= c.lower() <= "z" for c in text)

        if has_devanagari and has_latin:
            return "hi+en"
        elif has_devanagari:
            return "hi"
        return "en"

    def _group_ocr_results_into_blocks(
        self,
        ocr_results: List[Dict[str, Any]],
        dpi_scale: float,
        page_width: float,
        page_height: float,
    ) -> List[DocumentBlock]:
        blocks: List[DocumentBlock] = []
        block_counter = 1

        # Group words by vertical line position (within 10px on 300DPI)
        sorted_results = sorted(ocr_results, key=lambda r: (r["bbox"][1], r["bbox"][0]))
        current_lines: List[List[Dict[str, Any]]] = []

        for item in sorted_results:
            if not current_lines:
                current_lines.append([item])
                continue

            last_line = current_lines[-1]
            last_y = last_line[0]["bbox"][1]

            if abs(item["bbox"][1] - last_y) < (15 * dpi_scale):
                last_line.append(item)
            else:
                current_lines.append([item])

        # Group adjacent lines into paragraph blocks
        current_block_words: List[Dict[str, Any]] = []

        for line in current_lines:
            if not current_block_words:
                current_block_words.extend(line)
            else:
                last_y2 = max(w["bbox"][3] for w in current_block_words)
                line_y1 = min(w["bbox"][1] for w in line)

                # Line gap threshold
                if line_y1 - last_y2 < (25 * dpi_scale):
                    current_block_words.extend(line)
                else:
                    block = self._create_block_from_words(current_block_words, block_counter, dpi_scale, page_width, page_height)
                    blocks.append(block)
                    block_counter += 1
                    current_block_words = list(line)

        if current_block_words:
            block = self._create_block_from_words(current_block_words, block_counter, dpi_scale, page_width, page_height)
            blocks.append(block)

        return blocks

    def _create_block_from_words(
        self,
        words: List[Dict[str, Any]],
        block_idx: int,
        dpi_scale: float,
        page_width: float,
        page_height: float,
    ) -> DocumentBlock:
        full_text = " ".join([w["text"] for w in words])
        avg_conf = sum(w["confidence"] for w in words) / len(words) if words else 0.0

        # Scale 300DPI bounding box back to 72DPI points space
        x0 = min(w["bbox"][0] for w in words) / dpi_scale
        y0 = min(w["bbox"][1] for w in words) / dpi_scale
        x1 = max(w["bbox"][2] for w in words) / dpi_scale
        y1 = max(w["bbox"][3] for w in words) / dpi_scale

        canonical_bbox = CoordinateNormalizer.normalize_bbox([x0, y0, x1, y1], page_width, page_height)
        lang = self.detect_block_language(full_text)

        status = BlockStatusEnum.OK if avg_conf >= self.confidence_threshold else BlockStatusEnum.OK_LOW_CONFIDENCE
        warnings = [] if avg_conf >= self.confidence_threshold else ["LOW_OCR_CONFIDENCE"]

        return DocumentBlock(
            block_id=f"blk_ocr_{block_idx:04d}",
            type=BlockTypeEnum.PARAGRAPH,
            role="body",
            bbox=canonical_bbox,
            content=BlockContent(text=full_text, text_raw=full_text),
            language=lang,
            reading_order=block_idx,
            extraction_method=ExtractionMethodEnum.OCR,
            engine=EngineInfo(name="TesseractOCR", version="5.0"),
            confidence=round(avg_conf, 2),
            status=status,
            warnings=warnings,
        )
