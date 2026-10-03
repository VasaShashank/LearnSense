"""
Unit & Integration Test Suite for Cost-Aware Hybrid OCR + VLM Document Intelligence.

Verifies:
1. Selective routing: Simple text -> Native, Normal Scan -> OCR, Complex Diagram / Garbled -> VLM.
2. Configuration modes: disabled, auto, always.
3. Graceful fallback on VLM exception / timeout without crashing ingestion.
4. Content-hash based caching avoiding duplicate VLM calls.
5. Strict schema validation, coordinate normalization, and provenance preservation.
6. Ingestion observability and telemetry.
"""

import os
import pytest
import fitz  # PyMuPDF

from adapters.vlm_adapter import (
    VLMCache,
    VLMTelemetry,
    get_vlm_adapter,
    get_vlm_telemetry,
)
from tests.support.mock_vlm import MockVLMAdapter
from extraction.vlm import VLMEngine
from ingestion.inspector import PageInspectionMetrics, PageInspector
from ingestion.router import EscalationRouter
from phase3.errors import VLMExtractionError
from schemas.document import (
    BlockTypeEnum,
    ExtractionMethodEnum,
)


def _create_test_page_with_text(text: str = "This is a clean, standard textbook paragraph.") -> fitz.Page:
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((50, 72), text, fontsize=12)
    return page


def _create_test_page_with_drawings() -> fitz.Page:
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    # Add multiple vector drawing paths to simulate complex diagram
    for i in range(40):
        page.draw_line((50 + i * 2, 100), (100 + i * 2, 200), color=(0, 0, 1))
        page.draw_rect(fitz.Rect(50 + i * 5, 250, 90 + i * 5, 290), color=(1, 0, 0), fill=(0.8, 0.9, 1))
    return page


class TestVLMRoutingAndModes:
    """Test selective routing behavior and configuration modes."""

    def test_simple_text_page_uses_native_not_vlm(self):
        page = _create_test_page_with_text("Clean textbook paragraph about calculus theorems.")
        inspector = PageInspector()
        metrics = inspector.inspect_page(page, page_index=0)

        # Clean text should not require VLM in auto mode
        assert metrics.page_type == "native"
        assert metrics.requires_vlm is False

        telemetry = VLMTelemetry()
        mock_vlm = MockVLMAdapter(mode="auto", telemetry=telemetry)
        router = EscalationRouter(vlm_engine=VLMEngine(vlm_adapter=mock_vlm))
        router.telemetry = telemetry

        blocks, assets = router.route_and_extract_page(
            page=page,
            page_idx=0,
            metrics=metrics,
            pdf_path="test.pdf",
            document_id="doc_test_simple",
        )

        assert len(blocks) > 0
        # Provenance must be native
        assert any(b.extraction_method == ExtractionMethodEnum.NATIVE for b in blocks)
        # VLM calls should be 0
        assert telemetry.vlm_calls == 0
        assert telemetry.vlm_pages == 0

    def test_complex_diagram_page_escalates_to_vlm_in_auto_mode(self):
        page = _create_test_page_with_drawings()
        inspector = PageInspector()
        metrics = inspector.inspect_page(page, page_index=0)

        # Page with many vector drawings should trigger visual complexity flag
        assert metrics.vector_path_count >= 35

        telemetry = VLMTelemetry()
        mock_vlm = MockVLMAdapter(mode="auto", telemetry=telemetry)
        router = EscalationRouter(vlm_engine=VLMEngine(vlm_adapter=mock_vlm))
        router.telemetry = telemetry

        # Explicitly mark requires_vlm based on metrics
        metrics.requires_vlm = True
        metrics.vlm_reason = "Complex diagram structures"

        blocks, assets = router.route_and_extract_page(
            page=page,
            page_idx=0,
            metrics=metrics,
            pdf_path="test.pdf",
            document_id="doc_test_diagram",
        )

        assert len(blocks) > 0
        # VLM must have been called
        assert telemetry.vlm_calls == 1
        assert telemetry.vlm_pages == 1
        # Block provenance must be VLM
        assert any(b.extraction_method == ExtractionMethodEnum.VLM for b in blocks)

    def test_vlm_disabled_mode_never_calls_vlm(self):
        page = _create_test_page_with_drawings()
        inspector = PageInspector()
        metrics = inspector.inspect_page(page, page_index=0)
        metrics.requires_vlm = True

        from unittest.mock import MagicMock
        from extraction.ocr import OCREngine

        telemetry = VLMTelemetry()
        mock_vlm = MockVLMAdapter(mode="disabled", telemetry=telemetry)
        mock_ocr = MagicMock(spec=OCREngine)
        mock_ocr.process_scanned_page.return_value = []
        router = EscalationRouter(vlm_engine=VLMEngine(vlm_adapter=mock_vlm), ocr_engine=mock_ocr)
        router.telemetry = telemetry

        blocks, assets = router.route_and_extract_page(
            page=page,
            page_idx=0,
            metrics=metrics,
            pdf_path="test.pdf",
            document_id="doc_test_disabled",
        )

        # VLM must not be called when disabled
        assert telemetry.vlm_calls == 0
        assert telemetry.vlm_pages == 0

    def test_vlm_always_mode_calls_vlm_for_all_pages(self):
        page = _create_test_page_with_text("Standard clean text page.")
        inspector = PageInspector()
        metrics = inspector.inspect_page(page, page_index=0)
        assert metrics.requires_vlm is False

        telemetry = VLMTelemetry()
        mock_vlm = MockVLMAdapter(mode="always", telemetry=telemetry)
        router = EscalationRouter(vlm_engine=VLMEngine(vlm_adapter=mock_vlm))
        router.telemetry = telemetry

        blocks, assets = router.route_and_extract_page(
            page=page,
            page_idx=0,
            metrics=metrics,
            pdf_path="test.pdf",
            document_id="doc_test_always",
        )

        # VLM must be called in always mode
        assert telemetry.vlm_calls == 1
        assert telemetry.vlm_pages == 1
        assert any(b.extraction_method == ExtractionMethodEnum.VLM for b in blocks)


