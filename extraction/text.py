"""
Native Text & Metadata Extractor for Taproot Phase 1.
Extracts native PDF text layers using PyMuPDF (fitz), performing Unicode normalization (NFC),
ligature replacement, subscript/superscript detection, and line-end hyphenation rejoining.
Matches Section 11 of TAPROOT_PHASE_1_MASTER_IMPLEMENTATION_PLAN.md.
"""

import re
import unicodedata
from typing import Any, Dict, List, Tuple, Optional
import fitz  # PyMuPDF
from ingestion.coordinate import CoordinateNormalizer
from schemas.document import BlockContent, BlockTypeEnum, DocumentBlock, ExtractionMethodEnum, EngineInfo


class NativeTextExtractor:
    # Common Unicode ligature replacements
    LIGATURE_MAP = {
        "ﬁ": "fi",
        "ﬂ": "fl",
        "æ": "ae",
        "œ": "oe",
        "ﬀ": "ff",
        "ﬃ": "ffi",
        "ﬄ": "ffl",
        "ﬅ": "st",
        "ﬆ": "st",
    }

    def __init__(self, engine_name: str = "PyMuPDFNative", engine_version: str = fitz.VersionFitz):
        self.engine_name = engine_name
        self.engine_version = engine_version

    def extract_page_blocks(
        self,
        page: fitz.Page,
        page_width: float,
        page_height: float,
        rotation: int = 0,
    ) -> List[DocumentBlock]:
        """
        Extracts native text blocks from a PyMuPDF page, performing span analysis,
        script detection, Unicode normalization, and coordinate standardization.
        """
        text_page = page.get_text("dict", flags=fitz.TEXT_PRESERVE_LIGATURES | fitz.TEXT_PRESERVE_WHITESPACE)
        raw_blocks = text_page.get("blocks", [])

        extracted_blocks: List[DocumentBlock] = []
        block_counter = 1

        for raw_block in raw_blocks:
            # Block type 0 = text, 1 = image
            if raw_block.get("type") != 0:
                continue

            lines = raw_block.get("lines", [])
            if not lines:
                continue

            full_text_raw = ""
            full_text_normalized = ""
            block_spans_meta = []

            for line in lines:
                line_text_raw = ""
                line_text_norm = ""
                spans = line.get("spans", [])

                for span in spans:
                    span_text = span.get("text", "")
                    font_flags = span.get("flags", 0)
                    font_size = span.get("size", 10.0)

                    # Detect Superscript / Subscript font flags (bit 0 = superscript, bit 1 = subscript)
                    is_superscript = bool(font_flags & (1 << 0))
                    is_subscript = bool(font_flags & (1 << 1))

                    norm_span_text = self.normalize_text(span_text)

                    line_text_raw += span_text
                    line_text_norm += norm_span_text

                    block_spans_meta.append({
                        "font": span.get("font", ""),
                        "size": font_size,
                        "color": span.get("color", 0),
                        "is_superscript": is_superscript,
                        "is_subscript": is_subscript,
                    })

                full_text_raw += line_text_raw + "\n"
                full_text_normalized += line_text_norm + "\n"

            # Rejoin line hyphens
            full_text_normalized = self.rejoin_hyphenated_words(full_text_normalized.strip())
            full_text_raw = full_text_raw.strip()

            if not full_text_normalized:
                continue

            # Standardize coordinates
            raw_bbox = raw_block.get("bbox", [0, 0, page_width, page_height])
            canonical_bbox = CoordinateNormalizer.fitz_rect_to_canonical(
                raw_bbox, page_width, page_height, rotation=rotation
            )

            doc_block = DocumentBlock(
                block_id=f"blk_nat_{block_counter:04d}",
                type=BlockTypeEnum.PARAGRAPH,  # Default to paragraph; layout builder refines to heading/list/etc.
                role="body",
                bbox=canonical_bbox,
                content=BlockContent(
                    text=full_text_normalized,
                    text_raw=full_text_raw,
                    structured_data={"spans": block_spans_meta},
                ),
                reading_order=block_counter,
                extraction_method=ExtractionMethodEnum.NATIVE,
                engine=EngineInfo(name=self.engine_name, version=self.engine_version),
                confidence=1.0,
            )

            extracted_blocks.append(doc_block)
            block_counter += 1

        return extracted_blocks

    @classmethod
    def normalize_text(cls, text: str) -> str:
        """Applies Unicode NFC normalization and replaces ligatures."""
        if not text:
            return ""

        # Replace Unicode ligatures
        for lig, replacement in cls.LIGATURE_MAP.items():
            text = text.replace(lig, replacement)

        # Unicode NFC Normalization
        text = unicodedata.normalize("NFC", text)
        return text

    @staticmethod
    def rejoin_hyphenated_words(text: str) -> str:
        """
        Rejoins words split across line breaks with hyphens.
        e.g., 'ac-\nceleration' -> 'acceleration'.
        """
        if not text:
            return ""

        # Regex for end-of-line hyphens on word boundaries
        pattern = r"(\b[a-zA-Z]{2,})-\n([a-zA-Z]{2,}\b)"
        return re.sub(pattern, r"\1\2", text)
