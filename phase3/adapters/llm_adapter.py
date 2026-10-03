"""
LLM Adapter for the LearnSense learning runtime (Phase 3 + application layer).

Zero-fake production contract
-----------------------------
There is exactly one production LLM path. It either

  1. talks to a real provider (Groq / OpenAI / any OpenAI-compatible endpoint), or
  2. raises a typed :mod:`phase3.errors` exception.

It NEVER degrades to hardcoded questions, generic templates, schema echoes or mock
prose. A mock adapter exists *only* as an explicit, opt-in test double that is reachable
solely when ``LLM_MODE=mock`` is set. ``LLM_MODE`` is never inferred from a missing or
failing API key -- a missing key is a configuration error, not a licence to fake content.

Operational surface
-------------------
* ``Phase3LLMAdapter.mode``            -> ``"live"`` | ``"mock"``
* ``Phase3LLMAdapter.is_live``         -> bool
* ``Phase3LLMAdapter.generate_json()`` -> validated ``dict`` (raises on failure)
* ``Phase3LLMAdapter.generate_text()`` -> validated ``str``  (raises on failure)
"""

from __future__ import annotations

import json
import os
import random
import re
import socket
import ssl
import time
import urllib.error
import urllib.request
from http.client import BadStatusLine, IncompleteRead, RemoteDisconnected
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from phase3.errors import (
    LLMConfigurationError,
    LLMInvalidAPIKeyError,
    LLMOutputError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
    LLMProviderError,
)

# ---------------------------------------------------------------------------
# Environment loading
# ---------------------------------------------------------------------------


def load_env_file(dotenv_path: str = ".env") -> None:
    """Load ``.env`` key/values into ``os.environ`` without overwriting real env vars."""
    p = Path(dotenv_path)
    if not p.exists():
        return
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip("'\"")
                if key and key not in os.environ:
                    os.environ[key] = val


_PLACEHOLDER_VALUES = {
    "",
    "your_groq_api_key_here",
    "your_openai_api_key_here",
    "your_api_key_here",
    "none",
    "null",
    "changeme",
    "todo",
}


def _clean_key(raw: Optional[str]) -> Optional[str]:
    """Return a usable API key, or ``None`` when the value is absent/placeholder."""
    if raw is None:
        return None
    value = raw.strip().strip("'\"")
    if value.lower() in _PLACEHOLDER_VALUES:
        return None
    if value.lower().startswith("your_") or "api_key_here" in value.lower():
        return None
    return value


def _is_test_harness() -> bool:
    """Return True only when running under the test harness."""
    return (
        os.environ.get("LEARNSENSE_TEST_HARNESS", "").strip() == "1"
        or os.environ.get("PYTEST_CURRENT_TEST", "") != ""
    )


def resolve_mode() -> str:
    """Resolve the adapter mode. 'mock' is rejected unless in the test harness."""
    explicit = os.environ.get("LLM_MODE", "").strip().lower()
    if explicit == "mock":
        if not _is_test_harness():
            raise LLMConfigurationError(
                "LLM_MODE='mock' is only permitted when running under the test harness "
                "(LEARNSENSE_TEST_HARNESS=1 or PYTEST_CURRENT_TEST set). "
                "Production must run with LLM_MODE=live."
            )
        return "mock"
    return "live"


# ---------------------------------------------------------------------------
# JSON extraction helpers
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_json_object(content: str) -> Dict[str, Any]:
    """
    Parse a JSON object from an LLM reply, tolerating markdown fences and
    leading/trailing prose. Raises :class:`LLMOutputError` when nothing parses.
    """
    if not content or not content.strip():
        raise LLMOutputError("LLM returned an empty response body.")

    candidates: List[str] = []
    fenced = _FENCE_RE.findall(content)
    candidates.extend(block.strip() for block in fenced)

    stripped = content.strip()
    candidates.append(stripped)

    first_brace = stripped.find("{")
    last_brace = stripped.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        candidates.append(stripped[first_brace : last_brace + 1])

    for candidate in candidates:
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, dict):
            return parsed
        # A bare list is a common model slip for list-returning prompts; wrap it
        # using the single array-valued key the caller declared, if unambiguous.
        if isinstance(parsed, list):
            return {"items": parsed}

    raise LLMOutputError(
        "LLM response did not contain a decodable JSON object.",
        details={"response_preview": stripped[:600]},
    )


