"""
VLM (Vision-Language Model) Adapter for LearnSense Document Intelligence.

NO-FALLBACK POLICY (§1.2):
  - When VLM_MODE is "auto" or "always", VLM_PROVIDER and VLM_MODEL must be
    explicitly configured. Missing or invalid configuration is a startup error.
  - MockVLMAdapter has been moved to tests/support/mock_vlm.py. Production code
    must not import from tests/.
  - VLM_PROVIDER=mock and LLM_MODE=mock are rejected at startup unless
    LEARNSENSE_TEST_HARNESS=1 is set.

Operating Modes:
  - "disabled": Never invokes VLM. Status endpoint reports DISABLED_BY_CONFIG.
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

from phase3.errors import VLMConfigurationError, VLMExtractionError

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


def _is_test_harness() -> bool:
    """Return True only when running under the test harness."""
    return (
        os.environ.get("LEARNSENSE_TEST_HARNESS", "").strip() == "1"
        or os.environ.get("PYTEST_CURRENT_TEST", "") != ""
    )


@dataclass
class VLMTelemetry:
    """Telemetry counters for document ingestion observability."""
    total_pages: int = 0
    native_pages: int = 0
    ocr_pages: int = 0
    vlm_pages: int = 0
    vlm_failures: int = 0
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
            "vlm_calls": self.vlm_calls,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "processing_time_sec": round(self.processing_time_sec, 3),
        }


class VLMCache:
    """Stable page content hash cache for VLM responses (in-memory only)."""

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
        provider: Optional[str] = None,
        cache: Optional[VLMCache] = None,
        telemetry: Optional[VLMTelemetry] = None,
    ):
        self.mode = mode.lower()
        self.model = model
        self.provider = provider
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


class DisabledVLMAdapter(VLMAdapter):
    """Adapter returned when VLM_MODE=disabled. All calls raise."""

    def __init__(self, telemetry: Optional[VLMTelemetry] = None):
        super().__init__(mode="disabled", model=None, provider=None, telemetry=telemetry)

    def extract_visual_blocks(
        self,
        image_bytes: bytes,
        page_index: int,
        page_width: float,
        page_height: float,
        context_hint: str = "",
    ) -> List[Dict[str, Any]]:
        raise VLMConfigurationError(
            "VLM is disabled by configuration (VLM_MODE=disabled). "
            "Set VLM_MODE=auto or VLM_MODE=always with a valid VLM_PROVIDER and VLM_MODEL.",
        )


class LiveVLMAdapter(VLMAdapter):
    """
    Live Vision-Language Model adapter supporting Groq Vision, OpenAI, or OpenAI-compatible endpoints.
    """

    def __init__(
        self,
        api_key: str,
        provider: str,
        model: str,
        base_url: Optional[str] = None,
        mode: str = "auto",
        timeout_sec: float = 30.0,
        cache: Optional[VLMCache] = None,
        telemetry: Optional[VLMTelemetry] = None,
    ):
        super().__init__(mode=mode, model=model, provider=provider, cache=cache, telemetry=telemetry)
        self.api_key = api_key
        self.timeout_sec = timeout_sec

        if base_url:
            self.endpoint = base_url.rstrip("/") + "/chat/completions"
        elif self.provider == "groq":
            self.endpoint = "https://api.groq.com/openai/v1/chat/completions"
        elif self.provider == "openai":
            self.endpoint = "https://api.openai.com/v1/chat/completions"
        else:
            raise VLMConfigurationError(
                f"Unknown VLM_PROVIDER '{self.provider}'. Must be 'groq' or 'openai'.",
            )

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
            raise VLMConfigurationError("VLM API key is not configured or is a placeholder.")

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
            logger.error(
                "VLM extraction failed for page %d (provider=%s, model=%s): %s",
                page_index, self.provider, self.model, exc,
            )
            raise VLMExtractionError(
                f"VLM extraction failed for page {page_index}: {exc}",
                details={"provider": self.provider, "model": self.model, "page_index": page_index},
            ) from exc
        finally:
            self.telemetry.processing_time_sec += (time.time() - t0)


# Global singleton registry
_GLOBAL_VLM_ADAPTER: Optional[VLMAdapter] = None
_GLOBAL_TELEMETRY = VLMTelemetry()


def get_vlm_adapter(force_reload: bool = False) -> VLMAdapter:
    """
    Factory resolving VLM Adapter based on environment variables.

    NO-FALLBACK POLICY:
      - VLM_MODE must be one of: disabled, auto, always.
      - When VLM_MODE != disabled, VLM_PROVIDER and VLM_MODEL are required.
      - VLM_PROVIDER=mock is rejected unless LEARNSENSE_TEST_HARNESS=1.
      - No provider inference from API keys. Provider must be explicit.
    """
    global _GLOBAL_VLM_ADAPTER
    if _GLOBAL_VLM_ADAPTER is not None and not force_reload:
        return _GLOBAL_VLM_ADAPTER

    vlm_mode = os.environ.get("VLM_MODE", "disabled").strip().lower()

    if vlm_mode not in ("disabled", "auto", "always"):
        raise VLMConfigurationError(
            f"Invalid VLM_MODE='{vlm_mode}'. Must be 'disabled', 'auto', or 'always'.",
        )

    # Reject mock in production
    vlm_provider_raw = os.environ.get("VLM_PROVIDER", "").strip().lower()
    llm_mode_raw = os.environ.get("LLM_MODE", "").strip().lower()
    if (vlm_provider_raw == "mock" or llm_mode_raw == "mock") and not _is_test_harness():
        raise VLMConfigurationError(
            "VLM_PROVIDER=mock / LLM_MODE=mock is not allowed outside the test harness. "
            "Set LEARNSENSE_TEST_HARNESS=1 or PYTEST_CURRENT_TEST to use mock adapters.",
        )

    if vlm_mode == "disabled":
        _GLOBAL_VLM_ADAPTER = DisabledVLMAdapter(telemetry=_GLOBAL_TELEMETRY)
        return _GLOBAL_VLM_ADAPTER

    # VLM_MODE is auto or always — require explicit provider and model
    vlm_provider = vlm_provider_raw
    vlm_model = os.environ.get("VLM_MODEL", "").strip()

    if not vlm_provider:
        raise VLMConfigurationError(
            "VLM_PROVIDER is required when VLM_MODE is not 'disabled'. "
            "Set VLM_PROVIDER=groq or VLM_PROVIDER=openai.",
        )

    if not vlm_model:
        raise VLMConfigurationError(
            "VLM_MODEL is required when VLM_MODE is not 'disabled'. "
            "Set VLM_MODEL to a vision-capable model name.",
        )

    # Handle test harness mock
    if vlm_provider == "mock":
        if not _is_test_harness():
            raise VLMConfigurationError(
                "VLM_PROVIDER='mock' is only permitted when running under the test harness "
                "(LEARNSENSE_TEST_HARNESS=1 or PYTEST_CURRENT_TEST set)."
            )
        if _GLOBAL_VLM_ADAPTER is not None:
            return _GLOBAL_VLM_ADAPTER
        raise VLMConfigurationError(
            "VLM_PROVIDER='mock' requested in test harness but no test adapter was registered. "
            "Call set_vlm_adapter(MockVLMAdapter(...)) from the test fixture."
        )

    # Resolve API key for the explicit provider
    if vlm_provider == "groq":
        api_key = _clean_key(os.environ.get("VLM_API_KEY")) or _clean_key(os.environ.get("GROQ_API_KEY"))
    elif vlm_provider == "openai":
        api_key = _clean_key(os.environ.get("VLM_API_KEY")) or _clean_key(os.environ.get("OPENAI_API_KEY"))
    else:
        raise VLMConfigurationError(
            f"Unknown VLM_PROVIDER='{vlm_provider}'. Must be 'groq' or 'openai'.",
        )

    if not api_key:
        raise VLMConfigurationError(
            f"No valid API key found for VLM_PROVIDER='{vlm_provider}'. "
            f"Set the appropriate API key environment variable.",
        )

    _GLOBAL_VLM_ADAPTER = LiveVLMAdapter(
        api_key=api_key,
        provider=vlm_provider,
        model=vlm_model,
        mode=vlm_mode,
        telemetry=_GLOBAL_TELEMETRY,
    )
    logger.info(
        "VLM adapter initialized: provider=%s, model=%s, mode=%s",
        vlm_provider, vlm_model, vlm_mode,
    )
    return _GLOBAL_VLM_ADAPTER


def get_vlm_telemetry() -> VLMTelemetry:
    return _GLOBAL_TELEMETRY


def reset_vlm_adapter() -> None:
    """Test hook: drop the cached adapter so new env values take effect."""
    global _GLOBAL_VLM_ADAPTER
    _GLOBAL_VLM_ADAPTER = None


def set_vlm_adapter(adapter: Optional[VLMAdapter]) -> None:
    """Test hook: inject a test adapter (e.g. MockVLMAdapter) during tests."""
    global _GLOBAL_VLM_ADAPTER
    _GLOBAL_VLM_ADAPTER = adapter
