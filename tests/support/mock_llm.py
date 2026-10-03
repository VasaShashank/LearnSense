"""
Isolated test/development LLM double.

This module is TEST INFRASTRUCTURE. It is reachable from the production adapter only
when the environment explicitly sets ``LLM_MODE=mock`` (see
:mod:`phase3.adapters.llm_adapter`). It is never selected implicitly because a key is
missing or a live call failed.

Unlike the legacy mock, this double produces *schema-shaped but semantically real*
payloads derived from the prompt, so that pipeline wiring can be exercised without a
network call. It never emits the raw template strings.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Optional


def _seed(prompt: str) -> int:
    return int(hashlib.sha256(prompt.encode("utf-8")).hexdigest(), 16)


def _pick(prompt: str, options: List[str], salt: int = 0) -> str:
    return options[(_seed(prompt) + salt) % len(options)]


def _numeric_value(prompt: str) -> float:
    return round((_seed(prompt) % 900) / 10.0 + 0.5, 2)


class MockLLMAdapter:
    """Deterministic, prompt-aware JSON/text generator for offline test runs."""

    def __init__(
        self,
        model_name: str = "mock-gpt-4o",
        cache_dir: Optional[str] = None,
        schema_template: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.model_name = model_name
        self.cache_dir = cache_dir
        self.schema_template = schema_template or {}
        self.calls: List[str] = []

    @property
    def is_mock(self) -> bool:
        return True

    @property
    def is_live(self) -> bool:
        return False

    @property
    def mode(self) -> str:
        return "mock"

    @property
    def provider(self) -> str:
        return "mock"

    def has_credentials(self) -> bool:
        return True

    def health(self) -> Dict[str, Any]:
        return {
            "mode": "mock",
            "provider": "mock",
            "model": self.model_name,
            "has_credentials": True,
        }

    # -- public API ---------------------------------------------------------

    def generate_json(
        self,
        prompt: str,
        schema_template: Dict[str, Any],
        config: Optional[Dict[str, Any]] = None,
        validate: bool = True,
    ) -> Dict[str, Any]:
        return self.generate_json_response(prompt, schema_template, config)

    def generate_text(
        self,
        prompt: str,
        *,
        system_prompt: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> str:
        return self.generate_text_response(prompt)

    def generate_json_response(
        self,
        prompt: str,
        schema_template: Dict[str, Any],
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        self.calls.append(prompt)
        return self._render(prompt, schema_template, config)

    def generate_text_response(self, prompt: str) -> str:
        self.calls.append(prompt)
        return (
            f"[mock] {prompt.strip()[:400]}\n"
            f"(deterministic offline response from tests.support.mock_llm)"
        )

    # -- rendering ----------------------------------------------------------

    def _render(
        self,
        prompt: str,
        schema: Any,
        config: Optional[Dict[str, Any]] = None,
        salt: int = 0,
        field: str = "",
    ) -> Any:
        expected = self._kind(schema)

        if expected == "dict":
            assert isinstance(schema, dict)
            out: Dict[str, Any] = {}
            for key, sub in schema.items():
                out[key] = self._render(prompt, sub, config, salt, field=key)
            return out

        if expected == "list":
            assert isinstance(schema, list)
            item_schema = schema[0] if schema else "string"
            # Length is decided by the FIELD name, never by stringifying the item schema
            # (a dictified item used to contain the substring "options" and collapsed the
            # question list to a single element).
            field_low = field.lower()
            if field_low in ("options", "choices", "alternatives"):
                count = max(2, len(schema))
                # Option salt is the option index ONLY. Deriving it from the parent's
                # salt meant the "correct answer" text (which is keyed to salt 0) was
                # absent from the options of every question after the first.
                return [
                    self._render(prompt, item_schema, config, i, field=field)
                    for i in range(count)
                ]
            count = self._requested_count(prompt, config)
            return [
                self._render(prompt, item_schema, config, salt * 100 + i, field=field)
                for i in range(count)
            ]

        # Scalar schema: the value MUST be a scalar. Returning a list here produced
        # nested option lists that failed downstream Pydantic validation.
        hint = str(schema)
        field_low = field.lower()
        combined = f"{field_low} {hint.lower()}"

        if field_low in ("difficulty", "probability", "confidence", "mastery"):
            return 0.5
        if field_low in ("question_type", "type", "item_type"):
            return "mcq"
        if field_low in ("correct_answer", "answer", "solution"):
            return self._correct_answer(prompt, self._last_key_name(prompt))
        if field_low in ("evidence_refs", "evidence_ref", "citations", "citation_refs", "refs") or "evidence" in combined or "citation" in combined or "ref" in combined:
            return f"E{(salt % 2) + 1}"

        # Numeric-looking placeholders in the schema must yield real numbers.
        if not field_low and ("float" in hint.lower() or "number" in hint.lower() or hint.strip().lstrip("-.").replace(".", "", 1).isdigit()):
            return _numeric_value(prompt + str(salt))

        key = self._last_key_name(prompt)

        if "option" in combined or "choice" in combined or "distractor" in combined:
            return self._distractor(prompt, key, salt)
        if "exact match" in hint.lower():
            return self._correct_answer(prompt, key)
        if "explanation" in combined or "rationale" in combined:
            return (
                f"In the supplied source material, {key} is characterised by {salt} "
                f"defining behaviours that determine how it responds to the stated conditions."
            )
        if "question" in combined or "prompt" in combined or "ask" in combined:
            p_words = self._extract_passage_words(prompt)
            pw_str = " ".join(p_words[:8]) if p_words else key
            return (
                f"According to the source material regarding {pw_str}, which statement is correct "
                f"for condition set {salt + 1}?"
            )
        if "title" in combined or "name" in combined or "heading" in combined:
            return key if not salt else f"{key} ({salt + 1})"
        if "statement" in combined or "definition" in combined:
            return f"Explain how {key} applies to the given conditions (case {salt + 1})."
        if salt:
            return f"{key} (detail {salt}) as derived from the source material."
        return f"{key} derived from the source material."

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _extract_passage_words(prompt: str) -> List[str]:
        ignore = {
            "below", "passages", "taken", "learner", "material", "write", "questions",
            "concept", "answerable", "using", "only", "above", "rules", "every", "must",
            "outside", "knowledge", "invent", "facts", "examples", "formulas", "absent",
            "give", "exactly", "options", "correct", "explanation", "difficulty", "string",
            "statement", "which", "about", "condition", "derived", "source", "supplied",
            "characterised", "defining", "behaviours", "determine", "responds", "stated",
            "conditions", "page", "section", "cite", "labels", "relies", "quote", "paraphrase",
            "cited", "passage", "add", "claims", "typical", "match", "mcq", "true", "false"
        }
        words: List[str] = []
        for w in re.findall(r"[a-zA-Z]{4,}", prompt):
            if w.lower() not in ignore:
                words.append(w)
        return list(dict.fromkeys(words))

    @staticmethod
    def _requested_count(prompt: str, config: Optional[Dict[str, Any]]) -> int:
        """
        Honour an explicit count in the prompt ("Generate 6 questions", "exactly 5 items").

        Prompts are the contract between caller and generator, so reading the requested
        count back out keeps the double usable by tests that assert on item counts.
        """
        override = (config or {}).get("mock_list_size")
        if override:
            return int(override)
        match = re.search(
            r"(?:generate|produce|create|write|return|exactly)\s+(\d{1,3})",
            prompt,
            re.IGNORECASE,
        )
        if match:
            value = int(match.group(1))
            if 0 < value <= 50:
                return value
        return 3

    @staticmethod
    def _kind(schema: Any) -> str:
        if isinstance(schema, dict):
            return "dict"
        if isinstance(schema, list):
            return "list"
        return "string"

    @staticmethod
    def _last_key_name(prompt: str) -> str:
        for marker in ("CONCEPT:", "TOPIC:", "SUBJECT:", "CONCEPT_NAME:"):
            if marker in prompt:
                tail = prompt.split(marker, 1)[1]
                return tail.splitlines()[0].strip()[:60] or "the concept"
        return "the concept"

    _DISTRACTORS = (
        "increases monotonically with the measured quantity",
        "decreases monotonically with the measured quantity",
        "is independent of the measured quantity",
        "is undefined for the given conditions",
        "remains constant under every valid configuration",
        "is determined solely by the ordering of the inputs",
    )

    def _distractor(self, prompt: str, key: str, salt: int) -> str:
        """Deterministic, distinct option text. The first option is always correct."""
        p_words = self._extract_passage_words(prompt)
        pw_str = " ".join(p_words[:6]) if p_words else key
        if salt == 0:
            return f"{pw_str} increases monotonically with the measured quantity"
        return f"{pw_str} {self._DISTRACTORS[salt % len(self._DISTRACTORS)]}"

    def _correct_answer(self, prompt: str, key: str) -> str:
        p_words = self._extract_passage_words(prompt)
        pw_str = " ".join(p_words[:6]) if p_words else key
        return f"{pw_str} increases monotonically with the measured quantity"


class ScriptedLLM:
    """
    LLM double that returns pre-canned payloads and records every call.

    Used where a test needs to assert *why* a generation was accepted or rejected -
    for example that a question citing no evidence is dropped. ``MockLLMAdapter``
    cannot express that, because it always invents plausible-looking content.
    """

    def __init__(self, *payloads: Dict[str, Any]) -> None:
        self._payloads = list(payloads)
        self.prompts: List[str] = []
        self.templates: List[Dict[str, Any]] = []

    @property
    def call_count(self) -> int:
        return len(self.prompts)

    def generate_json(self, prompt: str, template: Dict[str, Any]) -> Dict[str, Any]:
        self.prompts.append(prompt)
        self.templates.append(template)
        if not self._payloads:
            return {"questions": []}
        if len(self._payloads) == 1:
            return self._payloads[0]
        return self._payloads.pop(0)

    def generate_text(self, prompt: str, **kwargs: Any) -> str:
        self.prompts.append(prompt)
        return self._payloads.pop(0) if self._payloads else ""  # type: ignore[return-value]
