"""
Phase 2 Mock LLM Adapter for tests only.

This module must NEVER be imported from production code (§2 #12).
Moved out of phase2/adapters/nlp_adapters.py per no-fallback policy.
"""

from typing import Any, Dict, Optional
from phase2.adapters.nlp_adapters import RecordReplayCache


class MockLLMAdapter:
    """Test-only LLM double for Phase 2 contracts."""

    def __init__(self, model_name: str = "mock-gpt-4o", cache_dir: Optional[str] = None):
        self.model_name = model_name
        self.cache = RecordReplayCache(cache_dir or ".cache/llm_replay")

    def generate_json_response(
        self, prompt: str, schema_template: Dict[str, Any], config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        cfg = config or {"temperature": 0.0}
        cached = self.cache.get(prompt, self.model_name, cfg)
        if cached:
            return cached
        response = schema_template.copy()
        self.cache.set(prompt, self.model_name, cfg, response)
        return response
