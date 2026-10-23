"""
Stable identifier generation for the canonical curriculum (Person 2).

Why not reuse ``phase2.utils.id_generator``?  That generator produces
``c_<sha12>`` over ``"<source_document_id>::concept::<name>"``.  Two consequences
make it unusable as a *canonical* identifier:

* the same topic uploaded as two different PDFs yields two different concept ids,
  so the rest of the platform can never join on concepts across documents;
* renaming a concept silently changes its id, which the shared contract
  (``concept_schema.json``) explicitly forbids ("IDs must be stable and must not
  be derived from display names").

Canonical ids here are therefore **document independent** and are assigned once,
from an explicit curriculum-authored ``stable_key``.  Renaming a concept changes
only its display name; the id never moves.  When a caller does not supply a key,
one is derived from the normalized name *at creation time and then frozen* into
the record, so later renames still cannot move the id.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Optional

#: Namespace for the JEE Class 11/12 curriculum this module curates.
DEFAULT_CURRICULUM_ID = "jee_class_11_12"

#: Default syllabus/curriculum version label for a freshly seeded graph.
DEFAULT_SYLLABUS_VERSION = "2026.jee.v1"

#: Canonical concept ids are prefixed ``cc_`` to keep them visually distinct from
#: document-scoped extracted ids (``c_``), which Person 3/4 already render.
CONCEPT_ID_PREFIX = "cc"

_RELATIONSHIP_ID_PREFIX = "rel"
_VERSION_ID_PREFIX = "cv"
_CANDIDATE_ID_PREFIX = "cand"

_SAFE_RE = re.compile(r"[^a-z0-9]+")


def _sha256_prefix(data: str, prefix: str, length: int = 16) -> str:
    digest = hashlib.sha256(data.encode("utf-8")).hexdigest()[:length]
    return f"{prefix}_{digest}"


def slugify(text: str, max_length: int = 80) -> str:
    """
    Lowercase ASCII-ish slug of ``text``.

    Applied to the *normalized* term form, so punctuation, case and typography
    differences collapse before slugging.  Non-ASCII letters that survive
    slugging are hex-escaped so keys stay portable across filesystems.
    """
    normalized = unicodedata.normalize("NFKD", text or "")
    normalized = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = _SAFE_RE.sub("_", normalized).strip("_")
    if not slug:
        # Pure non-ASCII input (e.g. a Greek-letter term): fall back to a stable
        # hex token so the key is still deterministic and portable.
        slug = hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:12]
    return slug[:max_length].strip("_")


def stable_key_from_name(name: str, chapter_id: Optional[str] = None) -> str:
    """
    Derive a *creation-time* stable key from a concept name.

    The key is frozen into the concept record when it is created; it is never
    recomputed, so a later rename cannot change the concept id.
    """
    scope = slugify(chapter_id) if chapter_id else "general"
    return f"{scope}/{slugify(name)}"


def generate_concept_id(curriculum_id: str, stable_key: str) -> str:
    """
    Deterministic, document-independent canonical concept id.

    ``cc_<sha256(curriculum_id::stable_key)[:16]>``.  The same curriculum and key
    produce the same id on every machine, which is what makes the evaluation
    fixtures and the Person 3 integration reproducible.
    """
    if not stable_key:
        raise ValueError("stable_key is required to generate a canonical concept id")
    return _sha256_prefix(f"{curriculum_id}::concept::{stable_key}", CONCEPT_ID_PREFIX)


def generate_candidate_id(document_id: str, locator: str, label: str) -> str:
    """
    Deterministic id for an *extracted* mapping candidate.

    Candidates are not canonical facts, so their id is scoped to the source
    document and evidence location.  Re-running the mapper on the same document
    yields the same candidate ids, which makes mapping runs diffable.
    """
    return _sha256_prefix(
        f"{document_id}::candidate::{locator}::{label}", _CANDIDATE_ID_PREFIX
    )


def generate_relationship_id(
    curriculum_id: str, source: str, relationship_type: str, target: str
) -> str:
    """
    Content-addressed edge id over (curriculum, source, type, target).

    Because it is content addressed, submitting the same edge twice collapses to
    one record instead of silently creating a duplicate.
    """
    return _sha256_prefix(
        f"{curriculum_id}::rel::{source}::{relationship_type}::{target}",
        _RELATIONSHIP_ID_PREFIX,
    )


def generate_version_id(curriculum_id: str, content_checksum: str) -> str:
    """Content-addressed curriculum version id: identical graphs snapshot identically."""
    return _sha256_prefix(f"{curriculum_id}::version::{content_checksum}", _VERSION_ID_PREFIX)


def excerpt_hash(text: str) -> str:
    """Stable short hash of an evidence excerpt, as required by ``source_refs[].excerpt_hash``."""
    normalized = re.sub(r"\s+", " ", (text or "").strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
