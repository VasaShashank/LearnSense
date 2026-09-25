"""
Stage 1 — Input Validation and Normalization.
Converts StructuredDocument into a normalized working representation for Phase 2 without mutating Phase 1 content.
Plan §4.
"""

import re
import unicodedata
from typing import Any, Dict, List
from schemas.document import StructuredDocument, BlockTypeEnum
from phase2.models import WarningMessage


class NormalizedDocumentContext:
    def __init__(self, doc: StructuredDocument):
        self.doc = doc
        self.doc_id = doc.document_id
        self.semantic_blocks: List[Dict[str, Any]] = []
        self.block_weight_map: Dict[str, float] = {}
        self.normalized_keys_map: Dict[str, str] = {}
        self.warnings: List[WarningMessage] = []

        self._process()

    def _process(self):
        for page in self.doc.pages:
            for block in page.blocks:
                # Role based weighting (§4)
                included = True
                exclusion_reason = None
                weight = 1.0

                role = (block.role or "").lower()
                btype = block.type

                if btype in (BlockTypeEnum.PAGE_NUMBER, BlockTypeEnum.HEADER, BlockTypeEnum.FOOTER, BlockTypeEnum.WATERMARK):
                    included = False
                    exclusion_reason = "boilerplate_page_element"
                    weight = 0.0
                elif role in ("bibliography", "boilerplate"):
                    included = False
                    exclusion_reason = "bibliography_or_boilerplate"
                    weight = 0.0
                elif role == "glossary":
                    weight = 1.5  # Strong definition evidence
                elif btype in (BlockTypeEnum.TOC_ENTRY, BlockTypeEnum.INDEX_ENTRY):
                    weight = 0.1  # Low weight for extraction
                elif role in ("exercises", "answer_keys"):
                    weight = 1.0

                norm_key = self.normalize_text_key(block.content.text)

                self.block_weight_map[block.block_id] = weight
                self.normalized_keys_map[block.block_id] = norm_key

                self.semantic_blocks.append({
                    "block_id": block.block_id,
                    "type": block.type.value if hasattr(block.type, "value") else str(block.type),
                    "role": block.role,
                    "section_id": block.section_id,
                    "text": block.content.text,
                    "text_raw": block.content.text_raw,
                    "confidence": block.confidence,
                    "language": block.language,
                    "weight": weight,
                    "included_in_semantic_flow": included,
                    "exclusion_reason": exclusion_reason
                })

    @staticmethod
    def normalize_text_key(text: str) -> str:
        """Case-folded, Unicode NFKC, punctuation-stripped matching key."""
        nfkc = unicodedata.normalize("NFKC", text or "")
        case_folded = nfkc.lower()
        cleaned = re.sub(r"[^\w\s]", "", case_folded)
        return " ".join(cleaned.split())


def run_stage1_normalize(doc: StructuredDocument) -> NormalizedDocumentContext:
    return NormalizedDocumentContext(doc)
