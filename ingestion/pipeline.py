"""
Pipeline Coordinator for Taproot Phase 1 Ingestion.
Coordinates Validation, Escalation Routing (Native/OCR/Tables/Math/Figures/Structure),
Security Sandboxing, and Pass B Aggregation.
Matches Section 10 of TAPROOT_PHASE_1_MASTER_IMPLEMENTATION_PLAN.md.
"""

from typing import Dict, Any, List, Optional
import fitz  # PyMuPDF
from ingestion.inspector import PageInspector
from ingestion.pass_b import PassBAggregator
from ingestion.router import EscalationRouter
from ingestion.validator import PDFValidator
from schemas.document import (
    DocumentAsset,
    DocumentPage,
    DocumentWarning,
    PageOrientationEnum,
    PageStatusEnum,
    PageTypeEnum,
    SourceMetadata,
    StructuredDocument,
)
from security.sandbox import SecuritySandbox
from storage.db import DatabaseManager
from storage.store import DocumentStorage


class IngestionPipeline:
    def __init__(
        self,
        storage: Optional[DocumentStorage] = None,
        db: Optional[DatabaseManager] = None,
        validator: Optional[PDFValidator] = None,
        inspector: Optional[PageInspector] = None,
        router: Optional[EscalationRouter] = None,
        sandbox: Optional[SecuritySandbox] = None,
        pass_b_aggregator: Optional[PassBAggregator] = None,
    ):
        self.storage = storage or DocumentStorage()
        self.db = db or DatabaseManager()
        self.validator = validator or PDFValidator()
        self.inspector = inspector or PageInspector()
        self.router = router or EscalationRouter()
        self.sandbox = sandbox or SecuritySandbox()
        self.pass_b_aggregator = pass_b_aggregator or PassBAggregator()

    def process_pdf_bytes(
        self,
        pdf_bytes: bytes,
        filename: str,
        document_id: Optional[str] = None,
    ) -> StructuredDocument:
        size_bytes = len(pdf_bytes)
        sha256 = DocumentStorage.compute_sha256(pdf_bytes)
        doc_id = document_id or f"doc_{sha256[:12]}"

        # 1. Store Original File & Initialize Job
        pdf_path = self.storage.save_original_pdf(doc_id, pdf_bytes)
        self.db.create_document_job(
            document_id=doc_id,
            sha256=sha256,
            filename=filename,
            size_bytes=size_bytes,
            cache_key=sha256,
            status="validating",
        )

        # 2. PDF Validation & Repair
        val_res = self.validator.validate_and_repair(pdf_bytes, filename=filename)
        if not val_res.is_valid:
            self.db.update_document_status(doc_id, "failed")
            raise ValueError(f"PDF Validation failed: {val_res.message}")

        if val_res.repaired_pdf_bytes:
            pdf_bytes = val_res.repaired_pdf_bytes
            pdf_path = self.storage.save_original_pdf(doc_id, pdf_bytes)

        source_meta = SourceMetadata(sha256=sha256, filename=filename, size_bytes=size_bytes)
        self.db.update_document_status(doc_id, "analyzing", page_count=val_res.page_count)

        # 3. Open PyMuPDF Document
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        total_pages = len(doc)
        pdf_toc = doc.get_toc()  # [(level, title, page_num)]

        # 4. Pass A: Per-Page Extraction via Escalation Router & Security Sandbox
        self.db.update_document_status(doc_id, "extracting", page_count=total_pages, processed_pages=0)
        extracted_pages: List[DocumentPage] = []
        document_assets: List[DocumentAsset] = []
        raw_page_blocks_list: List[List] = []

        # Calculate document body font size mode across pages for layout analysis
        for page_idx in range(total_pages):
            raw_page_blocks_list.append(
                self.router.text_extractor.extract_page_blocks(
                    doc[page_idx], page_width=doc[page_idx].rect.width, page_height=doc[page_idx].rect.height
                )
            )
        body_font_size = self.router.layout_analyzer.calculate_document_body_font_size(raw_page_blocks_list)

        for page_idx in range(total_pages):
            page = doc[page_idx]

            # Cheap Page Inspection
            metrics = self.inspector.inspect_page(page, page_idx)
            self.storage.save_page_preview(doc_id, page_idx, metrics.preview_png_bytes)

            # Route and extract page via Escalation Router (Native/OCR/Tables/Math/Figures/Structure)
            blocks, assets = self.router.route_and_extract_page(
                page=page,
                page_idx=page_idx,
                metrics=metrics,
                pdf_path=str(pdf_path),
                document_id=doc_id,
                body_font_size=body_font_size,
            )

            # Save extracted assets
            for asset in assets:
                document_assets.append(asset)

            # Security Inspection
            for block in blocks:
                sec_warnings = self.sandbox.inspect_block_security(
                    block, page_index=page_idx, page_width=metrics.width, page_height=metrics.height
                )
                for w in sec_warnings:
                    self.db.add_warning(doc_id, w.code.value, w.severity.value, w.message, page_index=page_idx, block_id=block.block_id)

            orientation = PageOrientationEnum.LANDSCAPE if metrics.orientation == "landscape" else PageOrientationEnum.PORTRAIT
            page_type = PageTypeEnum(metrics.page_type) if metrics.page_type in PageTypeEnum.__members__.values() else PageTypeEnum.NATIVE

            page_obj = DocumentPage(
                page_index=page_idx,
                page_label=str(page_idx + 1),
                width=metrics.width,
                height=metrics.height,
                orientation=orientation,
                rotation_applied=metrics.rotation_applied,
                page_type=page_type,
                status=PageStatusEnum.OK if metrics.page_type != "blank" else PageStatusEnum.EMPTY,
                blocks=blocks,
            )
            extracted_pages.append(page_obj)
            self.db.set_page_state(doc_id, page_idx, page_obj.page_label, page_obj.page_type.value, page_obj.status.value)
            self.db.update_document_status(doc_id, "extracting", processed_pages=page_idx + 1)

        # 5. Pass B: Document Aggregation & Section Tree Building
        self.db.update_document_status(doc_id, "aggregating")
        structured_doc = self.pass_b_aggregator.process_document(
            document_id=doc_id,
            source_meta=source_meta,
            pages=extracted_pages,
            pdf_outline_toc=pdf_toc if pdf_toc else None,
        )

        # Attach extracted assets to StructuredDocument
        structured_doc.assets = document_assets

        # Add validator warnings if any
        for w in val_res.warnings:
            self.db.add_warning(doc_id, w["code"], w["severity"], w["message"])

        # Collect warnings from DB into StructuredDocument
        db_warnings = self.db.get_warnings(doc_id)
        if db_warnings:
            doc_warnings = [
                DocumentWarning(
                    code=w["code"],
                    severity=w["severity"],
                    page_index=w["page_index"],
                    block_id=w["block_id"],
                    message=w["message"],
                )
                for w in db_warnings
            ]
            structured_doc.warnings = doc_warnings

        # 6. Persist Structured Document Output & Update Final DB Status
        self.storage.save_structured_document(doc_id, structured_doc)
        self.db.update_document_status(doc_id, structured_doc.metadata.processing_status.value)

        doc.close()
        return structured_doc
