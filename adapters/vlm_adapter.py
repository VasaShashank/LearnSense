"""
VLM (Vision-Language Model) Adapter for LearnSense Document Intelligence.

Provides a modular, provider-agnostic abstraction for selective visual document
understanding (diagrams, complex charts, handwritten text, multi-column flows).

Operating Modes:
- "disabled": Never invokes VLM. Pure CPU-friendly traditional OCR/native path.
- "auto": Conservative production mode. Escalates to VLM only when page complexity
          or OCR quality degradation warrants multimodal visual extraction.
- "always": Research/testing mode. Always attempts VLM extraction.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("LearnSense.VLMAdapter")

_PLACEHOLDER_KEYS = {
    "",
    "your_groq_api_key_here",
    "your_openai_api_key_here",
    "your_vlm_api_key_here",
    "your_api_key_here",
    "none",
    "null",
    "changeme",
    "todo",
}


def _clean_key(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    val = raw.strip().strip("'\"")
    if val.lower() in _PLACEHOLDER_KEYS or val.lower().startswith("your_"):
        return None
    return val


@dataclass
class VLMTelemetry:
    """Telemetry counters for document ingestion observability."""
    total_pages: int = 0
    native_pages: int = 0
    ocr_pages: int = 0
    vlm_pages: int = 0
    vlm_failures: int = 0
    vlm_fallbacks: int = 0
    vlm_calls: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    processing_time_sec: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_pages": self.total_pages,
            "native_pages": self.native_pages,
            "ocr_pages": self.ocr_pages,
            "vlm_pages": self.vlm_pages,
            "vlm_percentage": round((self.vlm_pages / max(1, self.total_pages)) * 100, 1),
            "vlm_failures": self.vlm_failures,
            "vlm_fallbacks": self.vlm_fallbacks,
            "vlm_calls": self.vlm_calls,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "processing_time_sec": round(self.processing_time_sec, 3),
        }


class VLMCache:
    """Stable page content hash cache for VLM responses."""

    def __init__(self, cache_file: Optional[Path] = None):
        self._memory_cache: Dict[str, Dict[str, Any]] = {}
        self.cache_file = cache_file

    def compute_key(self, image_bytes: bytes, model: str, prompt_hint: str = "") -> str:
        h = hashlib.sha256(image_bytes).hexdigest()[:24]
        p_hash = hashlib.sha256(prompt_hint.encode("utf-8")).hexdigest()[:8]
        return f"{h}_{model}_{p_hash}"

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        return self._memory_cache.get(key)

    def set(self, key: str, data: Dict[str, Any]) -> None:
        self._memory_cache[key] = data


class VLMAdapter:
    """Base abstract interface for Vision-Language Model adapters."""

    def __init__(
        self,
        mode: str = "auto",
        model: Optional[str] = None,
        cache: Optional[VLMCache] = None,
        telemetry: Optional[VLMTelemetry] = None,
    ):
        self.mode = mode.lower()
        self.model = model or "default"
        self.cache = cache or VLMCache()
        self.telemetry = telemetry or VLMTelemetry()

    @property
    def is_enabled(self) -> bool:
        return self.mode in ("auto", "always")

    def extract_visual_blocks(
        self,
        image_bytes: bytes,
        page_index: int,
        page_width: float,
        page_height: float,
        context_hint: str = "",
    ) -> List[Dict[str, Any]]:
        """
        Extract structured visual blocks (diagrams, tables, flowcharts, handwritten notes)
        from a rendered page image.
        """
        raise NotImplementedError


class MockVLMAdapter(VLMAdapter):
    """Deterministic, offline test double for VLM extraction."""

    def __init__(
        self,
        mode: str = "auto",
        model: str = "mock-vision-v1",
        cache: Optional[VLMCache] = None,
        telemetry: Optional[VLMTelemetry] = None,
    ):
        super().__init__(mode=mode, model=model, cache=cache, telemetry=telemetry)

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


class LiveVLMAdapter(VLMAdapter):
    """
    Live Vision-Language Model adapter supporting Groq Vision, OpenAI, or OpenAI-compatible endpoints.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        provider: str = "groq",
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        mode: str = "auto",
        timeout_sec: float = 30.0,
        cache: Optional[VLMCache] = None,
        telemetry: Optional[VLMTelemetry] = None,
    ):
        super().__init__(mode=mode, model=model or ("llama-3.2-11b-vision-preview" if provider == "groq" else "gpt-4o-mini"), cache=cache, telemetry=telemetry)
        self.api_key = _clean_key(api_key) or _clean_key(os.environ.get("VLM_API_KEY")) or _clean_key(os.environ.get("GROQ_API_KEY")) or _clean_key(os.environ.get("OPENAI_API_KEY"))
        self.provider = provider.lower()
        self.timeout_sec = timeout_sec

        if base_url:
            self.endpoint = base_url.rstrip("/") + "/chat/completions"
        elif self.provider == "groq":
            self.endpoint = "https://api.groq.com/openai/v1/chat/completions"
        else:
            self.endpoint = "https://api.openai.com/v1/chat/completions"

    @property
    def has_credentials(self) -> bool:
        return bool(self.api_key)

    def extract_visual_blocks(
        self,
        image_bytes: bytes,
        page_index: int,
        page_width: float,
        page_height: float,
        context_hint: str = "",
    ) -> List[Dict[str, Any]]:
        if not self.has_credentials:
            raise ValueError("VLM API key is not configured or is a placeholder.")

        self.telemetry.vlm_calls += 1
        cache_key = self.cache.compute_key(image_bytes, self.model, context_hint)
        cached = self.cache.get(cache_key)
        if cached is not None:
            self.telemetry.cache_hits += 1
            return cached.get("blocks", [])

        self.telemetry.cache_misses += 1

        # Encode image to base64
        b64_img = base64.b64encode(image_bytes).decode("ascii")
        data_uri = f"data:image/png;base64,{b64_img}"

        system_prompt = (
            "You are a specialized document intelligence Vision Model for an educational system. "
            "Analyze the uploaded page image and extract structured content blocks. "
            "For every visual element (diagram, table, heading, paragraph, equation, handwritten note), "
            "provide: type (heading, paragraph, figure, table, equation, list_item), role, estimated bbox in points "
            "[x0, y0, x1, y1] where page bounds are width="
            f"{page_width:.1f}, height={page_height:.1f}, text content, and confidence (0.0 to 1.0).\n"
            "Return ONLY a JSON object with schema:\n"
            "{\n"
            '  "blocks": [\n'
            "    {\n"
            '      "type": "heading|paragraph|figure|table|equation|list_item",\n'
            '      "role": "title|body|caption|diagram_explanation",\n'
            '      "bbox": [x0, y0, x1, y1],\n'
            '      "text": "exact extracted text or semantic diagram description",\n'
            '      "confidence": 0.95\n'
            "    }\n"
            "  ]\n"
            "}"
        )

        user_content = [
            {"type": "text", "text": f"Extract structured blocks from this page image (Page {page_index + 1}). Context: {context_hint}"},
            {"type": "image_url", "image_url": {"url": data_uri, "detail": "high"}},
        ]

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
            "max_tokens": 1500,
        }

        req_data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "LearnSense-VLM/2026.09",
        }

        req = urllib.request.Request(self.endpoint, data=req_data, headers=headers, method="POST")

        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                resp_bytes = resp.read()
                data = json.loads(resp_bytes.decode("utf-8"))
                content_str = data["choices"][0]["message"]["content"]
                parsed = json.loads(content_str)
                blocks = parsed.get("blocks", [])
                self.cache.set(cache_key, {"blocks": blocks})
                return blocks
        except Exception as exc:
            logger.warning("VLM live request failed: %s", exc)
            raise
        finally:
            self.telemetry.processing_time_sec += (time.time() - t0)


