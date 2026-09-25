"""
Canonical StructuredDocument Pydantic V2 Schema Specification for Taproot Phase 1.
Matches Section 25 of TAPROOT_PHASE_1_MASTER_IMPLEMENTATION_PLAN.md.
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ProcessingStatusEnum(str, Enum):
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"


class TitleSourceEnum(str, Enum):
    PDF_METADATA = "pdf_metadata"
    INFERRED = "inferred"
    USER = "user"


class PageOrientationEnum(str, Enum):
    PORTRAIT = "portrait"
    LANDSCAPE = "landscape"


class PageTypeEnum(str, Enum):
    NATIVE = "native"
    SCANNED = "scanned"
    HYBRID = "hybrid"
    BLANK = "blank"
    NEAR_BLANK = "near_blank"


class PageStatusEnum(str, Enum):
    PENDING = "pending"
    OK = "ok"
    OK_LOW_CONFIDENCE = "ok_low_confidence"
    EMPTY = "empty"
    FAILED = "failed"
    SKIPPED = "skipped"


class BlockTypeEnum(str, Enum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    TABLE = "table"
    EQUATION = "equation"
    FIGURE = "figure"
    CAPTION = "caption"
    FOOTNOTE = "footnote"
    CODE = "code"
    SIDEBAR = "sidebar"
    HEADER = "header"
    FOOTER = "footer"
    PAGE_NUMBER = "page_number"
    WATERMARK = "watermark"
    TOC_ENTRY = "toc_entry"
    INDEX_ENTRY = "index_entry"
    OTHER = "other"
    UNKNOWN = "unknown"


class ExtractionMethodEnum(str, Enum):
    NATIVE = "native"
    OCR = "ocr"
    TABLE_PARSER = "table_parser"
    MATH_PARSER = "math_parser"
    PRESERVED = "preserved"


class BlockStatusEnum(str, Enum):
    OK = "ok"
    OK_LOW_CONFIDENCE = "ok_low_confidence"
    PRESERVED_ONLY = "preserved_only"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"
    EMPTY = "empty"


class AssetTypeEnum(str, Enum):
    FIGURE = "figure"
    TABLE_CROP = "table_crop"
    EQUATION_CROP = "equation_crop"
    WATERMARK = "watermark"


class WarningSeverityEnum(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class WarningCodeEnum(str, Enum):
    LOW_OCR_CONFIDENCE = "LOW_OCR_CONFIDENCE"
    GARBLED_TEXT_LAYER = "GARBLED_TEXT_LAYER"
    UNSUPPORTED_LANGUAGE = "UNSUPPORTED_LANGUAGE"
    TABLE_RECONSTRUCTION_FAILED = "TABLE_RECONSTRUCTION_FAILED"
    TABLE_LOW_CONFIDENCE = "TABLE_LOW_CONFIDENCE"
    MATH_UNPARSED = "MATH_UNPARSED"
    PAGE_FAILED = "PAGE_FAILED"
    PAGE_TIMEOUT = "PAGE_TIMEOUT"
    HIDDEN_TEXT_DETECTED = "HIDDEN_TEXT_DETECTED"
    POSSIBLE_PROMPT_INJECTION = "POSSIBLE_PROMPT_INJECTION"
    HEADING_HIERARCHY_CONFLICT = "HEADING_HIERARCHY_CONFLICT"
    ROTATION_CORRECTED = "ROTATION_CORRECTED"
    DUPLICATE_PAGE_CANDIDATE = "DUPLICATE_PAGE_CANDIDATE"
    REPAIRED_PDF = "REPAIRED_PDF"
    RESOURCE_LIMIT_HIT = "RESOURCE_LIMIT_HIT"
    ENGINE_FALLBACK_USED = "ENGINE_FALLBACK_USED"
    OWNER_PASSWORD_RESTRICTED = "OWNER_PASSWORD_RESTRICTED"


# Supporting Models

class SourceMetadata(BaseModel):
    sha256: str
    filename: str
    size_bytes: int


class TitleMetadata(BaseModel):
    value: str
    source: TitleSourceEnum = TitleSourceEnum.INFERRED


class DocumentMetadata(BaseModel):
    page_count: int
    title: TitleMetadata
    processing_status: ProcessingStatusEnum


class SectionNode(BaseModel):
    section_id: str
    title: str
    level: int
    page_start: int
    children: List["SectionNode"] = Field(default_factory=list)


class EngineInfo(BaseModel):
    name: str
    version: str


class BlockContent(BaseModel):
    text: str
    text_raw: str
    structured_data: Optional[Dict[str, Any]] = None


class DocumentBlock(BaseModel):
    block_id: str
    type: BlockTypeEnum
    role: str
    bbox: List[float] = Field(..., min_length=4, max_length=4)
    content: BlockContent
    language: str = "en"
    reading_order: int
    section_id: Optional[str] = None
    extraction_method: ExtractionMethodEnum
    engine: Optional[EngineInfo] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    status: BlockStatusEnum = BlockStatusEnum.OK
    continues_from: Optional[str] = None
    continues_to: Optional[str] = None
    asset_ids: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class DocumentPage(BaseModel):
    page_index: int
    page_label: str
    width: float
    height: float
    orientation: PageOrientationEnum = PageOrientationEnum.PORTRAIT
    rotation_applied: int = 0
    page_type: PageTypeEnum = PageTypeEnum.NATIVE
    status: PageStatusEnum = PageStatusEnum.OK
    blocks: List[DocumentBlock] = Field(default_factory=list)


class DocumentAsset(BaseModel):
    asset_id: str
    type: AssetTypeEnum
    page_index: int
    bbox: List[float] = Field(..., min_length=4, max_length=4)
    uri: str
    sha256: str
    caption_block_id: Optional[str] = None
    is_decorative: bool = False


class DocumentWarning(BaseModel):
    code: WarningCodeEnum
    severity: WarningSeverityEnum = WarningSeverityEnum.MEDIUM
    page_index: Optional[int] = None
    block_id: Optional[str] = None
    message: str


class StructuredDocument(BaseModel):
    schema_version: str = "1.0.0"
    pipeline_version: str = "2026.09.0"
    document_id: str
    source: SourceMetadata
    metadata: DocumentMetadata
    outline: List[SectionNode] = Field(default_factory=list)
    pages: List[DocumentPage] = Field(default_factory=list)
    assets: List[DocumentAsset] = Field(default_factory=list)
    links: List[Dict[str, Any]] = Field(default_factory=list)
    annotations: List[Dict[str, Any]] = Field(default_factory=list)
    warnings: List[DocumentWarning] = Field(default_factory=list)


# Resolve recursive model reference for SectionNode
SectionNode.model_rebuild()
