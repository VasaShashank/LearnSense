"""Runtime configuration validation and CORS policy (docs/deployment/deployment.md).

``LEARNSENSE_ENV`` must be set explicitly to ``development``, ``test``, ``staging``
or ``production``; there is no default. Startup fails when it is unset or unknown,
so a production deployment can never silently run with development behavior.
Staging and production are *strict*: startup also fails unless every required
setting is present and safe. For exposure decisions taken at request time (demo
personas, status/debug detail) an unset or unknown environment is treated as
strict (fail closed). Error messages name settings, never values.
"""

from __future__ import annotations

import os
from typing import List, Mapping, Optional, Tuple
from urllib.parse import urlsplit

KNOWN_ENVIRONMENTS = ("development", "test", "staging", "production")
STRICT_ENVIRONMENTS = frozenset({"staging", "production"})
DEV_DEFAULT_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]


class ConfigurationError(RuntimeError):
    """Required configuration is missing or unsafe for this environment."""


def environment(env: Optional[Mapping[str, str]] = None) -> str:
    """Normalized LEARNSENSE_ENV, or "" when unset."""
    env = os.environ if env is None else env
    return (env.get("LEARNSENSE_ENV") or "").strip().lower()


def is_strict(env: Optional[Mapping[str, str]] = None) -> bool:
    """Strict unless explicitly development or test (unset/unknown fails closed)."""
    return environment(env) not in ("development", "test")


def _origins(env: Mapping[str, str]) -> List[str]:
    return [o.strip() for o in (env.get("ALLOWED_ORIGINS") or "").split(",") if o.strip()]


def cors_settings(env: Optional[Mapping[str, str]] = None) -> Tuple[List[str], bool]:
    """(allowed origins, allow_credentials).

    * Explicit origins → those origins, credentials allowed.
    * Unset in development → local dev-server origins, credentials allowed.
    * ``*`` in development → any origin, credentials NOT allowed.
    * Strict environments never get a wildcard or a default (validation fails).
    """
    env = os.environ if env is None else env
    origins = _origins(env)
    if "*" in origins:
        return (["*"], False) if not is_strict(env) else ([], False)
    if origins:
        return origins, True
    return ([], False) if is_strict(env) else (list(DEV_DEFAULT_ORIGINS), True)


def validate_runtime_config(env: Optional[Mapping[str, str]] = None) -> List[str]:
    """Problems for the current environment (empty = OK). Names only, never values."""
    env = os.environ if env is None else env
    name = environment(env)
    problems: List[str] = []
    if not name:
        problems.append(
            "LEARNSENSE_ENV must be set explicitly to one of " + ", ".join(KNOWN_ENVIRONMENTS)
        )
        return problems
    if name not in KNOWN_ENVIRONMENTS:
        problems.append(f"LEARNSENSE_ENV must be one of {', '.join(KNOWN_ENVIRONMENTS)}")
        return problems
    if name not in STRICT_ENVIRONMENTS:
        return problems

    supabase_url = (env.get("SUPABASE_URL") or "").strip()
    if not supabase_url:
        problems.append("SUPABASE_URL is required")
    elif urlsplit(supabase_url).scheme != "https":
        problems.append("SUPABASE_URL must use https")
    if not ((env.get("SUPABASE_PUBLISHABLE_KEY") or "").strip() or (env.get("SUPABASE_ANON_KEY") or "").strip()):
        problems.append("SUPABASE_PUBLISHABLE_KEY (or SUPABASE_ANON_KEY) is required")
    if not (env.get("DATABASE_URL") or "").strip():
        problems.append("DATABASE_URL is required")
    if (env.get("LEARNSENSE_REQUIRE_PG") or "").strip() != "1":
        problems.append("LEARNSENSE_REQUIRE_PG must be 1")
    if (env.get("LEARNSENSE_TEST_HARNESS") or "").strip() == "1":
        problems.append("LEARNSENSE_TEST_HARNESS must not be set")

    origins = _origins(env)
    if not origins:
        problems.append("ALLOWED_ORIGINS must list the allowed frontend origins")
    elif "*" in origins:
        problems.append("ALLOWED_ORIGINS must not contain '*'")
    else:
        for origin in origins:
            parts = urlsplit(origin)
            if parts.scheme not in ("http", "https") or not parts.netloc or parts.path not in ("", "/"):
                problems.append("ALLOWED_ORIGINS entries must be scheme://host[:port] origins")
                break
            if name == "production" and parts.scheme != "https":
                problems.append("ALLOWED_ORIGINS must use https in production")
                break
    return problems


def enforce_runtime_config(env: Optional[Mapping[str, str]] = None) -> None:
    problems = validate_runtime_config(env)
    if problems:
        raise ConfigurationError(
            f"Invalid {environment(env) or 'unset-environment'} configuration: " + "; ".join(problems)
        )
