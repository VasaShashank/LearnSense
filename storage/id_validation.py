"""Validation helpers for identifiers used as storage boundaries.

Legacy demo and test learner IDs remain supported by storage repositories when
they use the safe legacy alphabet. Authenticated learners must use canonical
Supabase UUIDs; this helper deliberately does not map or coerce legacy IDs.
"""

from __future__ import annotations

import re
import uuid

_SAFE_STORAGE_ID = re.compile(r"\A[A-Za-z0-9_-]{1,128}\Z", re.ASCII)


def validate_storage_id(value: str, *, name: str = "id") -> str:
    """Return a safe legacy-compatible ID or reject it before filesystem access."""
    if not isinstance(value, str) or not _SAFE_STORAGE_ID.fullmatch(value):
        raise ValueError(f"Invalid {name}: expected 1-128 ASCII letters, digits, '_' or '-'.")
    return value


def validate_canonical_learner_id(value: str) -> str:
    """Require the lowercase canonical UUID form used for Supabase identities."""
    if not isinstance(value, str):
        raise ValueError("Invalid learner_id: expected a canonical Supabase UUID.")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        raise ValueError("Invalid learner_id: expected a canonical Supabase UUID.") from None
    canonical = str(parsed)
    if value != canonical:
        raise ValueError("Invalid learner_id: expected a canonical Supabase UUID.")
    return canonical
