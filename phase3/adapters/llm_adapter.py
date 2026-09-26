"""
LLM Adapter Abstraction for Phase 3.
Reuses and extends Phase 2 Record/Replay cache mechanisms.
Provides Mock and Pluggable LLM interfaces.
"""

import json
from typing import Any, Dict, Optional, Protocol
from phase2.adapters.nlp_adapters import MockLLMAdapter as Phase2MockLLMAdapter, RecordReplayCache


class BaseLLMAdapter(Protocol):
    def generate_json_response(
        self, prompt: str, schema_template: Dict[str, Any], config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]: ...


class Phase3LLMAdapter:
    """LLM Adapter for Phase 3 question and quiz generation."""

    def __init__(self, model_name: str = "mock-gpt-4o", cache_dir: Optional[str] = None):
        self.model_name = model_name
        self.cache = RecordReplayCache(cache_dir or ".cache/llm_replay")
        self._mock_adapter = Phase2MockLLMAdapter(model_name=model_name, cache_dir=cache_dir)

    def generate_json(
        self, prompt: str, schema_template: Dict[str, Any], config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Generates a structured JSON response grounded in prompt context."""
        cfg = config or {"temperature": 0.2}
        cached = self.cache.get(prompt, self.model_name, cfg)
        if cached:
            return cached

        # Fallback to mock generation if not explicitly cached
        res = self._mock_adapter.generate_json_response(prompt, schema_template, cfg)
        return res
