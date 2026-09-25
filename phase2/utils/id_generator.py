"""
Deterministic ID hashing utilities for Phase 2.
Follows Plan §16.3:
concept_id = h(source_document_id, normalized_canonical_key, sense_qualifier)
skill_id = h(source_document_id, action, sorted_concept_ids)
"""

import hashlib
from typing import List, Optional


def _sha256_prefix(data: str, prefix: str, length: int = 12) -> str:
    digest = hashlib.sha256(data.encode("utf-8")).hexdigest()[:length]
    return f"{prefix}_{digest}"


def generate_concept_id(source_doc_id: str, canonical_name: str, sense_qualifier: Optional[str] = None) -> str:
    norm_key = canonical_name.strip().lower()
    sense = (sense_qualifier or "").strip().lower()
    raw = f"{source_doc_id}::concept::{norm_key}::{sense}"
    return _sha256_prefix(raw, "c")


def generate_skill_id(source_doc_id: str, action: str, concept_ids: List[str]) -> str:
    sorted_concepts = ",".join(sorted(concept_ids))
    act = action.strip().lower()
    raw = f"{source_doc_id}::skill::{act}::{sorted_concepts}"
    return _sha256_prefix(raw, "s")


def generate_unit_id(source_doc_id: str, section_id: str, unit_index: int, unit_type: str) -> str:
    raw = f"{source_doc_id}::unit::{section_id}::{unit_index}::{unit_type}"
    return _sha256_prefix(raw, "u")


def generate_mention_id(source_doc_id: str, block_id: str, start: int, end: int) -> str:
    raw = f"{source_doc_id}::mention::{block_id}::{start}:{end}"
    return _sha256_prefix(raw, "m")


def generate_evidence_id(source_doc_id: str, block_id: str, start: int, end: int, kind: str) -> str:
    raw = f"{source_doc_id}::evidence::{block_id}::{start}:{end}::{kind}"
    return _sha256_prefix(raw, "ev")


def generate_relationship_id(source_doc_id: str, source_concept_id: str, rel_type: str, target_concept_id: str) -> str:
    raw = f"{source_doc_id}::rel::{source_concept_id}::{rel_type}::{target_concept_id}"
    return _sha256_prefix(raw, "rel")


def generate_item_id(source_doc_id: str, unit_id: str, item_index: int) -> str:
    raw = f"{source_doc_id}::item::{unit_id}::{item_index}"
    return _sha256_prefix(raw, "i")


def generate_formula_id(source_doc_id: str, block_id: str, formula_index: int) -> str:
    raw = f"{source_doc_id}::formula::{block_id}::{formula_index}"
    return _sha256_prefix(raw, "f")
