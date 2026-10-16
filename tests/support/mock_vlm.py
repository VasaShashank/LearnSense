"""
Mock VLM Adapter for tests only.

This module must NEVER be imported from production code. It is only reachable
via the test harness (LEARNSENSE_TEST_HARNESS=1 or PYTEST_CURRENT_TEST set).
"""

from typing import Any, Dict, List, Optional

from adapters.vlm_adapter import VLMAdapter, VLMCache, VLMTelemetry


class MockVLMAdapter(VLMAdapter):
    """Deterministic, offline test double for VLM extraction."""

    def __init__(
        self,
        mode: str = "auto",
        model: str = "mock-vision-v1",
        cache: Optional[VLMCache] = None,
        telemetry: Optional[VLMTelemetry] = None,
    ):
        super().__init__(mode=mode, model=model, provider="mock", cache=cache, telemetry=telemetry)

    def extract_visual_blocks(
        self,
        image_bytes: bytes,
        page_index: int,
        page_width: float,
        page_height: float,
        context_hint: str = "",
    ) -> List[Dict[str, Any]]:
        self.telemetry.vlm_calls += 1
        cache_key = self.cache.compute_key(image_bytes, self.model, context_hint)
        cached = self.cache.get(cache_key)
        if cached is not None:
            self.telemetry.cache_hits += 1
            return cached.get("blocks", [])

        self.telemetry.cache_misses += 1

        # Simulate intelligent visual decomposition based on hints
        blocks = []
        if "diagram" in context_hint.lower() or "chart" in context_hint.lower() or "figure" in context_hint.lower():
            blocks.append({
                "type": "figure",
                "role": "diagram_interpretation",
                "bbox": [50.0, 100.0, page_width - 50.0, page_height * 0.45],
                "text": f"Visual Diagram on page {page_index + 1}: Conceptual relationship diagram showing system flow and interconnected state variables.",
                "confidence": 0.95,
                "metadata": {"visual_type": "diagram", "elements_detected": ["node_A", "node_B", "directional_arrow"]},
            })
            blocks.append({
                "type": "paragraph",
                "role": "diagram_caption",
                "bbox": [50.0, page_height * 0.46, page_width - 50.0, page_height * 0.55],
                "text": "Figure Explanation: Nodes illustrate state transitions governed by foundational boundary invariants.",
                "confidence": 0.92,
            })
        elif "handwritten" in context_hint.lower():
            blocks.append({
                "type": "paragraph",
                "role": "handwritten_transcription",
                "bbox": [40.0, 80.0, page_width - 40.0, page_height * 0.60],
                "text": "Transcribed handwritten notes: Review Chapter 4 fundamental theorems before applying dynamic recurrence relation.",
                "confidence": 0.88,
                "metadata": {"is_handwritten": True},
            })
        else:
            # Generic visual block decomposition
            blocks.append({
                "type": "heading",
                "role": "section_header",
                "bbox": [50.0, 50.0, page_width - 50.0, 90.0],
                "text": f"Visual Section Header (Page {page_index + 1})",
                "confidence": 0.96,
            })
            blocks.append({
                "type": "paragraph",
                "role": "body",
                "bbox": [50.0, 100.0, page_width - 50.0, page_height * 0.50],
                "text": "Multimodal visual synthesis: Content structured with verified spatial hierarchy and semantic relationship preservation.",
                "confidence": 0.94,
            })

        self.cache.set(cache_key, {"blocks": blocks})
        return blocks
