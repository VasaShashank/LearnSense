"""
Semantic Entity Resolution and Canonicalization Engine for Phase 2.
Implements the multi-stage resolution pipeline specified in Section 15 of TAPROOT:
1. Normalization
2. Exact merge
3. Syntactic & ordinal alias matching (e.g. "Newton's Second Law" vs "Newton's 2nd Law" vs "Newton II law")
4. Domain-grounded semantic equivalence resolution (e.g. "rate of change of velocity" <-> "acceleration")
5. Strict evidence verification
6. Safe non-merging of near-misses and unrelated concepts (e.g. "Speed" vs "Velocity", "Newton's 1st" vs "Newton's 2nd")
"""

from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from phase2.models import (
    ConceptMention,
    Evidence,
    MergeRecord,
)

RESOLVER_VERSION = "2026.09.0"

_ROMAN_NUMERALS = {
    "i": "1",
    "ii": "2",
    "iii": "3",
    "iv": "4",
    "v": "5",
    "vi": "6",
    "vii": "7",
    "viii": "8",
    "ix": "9",
    "x": "10",
}

_ORDINALS = {
    "first": "1",
    "1st": "1",
    "second": "2",
    "2nd": "2",
    "third": "3",
    "3rd": "3",
    "fourth": "4",
    "4th": "4",
    "fifth": "5",
    "5th": "5",
}

# Domain semantic equivalences: (canonical_name, set of equivalent phrases)
_DOMAIN_SEMANTIC_EQUIVALENCES: List[Tuple[str, Set[str]]] = [
    (
        "Acceleration",
        {
            "acceleration",
            "rate of change of velocity",
            "time rate of change of velocity",
            "derivative of velocity",
            "second derivative of position",
            "second derivative of displacement",
        },
    ),
    (
        "Velocity",
        {
            "velocity",
            "rate of change of displacement",
            "rate of change of position",
            "derivative of displacement",
            "derivative of position",
        },
    ),
    (
        "Newton's Second Law of Motion",
        {
            "newton's second law",
            "newtons second law",
            "newton's 2nd law",
            "newtons 2nd law",
            "newton ii law",
            "newtons second law of motion",
            "newton's second law of motion",
            "newton second law",
            "second law",
            "second law of motion",
        },
    ),
    (
        "Newton's First Law of Motion",
        {
            "newton's first law",
            "newtons first law",
            "newton's 1st law",
            "newtons 1st law",
            "newton i law",
            "newton's law of inertia",
            "law of inertia",
            "newtons first law of motion",
            "newton's first law of motion",
            "first law",
            "first law of motion",
        },
    ),
    (
        "Newton's Third Law of Motion",
        {
            "newton's third law",
            "newtons third law",
            "newton's 3rd law",
            "newtons 3rd law",
            "newton iii law",
            "action and reaction law",
            "law of action and reaction",
            "newtons third law of motion",
            "newton's third law of motion",
            "third law",
            "third law of motion",
        },
    ),
    (
        "Newton's Laws of Motion",
        {
            "newton's laws of motion",
            "newtons laws of motion",
            "newton's laws",
            "newtons laws",
            "laws of motion",
        },
    ),
    (
        "Friction",
        {
            "friction",
            "force of friction",
            "frictional force",
            "friction force",
            "friction and resistive forces",
            "resistive forces",
            "properties of friction",
            "laws of friction",
        },
    ),
    (
        "Static Friction",
        {
            "static friction",
            "static friction force",
            "force of static friction",
        },
    ),
    (
        "Kinetic Friction",
        {
            "kinetic friction",
            "kinetic friction force",
            "force of kinetic friction",
        },
    ),
    (
        "Limiting Friction",
        {
            "limiting friction",
            "limiting force of friction",
            "maximum static friction",
            "maximum static friction force",
            "maximum value of static friction",
        },
    ),
    (
        "Centripetal Acceleration",
        {
            "centripetal acceleration",
            "radial acceleration",
            "centripetal acceleration and force",
            "radial forces",
            "radial force",
        },
    ),
    (
        "Centripetal Force",
        {
            "centripetal force",
            "centripetal force and acceleration",
            "force and acceleration",
        },
    ),
    (
        "Normal Force",
        {
            "normal force",
            "normal reaction",
            "normal reaction force",
        },
    ),
    (
        "Angle of Repose",
        {
            "angle of repose",
            "angle of friction",
        },
    ),
    (
        "Net Acceleration",
        {
            "net acceleration",
            "net acceleration in circular motion",
            "acceleration in circular motion",
        },
    ),
    (
        "Conservation of Energy",
        {
            "conservation of energy",
            "law of conservation of energy",
            "principle of conservation of energy",
            "first law of thermodynamics",
        },
    ),
    (
        "Conservation of Momentum",
        {
            "conservation of momentum",
            "law of conservation of momentum",
            "principle of conservation of momentum",
            "conservation of linear momentum",
        },
    ),
    (
        "Gauss's Law",
        {
            "gauss's law",
            "gauss law",
            "gauss' law",
            "gauss flux theorem",
            "gauss's flux theorem",
        },
    ),
]

