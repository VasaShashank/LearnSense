"""
LLM Adapter Abstraction for Phase 3.
Supports environment variables and .env file loading for GROQ_API_KEY / OPENAI_API_KEY.
Performs live structured JSON generation when an API key is available, falling back
gracefully to deterministic schema-based mock adapter when no key is configured or on network error.
"""

import json
import os
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, Optional, Protocol
from phase2.adapters.nlp_adapters import MockLLMAdapter as Phase2MockLLMAdapter, RecordReplayCache


def load_env_file(dotenv_path: str = ".env") -> None:
    """Simple helper to load .env file key-values into os.environ if present."""
    p = Path(dotenv_path)
    if p.exists():
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if key and key not in os.environ:
                        os.environ[key] = val


class BaseLLMAdapter(Protocol):
    def generate_json_response(
        self, prompt: str, schema_template: Dict[str, Any], config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]: ...


class Phase3LLMAdapter:
    """LLM Adapter for Phase 3 question and quiz generation with Groq / OpenAI live API & Mock fallback."""

    def __init__(self, model_name: Optional[str] = None, cache_dir: Optional[str] = None):
        load_env_file()
        self.groq_api_key = os.environ.get("GROQ_API_KEY")
        self.openai_api_key = os.environ.get("OPENAI_API_KEY")

        if model_name:
            self.model_name = model_name
        elif self.groq_api_key:
            self.model_name = "llama-3.3-70b-versatile"
        elif self.openai_api_key:
            self.model_name = "gpt-4o-mini"
        else:
            self.model_name = "mock-gpt-4o"

        self.cache = RecordReplayCache(cache_dir or ".cache/llm_replay")
        self._mock_adapter = Phase2MockLLMAdapter(model_name=self.model_name, cache_dir=cache_dir)

    def _call_live_api(
        self, prompt: str, schema_template: Dict[str, Any], config: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Attempts live HTTP request to Groq or OpenAI API if API key is present."""
        if self.groq_api_key:
            url = "https://api.groq.com/openai/v1/chat/completions"
            api_key = self.groq_api_key
        elif self.openai_api_key:
            url = "https://api.openai.com/v1/chat/completions"
            api_key = self.openai_api_key
        else:
            return None

        system_prompt = (
            "You are an educational content generation AI. You MUST reply ONLY with valid JSON "
            "matching the following JSON structure template:\n" + json.dumps(schema_template, indent=2)
        )

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": config.get("temperature", 0.2),
        }

        try:
            req = urllib.request.Request(
                url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                content_str = res_data["choices"][0]["message"]["content"]
                return json.loads(content_str)
        except Exception:
            # Fallback on network timeout, invalid key, or API rate limit
            return None

    def generate_json(
        self, prompt: str, schema_template: Dict[str, Any], config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Generates a structured JSON response grounded in prompt context."""
        cfg = config or {"temperature": 0.2}

        # Check replay cache first
        cached = self.cache.get(prompt, self.model_name, cfg)
        if cached:
            return cached

        # Attempt live API call if key exists
        live_res = self._call_live_api(prompt, schema_template, cfg)
        if live_res:
            self.cache.set(prompt, self.model_name, cfg, live_res)
            return live_res

        # Fallback to mock generation
        res = self._mock_adapter.generate_json_response(prompt, schema_template, cfg)
        return res