# ---------------------------------------------------------------------------
# Schema conformance validation
# ---------------------------------------------------------------------------

# Placeholder strings that indicate the model echoed the schema template back
# instead of authoring content.
_PLACEHOLDER_MARKERS = (
    "string (",
    "string(",
    "option a)",
    "option b)",
    "option c)",
    "option d)",
    "correct option",
    "distractor",
    "your_",
    "todo",
    "n/a",
    "xxx",
    "<string>",
    "type here",
    "placeholder",
    "lorem ipsum",
)


def _looks_like_placeholder(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    low = value.strip().lower()
    if not low:
        return True
    return any(marker in low for marker in _PLACEHOLDER_MARKERS)


def _type_of(schema: Any) -> str:
    if isinstance(schema, str):
        low = schema.lower()
        if low.startswith("list") or low.startswith("array") or low.startswith("["):
            return "list"
        if low.startswith("dict") or low.startswith("object") or low.startswith("{"):
            return "dict"
        if "float" in low or "number" in low or "int" in low:
            return "number"
        if "bool" in low:
            return "bool"
        if "list" in low or "string[]" in low:
            return "list"
        return "string"
    if isinstance(schema, list):
        return "list"
    if isinstance(schema, dict):
        return "dict"
    return "string"


def _validate_node(value: Any, schema: Any, path: str, problems: List[str]) -> None:
    """Structural + placeholder validation driven by the caller-supplied schema template."""
    expected = _type_of(schema)

    if expected == "dict":
        if not isinstance(value, dict):
            problems.append(f"{path}: expected object, got {type(value).__name__}")
            return
        if isinstance(schema, dict):
            for key, sub in schema.items():
                if key not in value or value[key] is None:
                    problems.append(f"{path}.{key}: missing required field")
                    continue
                _validate_node(value[key], sub, f"{path}.{key}", problems)
        return

    if expected == "list":
        if not isinstance(value, list):
            problems.append(f"{path}: expected list, got {type(value).__name__}")
            return
        if not value:
            problems.append(f"{path}: list must not be empty")
            return
        item_schema = schema[0] if isinstance(schema, list) and schema else None
        for idx, item in enumerate(value[:8]):
            if item_schema is not None:
                _validate_node(item, item_schema, f"{path}[{idx}]", problems)
            elif _looks_like_placeholder(item):
                problems.append(f"{path}[{idx}]: placeholder content")
        return

    if expected == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            try:
                float(value)
            except (TypeError, ValueError):
                problems.append(f"{path}: expected number, got {value!r}")
        return

    if expected == "bool":
        if not isinstance(value, bool):
            problems.append(f"{path}: expected boolean, got {value!r}")
        return

    # string
    if not isinstance(value, str):
        problems.append(f"{path}: expected string, got {type(value).__name__}")
        return
    if not value.strip():
        problems.append(f"{path}: empty string")
        return
    if _looks_like_placeholder(value):
        problems.append(f"{path}: placeholder content ({value.strip()[:60]!r})")


def validate_against_schema(payload: Dict[str, Any], schema_template: Dict[str, Any]) -> List[str]:
    """Return a list of human-readable schema problems; empty list means conformant."""
    problems: List[str] = []
    _validate_node(payload, schema_template, "$", problems)
    return problems


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

_PROVIDERS: Dict[str, Tuple[str, str]] = {
    # name -> (base_url, api key env var)
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
}


class Phase3LLMAdapter:
    """The single authoritative LLM entry point for LearnSense."""

    SYSTEM_PREAMBLE = (
        "You are the LearnSense instructional engine. You transform a learner's own "
        "uploaded source material into grounded educational content.\n"
        "Hard rules:\n"
        "1. Ground every factual claim in the SOURCE MATERIAL supplied in the request. "
        "Never introduce a fact that the source does not support.\n"
        "2. Never fabricate citations, page numbers, quotes or section names.\n"
        "3. Return ONLY a single JSON object that conforms to the requested JSON "
        "structure. No markdown fences, no commentary outside the JSON.\n"
        "4. Never echo the structure template or its placeholder descriptions as content."
    )

    def __init__(
        self,
        model_name: Optional[str] = None,
        provider: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> None:
        load_env_file()

        self.mode = resolve_mode()
        self.groq_api_key = _clean_key(os.environ.get("GROQ_API_KEY"))
        self.openai_api_key = _clean_key(os.environ.get("OPENAI_API_KEY"))

        self.provider = (provider or os.environ.get("LLM_PROVIDER") or "").strip().lower() or None
        if self.provider is None and self.mode != "mock":
            raise LLMConfigurationError(
                "LLM_PROVIDER is required (e.g. LLM_PROVIDER=groq or LLM_PROVIDER=openai). "
                "Inferring provider from API keys is forbidden per no-fallback policy §1.2 #5."
            )

        if self.model_name_is_valid(model_name):
            self.model_name = model_name
        elif self.provider == "groq":
            self.model_name = os.environ.get("GROQ_MODEL", "").strip() or None
            if not self.model_name and self.mode != "mock":
                raise LLMConfigurationError(
                    "GROQ_MODEL is required when LLM_PROVIDER=groq. Do not default model names."
                )
        elif self.provider == "openai":
            self.model_name = os.environ.get("OPENAI_MODEL", "").strip() or None
            if not self.model_name and self.mode != "mock":
                raise LLMConfigurationError(
                    "OPENAI_MODEL is required when LLM_PROVIDER=openai. Do not default model names."
                )
        elif self.mode != "mock":
            self.model_name = os.environ.get("LLM_MODEL", "").strip() or None
            if not self.model_name:
                raise LLMConfigurationError("LLM_MODEL is required when LLM_PROVIDER is custom.")
        else:
            self.model_name = model_name or "mock-model"

        self.timeout_seconds = float(
            timeout_seconds if timeout_seconds is not None else os.environ.get("LLM_TIMEOUT_SECONDS", 60)
        )
        self.max_retries = int(
            max_retries if max_retries is not None else os.environ.get("LLM_MAX_RETRIES", 3)
        )

    # -- introspection ------------------------------------------------------

    @staticmethod
    def model_name_is_valid(model_name: Optional[str]) -> bool:
        return bool(model_name) and not model_name.startswith("mock-")

    @property
    def is_live(self) -> bool:
        return self.mode == "live"

    @property
    def is_mock(self) -> bool:
        return self.mode == "mock"

    def has_credentials(self) -> bool:
        return bool(self.groq_api_key or self.openai_api_key)

    def health(self) -> Dict[str, Any]:
        """Structured provider status used by ``/health`` and the frontend banner."""
        return {
            "mode": self.mode,
            "provider": self.provider,
            "model": self.model_name,
            "has_credentials": self.has_credentials(),
        }

    def _require_live(self) -> None:
        if self.mode == "mock":
            if _shared_adapter is not None and getattr(_shared_adapter, "is_mock", False) and _shared_adapter is not self:
                return
            raise LLMConfigurationError(
                "Phase3LLMAdapter cannot execute directly with mode='mock'. "
                "Test doubles must be injected via set_llm_adapter(MockLLMAdapter())."
            )
        if not self.provider:
            raise LLMConfigurationError("No LLM provider could be resolved from configuration.")
        if not self.has_credentials():
            raise LLMConfigurationError(
                "No LLM API key is configured. Set GROQ_API_KEY (or OPENAI_API_KEY) in the "
                "environment and restart the server. LearnSense will not fabricate learning "
                "content without a real model.",
                details={"hint": "GROQ_API_KEY / OPENAI_API_KEY"},
            )

    # -- HTTP ---------------------------------------------------------------

    def _provider_base_url(self) -> str:
        base = os.environ.get("LLM_BASE_URL")
        if base:
            return base.rstrip("/")
        if self.provider and self.provider in _PROVIDERS:
            return _PROVIDERS[self.provider][0]
        raise LLMConfigurationError(f"Unknown LLM provider '{self.provider}'.")

    def _provider_api_key(self) -> str:
        if self.provider == "groq":
            return self.groq_api_key or ""
        if self.provider == "openai":
            return self.openai_api_key or ""
        # Custom LLM_BASE_URL deployments reuse whichever key is configured.
        return self.groq_api_key or self.openai_api_key or ""

    @staticmethod
    def _candidate_models(model: str) -> List[str]:
        """Groq deprecates open-weight aliases; try a sibling if the first 404s."""
        candidates = [model]
        if "120b" in model:
            candidates.append("openai/gpt-oss-20b")
        elif "20b" in model:
            candidates.append("openai/gpt-oss-120b")
        elif "llama" in model and "70b" in model:
            candidates.append("llama-3.3-70b-versatile")
        return candidates

    # Transport failures that a retry can genuinely fix.
    #
    # These are raised by ``http.client`` *after* the request was written, and urllib
    # only wraps OSError into URLError inside ``do_open`` -- exceptions raised by
    # ``getresponse()`` propagate bare. Consequently "Remote end closed connection
    # without response" (RemoteDisconnected), a bare BadStatusLine, and a Windows
    # WSAECONNRESET ("An existing connection was forcibly closed by the remote host")
    # all bypassed every ``except`` clause and were reported as
    # "Unexpected failure calling LLM provider" -- a permanent-sounding error for what
    # is in practice a routine, retryable network blip.
    _TRANSIENT_TRANSPORT_ERRORS: Tuple[type, ...] = (
        RemoteDisconnected,
        BadStatusLine,
        IncompleteRead,
        ConnectionResetError,
        ConnectionAbortedError,
        ConnectionError,
        BrokenPipeError,
        ssl.SSLError,
        OSError,
    )

    @classmethod
    def _is_transient_transport_error(cls, exc: BaseException) -> bool:
        """True when ``exc`` (or a URLError's reason) is a droppable connection."""
        if isinstance(exc, urllib.error.HTTPError):
            # An HTTP error means the server *did* respond; handled separately.
            return False
        if isinstance(exc, cls._TRANSIENT_TRANSPORT_ERRORS):
            return True
        reason = getattr(exc, "reason", None)
        return isinstance(reason, cls._TRANSIENT_TRANSPORT_ERRORS)

    @classmethod
    def _describe_transport_error(cls, exc: BaseException) -> str:
        """Human-readable cause for a dropped connection, unwrapping URLError."""
        inner = getattr(exc, "reason", None)
        if isinstance(inner, BaseException) and inner is not exc:
            exc = inner
        if isinstance(exc, RemoteDisconnected):
            return "the server closed the connection before sending a response"
        if isinstance(exc, BadStatusLine):
            return "the server returned a malformed HTTP response"
        if isinstance(exc, IncompleteRead):
            return "the response was truncated mid-transfer"
        if isinstance(exc, ssl.SSLError):
            return f"the TLS connection failed ({exc})"
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError)):
            return f"the connection was reset by the remote host ({exc})"
        if isinstance(exc, BrokenPipeError):
            return "the connection was closed while the request was being sent"
        return str(exc) or type(exc).__name__

    def _backoff(self, attempt: int) -> None:
        """Exponential backoff with full jitter, so retries do not synchronise."""
        ceiling = min(2 ** (attempt - 1) * 1.5, 8.0)
        time.sleep(random.uniform(ceiling * 0.5, ceiling))

    def _post_completion(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        config: Dict[str, Any],
        json_mode: bool,
    ) -> str:
        url = f"{self._provider_base_url()}/chat/completions"
        api_key = self._provider_api_key()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "LearnSense/1.0 (+adaptive-learning-runtime)",
            # Avoids stale pooled sockets through corporate proxies, which are a common
            # source of "remote end closed connection" on long-lived server processes.
            "Connection": "close",
            "Accept": "application/json",
        }

        last_error: Optional[Exception] = None

        for model_name in self._candidate_models(self.model_name):
            payload: Dict[str, Any] = {
                "model": model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": float(config.get("temperature", 0.3)),
            }
            if config.get("max_tokens"):
                payload["max_tokens"] = int(config["max_tokens"])
            if json_mode:
                # Several OpenAI-compatible providers reject this for non-JSON models;
                # retry without it rather than failing the whole generation.
                payload["response_format"] = {"type": "json_object"}

            for attempt in range(1, self.max_retries + 1):
                try:
                    req = urllib.request.Request(
                        url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
                    )
                    with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                        raw = resp.read().decode("utf-8")
                    data = json.loads(raw)
                    return data["choices"][0]["message"]["content"] or ""
                except urllib.error.HTTPError as exc:  # noqa: PERF203
                    body = ""
                    retry_after: Optional[float] = None
                    try:
                        body = exc.read().decode("utf-8", "replace")[:400]
                    except (OSError, ValueError, AttributeError):  # pragma: no cover - defensive
                        pass
                    try:
                        raw_retry = exc.headers.get("Retry-After") if exc.headers else None
                        if raw_retry:
                            retry_after = float(raw_retry)
                    except (TypeError, ValueError):
                        retry_after = None

                    if exc.code in (401, 403):
                        raise LLMInvalidAPIKeyError(
                            f"LLM provider '{self.provider}' rejected the configured API key.",
                            details={"provider": self.provider, "status": exc.code, "body": body},
                        ) from exc
                    if exc.code == 429:
                        last_error = LLMRateLimitError(
                            "LLM provider rate limit reached. Retry shortly.",
                            details={
                                "provider": self.provider,
                                "model": model_name,
                                "attempt": attempt,
                                "retry_after": retry_after,
                                "body": body,
                            },
                        )
                    elif exc.code in (408, 502, 503, 504):
                        # Gateway-level transient failures: worth retrying.
                        last_error = LLMUnavailableError(
                            f"LLM provider is temporarily unavailable (HTTP {exc.code}).",
                            details={"provider": self.provider, "status": exc.code, "body": body},
                        )
                    elif exc.code == 400 and json_mode:
                        # Likely a rejected response_format / model combination.
                        payload.pop("response_format", None)
                        last_error = LLMProviderError(
                            "LLM provider rejected the request parameters.",
                            details={"provider": self.provider, "status": 400, "body": body},
                        )
                    else:
                        last_error = LLMProviderError(
                            f"LLM provider returned HTTP {exc.code}.",
                            details={"provider": self.provider, "status": exc.code, "body": body},
                        )

                    if retry_after and attempt < self.max_retries:
                        time.sleep(min(retry_after, 30.0))
                        continue

                except urllib.error.URLError as exc:
                    reason = getattr(exc, "reason", exc)
                    if isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
                        last_error = LLMTimeoutError(
                            f"LLM request timed out after {self.timeout_seconds}s.",
                            details={"provider": self.provider, "model": model_name, "attempt": attempt},
                        )
                    elif self._is_transient_transport_error(exc):
                        last_error = LLMUnavailableError(
                            "Lost the connection to the LLM provider because "
                            f"{self._describe_transport_error(exc)}.",
                            details={
                                "provider": self.provider,
                                "model": model_name,
                                "attempt": attempt,
                                "retryable": True,
                            },
                        )
                    else:
                        last_error = LLMUnavailableError(
                            f"Could not reach LLM provider '{self.provider}': {reason}",
                            details={"provider": self.provider},
                        )

                except socket.timeout as exc:
                    last_error = LLMTimeoutError(
                        f"LLM request timed out after {self.timeout_seconds}s.",
                        details={"provider": self.provider, "model": model_name, "attempt": attempt},
                    )

                except (json.JSONDecodeError, KeyError, IndexError) as exc:
                    last_error = LLMOutputError(
                        f"LLM provider returned an undecodable response: {exc}",
                        details={"provider": self.provider, "model": model_name},
                    )

                except Exception as exc:
                    # Must stay AFTER the narrow handlers: RemoteDisconnected, BadStatusLine
                    # and ConnectionResetError are OSError subclasses that would otherwise be
                    # swallowed here and reported as a non-retryable "unexpected failure".
                    if self._is_transient_transport_error(exc):
                        last_error = LLMUnavailableError(
                            "Lost the connection to the LLM provider because "
                            f"{self._describe_transport_error(exc)}. This is usually transient.",
                            details={
                                "provider": self.provider,
                                "model": model_name,
                                "attempt": attempt,
                                "exception": type(exc).__name__,
                                "retryable": True,
                            },
                        )
                    else:
                        last_error = LLMUnavailableError(
                            f"Unexpected failure calling LLM provider: {exc}",
                            details={
                                "provider": self.provider,
                                "model": model_name,
                                "exception": type(exc).__name__,
                            },
                        )

                if last_error is not None and not last_error.recoverable:
                    raise last_error
                if attempt < self.max_retries:
                    self._backoff(attempt)

            # This model alias is unusable; try the sibling alias before failing.

        if isinstance(last_error, LLMInvalidAPIKeyError):
            raise last_error
        if last_error is not None:
            raise last_error
        raise LLMUnavailableError("LLM provider call failed without a diagnostic error.")

    # -- public generation API ---------------------------------------------

    def generate_json(
        self,
        prompt: str,
        schema_template: Dict[str, Any],
        config: Optional[Dict[str, Any]] = None,
        *,
        validate: bool = True,
    ) -> Dict[str, Any]:
        """
        Generate a JSON object conforming to ``schema_template``.

        Raises a typed :mod:`phase3.errors` exception on any provider, transport,
        decoding or schema-conformance failure. Never returns placeholder content.
        """
        cfg = dict(config or {})
        cfg.setdefault("temperature", 0.3)
        self._require_live()

        if self.mode == "mock":
            return _shared_adapter.generate_json(prompt, schema_template, config=cfg, validate=validate)

        system_prompt = (
            f"{self.SYSTEM_PREAMBLE}\n"
            "Return a single JSON object whose keys match this structure exactly:\n"
            f"{json.dumps(schema_template, indent=2, ensure_ascii=False)}"
        )
        content = self._post_completion(
            system_prompt=system_prompt, user_prompt=prompt, config=cfg, json_mode=True
        )
        payload = extract_json_object(content)

        if validate:
            problems = validate_against_schema(payload, schema_template)
            if problems:
                raise LLMOutputError(
                    "LLM output did not conform to the requested structure.",
                    details={"problems": problems[:12], "payload_preview": json.dumps(payload)[:600]},
                )
        return payload

    def generate_text(
        self,
        prompt: str,
        *,
        system_prompt: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Generate free-form text. Raises on failure; never returns fallback prose."""
        cfg = dict(config or {})
        cfg.setdefault("temperature", 0.4)
        self._require_live()

        if self.mode == "mock":
            return _shared_adapter.generate_text(prompt, system_prompt=system_prompt, config=cfg)

        content = self._post_completion(
            system_prompt=system_prompt or self.SYSTEM_PREAMBLE,
            user_prompt=prompt,
            config=cfg,
            json_mode=False,
        )
        if not content or not content.strip():
            raise LLMOutputError("LLM returned an empty text response.")
        return content.strip()

    # -- legacy alias retained for Phase 2 / Phase 4 callers -----------------
    generate_json_response = generate_json


_shared_adapter: Optional[Any] = None


def get_llm_adapter() -> Any:
    """Process-wide singleton so credentials/connection settings are resolved once."""
    global _shared_adapter
    if _shared_adapter is None:
        _shared_adapter = Phase3LLMAdapter()
    return _shared_adapter


def set_llm_adapter(adapter: Optional[Any]) -> None:
    """Test hook: inject a test double adapter (e.g. MockLLMAdapter) during tests."""
    global _shared_adapter
    _shared_adapter = adapter


def reset_llm_adapter() -> None:
    """Test hook: drop the cached adapter so new env values take effect."""
    global _shared_adapter
    _shared_adapter = None