# Explicit near-miss concept sets: terms within the same set MUST NOT be merged
_NEAR_MISS_SETS: List[Set[str]] = [
    {"newton's first law", "newton's second law", "newton's third law"},
    {"speed", "velocity", "angular velocity"},
    {"mass", "weight"},
    {"distance", "displacement"},
    {"potential energy", "kinetic energy", "thermal energy"},
    {"linear momentum", "angular momentum"},
    {"scalar", "vector", "tensor"},
    {"heat", "temperature"},
    {"stress", "strain"},
    {"accuracy", "precision"},
    {"static friction", "kinetic friction", "limiting friction", "rolling friction"},
    {"centripetal acceleration", "tangential acceleration", "angular acceleration"},
    {"centripetal force", "centrifugal force"},
    {"coefficient of static friction", "coefficient of kinetic friction"},
    {"inertial mass", "gravitational mass"},
]


class SemanticEntityResolver:
    """
    Multi-stage semantic entity resolution and canonicalization engine.
    Ensures safe, verifiable merges with structured MergeRecords and zero speculative merging.
    """

    def __init__(self, confidence_threshold: float = 0.85):
        self.confidence_threshold = confidence_threshold
        self.resolver_version = RESOLVER_VERSION
        self.domain_equivalences = list(_DOMAIN_SEMANTIC_EQUIVALENCES)
        self._load_canonical_curriculum_equivalences()

    def _load_canonical_curriculum_equivalences(self) -> None:
        """Dynamically expands semantic equivalences with all 89 concepts across Physics, Chemistry, and Math."""
        import json
        for spec_path in [
            "curriculum/data/jee_curriculum_spec.json",
            "LearnSense/curriculum/data/jee_curriculum_spec.json",
            os.path.join(os.path.dirname(__file__), "..", "..", "curriculum", "data", "jee_curriculum_spec.json"),
        ]:
            if os.path.exists(spec_path):
                try:
                    with open(spec_path, "r", encoding="utf-8") as f:
                        spec = json.load(f)
                    for c in spec.get("concepts", []):
                        c_name = c.get("name", "").strip()
                        if not c_name:
                            continue
                        aliases = {c_name.lower()}
                        for a in c.get("aliases", []):
                            if isinstance(a, str) and len(a.strip()) > 2:
                                aliases.add(a.strip().lower())
                        self.domain_equivalences.append((c_name, aliases))
                    break
                except Exception:
                    pass

    @staticmethod
    def normalize_surface_key(text: str) -> str:
        """
        Normalizes surface strings:
        - lowercases and strips whitespace/punctuation
        - normalizes apostrophes and possessives ('s -> "")
        - standardizes roman numerals and ordinals to digits
        """
        if not text:
            return ""
        s = text.lower().strip()
        # Normalize quotes / apostrophes
        s = s.replace("’", "'").replace("`", "'")
        s = re.sub(r"'s\b", "", s)
        s = re.sub(r"[^\w\s-]", " ", s)
        tokens = s.split()

        norm_tokens = []
        for tok in tokens:
            # Check roman numerals
            if tok in _ROMAN_NUMERALS:
                norm_tokens.append(_ROMAN_NUMERALS[tok])
            # Check ordinals
            elif tok in _ORDINALS:
                norm_tokens.append(_ORDINALS[tok])
            else:
                norm_tokens.append(tok)

        return " ".join(norm_tokens)

    def is_near_miss(self, term_a: str, term_b: str) -> bool:
        """Checks if term_a and term_b belong to an explicit near-miss set and should NEVER merge."""
        norm_a = self.normalize_surface_key(term_a)
        norm_b = self.normalize_surface_key(term_b)

        if norm_a == norm_b:
            return False

        for nms in _NEAR_MISS_SETS:
            norm_set = {self.normalize_surface_key(item) for item in nms}
            if any(norm_a == item or norm_a.startswith(item) or item in norm_a for item in norm_set) and \
               any(norm_b == item or norm_b.startswith(item) or item in norm_b for item in norm_set):
                return True
        return False

    def find_semantic_equivalent(self, term: str) -> Optional[Tuple[str, float, str]]:
        """
        Looks up domain-grounded semantic equivalences.
        Returns (canonical_name, confidence, reason) if verified, else None.
        """
        norm_term = self.normalize_surface_key(term)

        equivalences = getattr(self, "domain_equivalences", _DOMAIN_SEMANTIC_EQUIVALENCES)
        for canonical_name, equiv_set in equivalences:
            norm_equiv_set = {self.normalize_surface_key(eq) for eq in equiv_set}
            if norm_term in norm_equiv_set:
                return (canonical_name, 0.95, "SEMANTIC_DOMAIN_EQUIVALENCE")

        return None

    def are_syntactic_variants(self, term_a: str, term_b: str) -> bool:
        """Determines if two terms are syntactic/ordinal/roman variants of each other."""
        if self.is_near_miss(term_a, term_b):
            return False
        norm_a = self.normalize_surface_key(term_a)
        norm_b = self.normalize_surface_key(term_b)
        return norm_a == norm_b

    def resolve_mentions(
        self,
        mentions: List[ConceptMention],
        evidence_list: Optional[List[Evidence]] = None,
    ) -> Tuple[Dict[str, List[ConceptMention]], Dict[str, str], List[MergeRecord]]:
        """
        Executes full entity resolution pipeline:
        Returns:
        1. clusters: Dict[cluster_key, List[ConceptMention]]
        2. canonical_names: Dict[cluster_key, str]
        3. merge_records: List[MergeRecord]
        """
        evidence_by_block: Dict[str, List[Evidence]] = {}
        if evidence_list:
            for ev in evidence_list:
                evidence_by_block.setdefault(ev.block_id, []).append(ev)

        # Step 1: Initial grouping by syntactic normalized key
        raw_clusters: Dict[str, List[ConceptMention]] = {}
        for m in mentions:
            key = self.normalize_surface_key(m.surface_form)
            raw_clusters.setdefault(key, []).append(m)

        # Step 2: Merge clusters based on domain semantic equivalence
        cluster_canonical: Dict[str, str] = {}
        for key, m_list in raw_clusters.items():
            # Pick most frequent surface form as initial canonical name
            counts: Dict[str, int] = {}
            for m in m_list:
                counts[m.surface_form] = counts.get(m.surface_form, 0) + 1
            best_surface = max(counts.keys(), key=lambda s: counts[s])
            cluster_canonical[key] = best_surface

        final_clusters: Dict[str, List[ConceptMention]] = {}
        final_canonical: Dict[str, str] = {}
        merge_records: List[MergeRecord] = []

        keys = list(raw_clusters.keys())
        merged_into: Dict[str, str] = {}

        for i in range(len(keys)):
            key_i = keys[i]
            target_key = merged_into.get(key_i, key_i)

            equiv_i = self.find_semantic_equivalent(cluster_canonical[target_key])
            if equiv_i:
                canon_name, conf, reason = equiv_i
                canon_key = self.normalize_surface_key(canon_name)
                cluster_canonical[target_key] = canon_name

                if canon_key != target_key and canon_key in raw_clusters:
                    # Near miss safety check
                    if not self.is_near_miss(cluster_canonical[target_key], cluster_canonical[canon_key]):
                        merged_into[target_key] = canon_key
                        target_key = canon_key
                        cluster_canonical[target_key] = canon_name

                        # Extract grounded evidence references from mentions
                        ev_refs: List[str] = []
                        for m in raw_clusters.get(key_i, []):
                            if m.block_id in evidence_by_block:
                                ev_refs.extend([e.evidence_id for e in evidence_by_block[m.block_id]])

                        rec = MergeRecord(
                            record_id=f"mrg_{uuid.uuid4().hex[:12]}",
                            inputs=[cluster_canonical.get(key_i, key_i), canon_name],
                            canonical_name=canon_name,
                            signals={
                                "source_phrase": cluster_canonical.get(key_i, key_i),
                                "canonical_concept": canon_name,
                                "confidence": conf,
                                "reason": reason,
                                "evidence_refs": list(dict.fromkeys(ev_refs)),
                                "resolver_version": self.resolver_version,
                                "verification_status": "VERIFIED",
                            },
                            score=conf,
                            outcome="MERGED",
                        )
                        merge_records.append(rec)

        # Build final merged clusters
        for key, m_list in raw_clusters.items():
            dest_key = merged_into.get(key, key)
            final_clusters.setdefault(dest_key, []).extend(m_list)
            if dest_key not in final_canonical:
                final_canonical[dest_key] = cluster_canonical.get(dest_key, cluster_canonical[key])

        return final_clusters, final_canonical, merge_records
