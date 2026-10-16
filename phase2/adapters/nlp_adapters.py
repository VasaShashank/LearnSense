"""
NLP Adapter Framework & Record/Replay Cache.
Provides Tier 0-1 deterministic baseline adapters and an optional Tier 2 Mock LLM adapter.
"""

import hashlib
import json
import os
from typing import Any, Dict, List, Optional, Protocol


class RecordReplayCache:
    def __init__(self, cache_dir: str = ".cache/llm_replay"):
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)

    def _compute_hash(self, prompt: str, model: str, config: Dict[str, Any]) -> str:
        key = json.dumps({"prompt": prompt, "model": model, "config": config}, sort_keys=True)
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def get(self, prompt: str, model: str, config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        h = self._compute_hash(prompt, model, config)
        filepath = os.path.join(self.cache_dir, f"{h}.json")
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    def set(self, prompt: str, model: str, config: Dict[str, Any], response: Dict[str, Any]) -> None:
        h = self._compute_hash(prompt, model, config)
        filepath = os.path.join(self.cache_dir, f"{h}.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(response, f, indent=2)


class BaseNLPAdapter(Protocol):
    def extract_keywords(self, text: str) -> List[str]: ...
    def classify_text_role(self, text: str) -> str: ...
    def compute_embedding(self, text: str) -> List[float]: ...


class Tier01DeterministicAdapter:
    """Deterministic Tier 0-1 rules and lightweight ML mock adapter."""

    def __init__(self):
        self.engine_name = "tier01_rule_engine"
        self.engine_version = "1.0.0"

    def extract_keywords(self, text: str) -> List[str]:
        words = [w.strip(".,!?:;()[]{}") for w in text.split()]
        # Simple heuristic: capitalized words and terms > 3 chars
        keywords = []
        for w in words:
            if len(w) > 3 and (w[0].isupper() or len(w) > 6):
                keywords.append(w)
        return list(dict.fromkeys(keywords))

    def classify_text_role(self, text: str) -> str:
        t = text.lower().strip()
        if t.startswith("definition") or "is defined as" in t or "refers to" in t:
            return "definition"
        if t.startswith("example") or "for example" in t:
            return "example"
        if t.startswith("theorem"):
            return "theorem"
        if "exercise" in t or t.startswith("q") or "question" in t:
            return "exercise"
        if "objective" in t or "able to" in t:
            return "learning_objective"
        if "prerequisite" in t or "before studying" in t:
            return "prerequisite_statement"
        return "explanation"

    def compute_embedding(self, text: str) -> List[float]:
        # Deterministic 8-dim dummy vector derived from hash
        h = hashlib.md5(text.encode("utf-8")).digest()
        return [b / 255.0 for b in h[:8]]