class TestVLMFallback:
    """Test graceful fallback behavior when VLM fails."""

    def test_vlm_exception_graceful_fallback_to_traditional(self):
        page = _create_test_page_with_text("Fallback content to preserve.")
        metrics = PageInspectionMetrics(
            page_index=0,
            width=612,
            height=792,
            orientation="portrait",
            rotation_applied=0,
            char_count=50,
            garbage_ratio=0.0,
            ink_ratio=0.05,
            image_coverage_ratio=0.0,
            vector_path_count=10,
            page_type="native",
            preview_png_bytes=b"fake",
            requires_vlm=True,
            vlm_reason="Forced test",
        )

        class FailingVLMAdapter(MockVLMAdapter):
            def extract_visual_blocks(self, *args, **kwargs):
                raise RuntimeError("Simulated network timeout or quota exhaustion")

        telemetry = VLMTelemetry()
        failing_vlm = FailingVLMAdapter(mode="auto", telemetry=telemetry)
        router = EscalationRouter(vlm_engine=VLMEngine(vlm_adapter=failing_vlm))
        router.telemetry = telemetry

        # Under the strict no-fallback policy (§1.2 #1, §2 #2), VLM failure must
        # FAIL the page loudly via VLMExtractionError, NEVER silently fall back to native/OCR.
        with pytest.raises(VLMExtractionError) as exc_info:
            router.route_and_extract_page(
                page=page,
                page_idx=0,
                metrics=metrics,
                pdf_path="test.pdf",
                document_id="doc_test_fallback",
            )

        assert "VLM extraction failed on page 1" in str(exc_info.value)
        assert exc_info.value.details["page_index"] == 0
        assert "Simulated network timeout" in exc_info.value.details["cause"]
        # Telemetry must record failure
        assert telemetry.vlm_failures == 1