# Global singleton registry
_GLOBAL_VLM_ADAPTER: Optional[VLMAdapter] = None
_GLOBAL_TELEMETRY = VLMTelemetry()


def get_vlm_adapter(force_reload: bool = False) -> VLMAdapter:
    """
    Factory resolving VLM Adapter based on environment variables:
    VLM_MODE: 'disabled' | 'auto' | 'always' (default: 'auto')
    LLM_MODE / VLM_PROVIDER: 'mock' -> MockVLMAdapter, else LiveVLMAdapter
    """
    global _GLOBAL_VLM_ADAPTER
    if _GLOBAL_VLM_ADAPTER is not None and not force_reload:
        return _GLOBAL_VLM_ADAPTER

    vlm_mode = os.environ.get("VLM_MODE", "auto").strip().lower()
    llm_mode = os.environ.get("LLM_MODE", "").strip().lower()

    if llm_mode == "mock" or os.environ.get("VLM_PROVIDER", "").lower() == "mock":
        _GLOBAL_VLM_ADAPTER = MockVLMAdapter(mode=vlm_mode, telemetry=_GLOBAL_TELEMETRY)
    else:
        # Check if live keys are present
        groq_key = _clean_key(os.environ.get("GROQ_API_KEY")) or _clean_key(os.environ.get("VLM_API_KEY"))
        openai_key = _clean_key(os.environ.get("OPENAI_API_KEY"))
        if groq_key:
            _GLOBAL_VLM_ADAPTER = LiveVLMAdapter(
                api_key=groq_key,
                provider="groq",
                model=os.environ.get("VLM_MODEL", "llama-3.2-11b-vision-preview"),
                mode=vlm_mode,
                telemetry=_GLOBAL_TELEMETRY,
            )
        elif openai_key:
            _GLOBAL_VLM_ADAPTER = LiveVLMAdapter(
                api_key=openai_key,
                provider="openai",
                model=os.environ.get("VLM_MODEL", "gpt-4o-mini"),
                mode=vlm_mode,
                telemetry=_GLOBAL_TELEMETRY,
            )
        else:
            # Fallback to mock adapter when no live keys are configured
            _GLOBAL_VLM_ADAPTER = MockVLMAdapter(mode=vlm_mode, telemetry=_GLOBAL_TELEMETRY)

    return _GLOBAL_VLM_ADAPTER


def get_vlm_telemetry() -> VLMTelemetry:
    return _GLOBAL_TELEMETRY