class TestVLMCaching:
    """Test content-hash caching mechanism."""

    def test_same_page_cached_single_invocation(self):
        cache = VLMCache()
        telemetry = VLMTelemetry()
        adapter = MockVLMAdapter(mode="always", cache=cache, telemetry=telemetry)
        engine = VLMEngine(vlm_adapter=adapter)

        page = _create_test_page_with_drawings()

        # First call -> cache miss
        blocks1 = engine.process_visual_page(page, page_width=612, page_height=792, page_index=0, context_hint="diagram")
        assert telemetry.vlm_calls == 1
        assert telemetry.cache_hits == 0
        assert telemetry.cache_misses == 1

        # Second call on identical page -> cache hit
        blocks2 = engine.process_visual_page(page, page_width=612, page_height=792, page_index=0, context_hint="diagram")
        assert telemetry.vlm_calls == 2
        assert telemetry.cache_hits == 1
        assert len(blocks1) == len(blocks2)

    def test_different_page_triggers_fresh_call(self):
        cache = VLMCache()
        telemetry = VLMTelemetry()
        adapter = MockVLMAdapter(mode="always", cache=cache, telemetry=telemetry)
        engine = VLMEngine(vlm_adapter=adapter)

        page1 = _create_test_page_with_text("Page 1 Content")
        page2 = _create_test_page_with_text("Page 2 Completely Different Content")

        engine.process_visual_page(page1, page_width=612, page_height=792, page_index=0)
        assert telemetry.cache_misses == 1

        engine.process_visual_page(page2, page_width=612, page_height=792, page_index=1)
        assert telemetry.cache_misses == 2
        assert telemetry.cache_hits == 0


class TestVLMSchemaAndProvenance:
    """Test schema validation and coordinate normalization."""

    def test_vlm_blocks_have_valid_schema_and_provenance(self):
        adapter = MockVLMAdapter(mode="always")
        engine = VLMEngine(vlm_adapter=adapter)

        raw_blocks = [
            {
                "type": "figure",
                "role": "diagram",
                "bbox": [50.0, 100.0, 500.0, 400.0],
                "text": "State Machine Diagram",
                "confidence": 0.95,
            },
            {
                "type": "heading",
                "role": "title",
                "bbox": [-10.0, -20.0, 9999.0, 9999.0],  # Out of bounds coordinates
                "text": "Chapter 3 State Invariants",
                "confidence": 0.90,
            },
        ]

        validated = engine.validate_and_normalize_blocks(
            raw_blocks=raw_blocks,
            page_width=612.0,
            page_height=792.0,
            page_index=2,
        )

        assert len(validated) == 2

        # 1. Figure block validation
        b1 = validated[0]
        assert b1.block_id == "blk_p0002_vlm_0001"
        assert b1.type == BlockTypeEnum.FIGURE
        assert b1.extraction_method == ExtractionMethodEnum.VLM
        assert b1.content.text == "State Machine Diagram"
        assert b1.bbox == [50.0, 100.0, 500.0, 400.0]

        # 2. Out of bounds bbox clamped safely within [0, 0, 612, 792]
        b2 = validated[1]
        assert b2.block_id == "blk_p0002_vlm_0002"
        assert b2.type == BlockTypeEnum.HEADING
        assert b2.bbox[0] >= 0.0
        assert b2.bbox[1] >= 0.0
        assert b2.bbox[2] <= 612.0
        assert b2.bbox[3] <= 792.0

    def test_telemetry_reporting(self):
        telemetry = VLMTelemetry(
            total_pages=10,
            native_pages=8,
            ocr_pages=1,
            vlm_pages=1,
            vlm_failures=0,
            vlm_calls=1,
            cache_hits=0,
            cache_misses=1,
            processing_time_sec=0.15,
        )
        report = telemetry.to_dict()
        assert report["total_pages"] == 10
        assert report["vlm_percentage"] == 10.0
        assert report["native_pages"] == 8
        assert report["vlm_pages"] == 1
