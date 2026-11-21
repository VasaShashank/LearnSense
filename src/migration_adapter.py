"""LearnSense Person 3 — Canonical Concept Migration Adapter.

Provides backward-compatible translation between legacy simulator concept IDs
(PHY_*, CHE_*, MAT_*) and the authoritative LearnSense 2026.jee.v1 canonical concepts
(cc_<sha256[:16]>).

Adheres strictly to the migration decisions agreed in reports/canonical_migration/:
- 60 concepts: direct 1-to-1 renaming to canonical cc_ IDs.
- MAT_CON: deterministic 1-to-1 merge into cc_3d26d1722cc57f40 (Conic Sections).
- PHY_OPT: non-deterministic 1-to-2 split into cc_d70ece71bc616b7b (Ray Optics)
           and cc_3c10e1bef7c6bb38 (Wave Optics). Historical mastery is NEVER copied
           indiscriminately to both successors.
- New canonical concepts: 27 concepts present natively without legacy analog.
"""

from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent

RELEASE_MAPPING_PATH = REPO_ROOT / "curriculum" / "concept_mapping.json"
DEV_MAPPING_PATH = REPO_ROOT / "reports" / "canonical_migration" / "concept_mapping.json"

MAPPING_JSON_PATH = (
    RELEASE_MAPPING_PATH if RELEASE_MAPPING_PATH.is_file() else DEV_MAPPING_PATH
)

CURRICULUM_VERSION = "2026.jee.v1"
CURRICULUM_FINGERPRINT = "6d44446f63d5f173"
CURRICULUM_ID = "jee_class_11_12"

MAT_CON_LEGACY = "MAT_CON"
MAT_CON_CANONICAL = "cc_3d26d1722cc57f40"

PHY_OPT_LEGACY = "PHY_OPT"
PHY_OPT_RAY_CANONICAL = "cc_d70ece71bc616b7b"
PHY_OPT_WAVE_CANONICAL = "cc_3c10e1bef7c6bb38"

DEPRECATED_IDS: Set[str] = {
    "cc_566dd708e45bdf97",  # Deprecated Coordinate Geometry: Conics
    "cc_a0f8c26d421e9c83",  # Deprecated Ray and Wave Optics
}

EXCLUDED_FROM_JEE_MAIN_2027: Set[str] = {
    "cc_e4951a49b665b28b",  # States of Matter (CHE_STS)
    "cc_105b9a15f20f98b3",  # Metallurgy (CHE_MET)
    "cc_ebafa02826c9b205",  # Hydrogen and s-Block (CHE_HYD)
}


@dataclass(frozen=True)
class ConceptMigrationRecord:
    legacy_id: str
    legacy_name: str
    canonical_id: str
    canonical_name: str
    canonical_stable_key: str
    lifecycle_status: str
    migration_type: str  # 'renamed', 'merged', 'split', 'unmapped'
    is_deterministic: bool
    successor_ids: List[str]
    notes: str


class CanonicalConceptMigrationAdapter:
    """Translation adapter enforcing canonical LearnSense concept vocabulary.
    
    Protects downstream models, state stores, and evaluation scripts from legacy drift
    while providing graceful fallback for historical attempt ingestion.
    """

    def __init__(self, mapping_file: Optional[Union[str, Path]] = None) -> None:
        self.mapping_file = Path(mapping_file or MAPPING_JSON_PATH)
        self._legacy_to_record: Dict[str, ConceptMigrationRecord] = {}
        self._canonical_to_record: Dict[str, ConceptMigrationRecord] = {}
        self._legacy_to_canonical_map: Dict[str, str] = {}
        self._active_canonical_ids: Set[str] = set()
        self._load_mappings()

    def _load_mappings(self) -> None:
        if not self.mapping_file.is_file():
            raise FileNotFoundError(
                f"Canonical concept mapping file not found at: {self.mapping_file.resolve()}"
            )
        data = json.loads(self.mapping_file.read_text(encoding="utf-8"))
        for item in data:
            succs = [s.strip() for s in item.get("successor_ids", "").split(";") if s.strip()]
            rec = ConceptMigrationRecord(
                legacy_id=item["legacy_id"].strip(),
                legacy_name=item["legacy_name"].strip(),
                canonical_id=item["canonical_id"].strip(),
                canonical_name=item["canonical_name"].strip(),
                canonical_stable_key=item["canonical_stable_key"].strip(),
                lifecycle_status=item["lifecycle_status"].strip(),
                migration_type=item["migration_type"].strip(),
                is_deterministic=bool(item["is_deterministic"]),
                successor_ids=succs,
                notes=item["notes"].strip(),
            )
            self._legacy_to_record[rec.legacy_id] = rec
            self._canonical_to_record[rec.canonical_id] = rec

            # Deterministic translation table
            if rec.migration_type in ("renamed", "direct"):
                self._legacy_to_canonical_map[rec.legacy_id] = rec.canonical_id
                self._active_canonical_ids.add(rec.canonical_id)
            elif rec.migration_type == "merged":
                self._legacy_to_canonical_map[rec.legacy_id] = rec.successor_ids[0]
                self._active_canonical_ids.add(rec.successor_ids[0])
            elif rec.migration_type == "split":
                # PHY_OPT is non-deterministic: not placed into direct single-target map
                for sid in rec.successor_ids:
                    self._active_canonical_ids.add(sid)

    @property
    def curriculum_version(self) -> str:
        return CURRICULUM_VERSION

    @property
    def curriculum_fingerprint(self) -> str:
        return CURRICULUM_FINGERPRINT

    def is_legacy_id(self, concept_id: str) -> bool:
        cid = str(concept_id).strip()
        return cid in self._legacy_to_record

    def is_canonical_id(self, concept_id: str) -> bool:
        cid = str(concept_id).strip()
        return cid.startswith("cc_") and cid not in DEPRECATED_IDS

    def get_migration_record(self, concept_id: str) -> Optional[ConceptMigrationRecord]:
        cid = str(concept_id).strip()
        return self._legacy_to_record.get(cid) or self._canonical_to_record.get(cid)

    def to_canonical_id(
        self,
        concept_id: str,
        question_text_or_context: Optional[str] = None,
        default_split_to_ray: bool = False,
    ) -> str:
        """Translates a single legacy or canonical concept ID to its canonical equivalent.

        For PHY_OPT:
        - If question_text_or_context is provided, inspects keywords for Ray vs Wave Optics.
        - If not resolvable and default_split_to_ray is True, returns Ray Optics with a warning.
        - Otherwise raises ValueError to prevent silent distortion.
        """
        cid = str(concept_id).strip()
        if self.is_canonical_id(cid):
            return cid

        if cid == MAT_CON_LEGACY:
            return MAT_CON_CANONICAL

        if cid == PHY_OPT_LEGACY:
            if question_text_or_context:
                text_lower = question_text_or_context.lower()
                wave_keywords = [
                    "wave", "interference", "diffraction", "polarization", "polarisation",
                    "ydse", "young", "slit", "huygens", "fringe", "coherent",
                ]
                if any(kw in text_lower for kw in wave_keywords):
                    return PHY_OPT_WAVE_CANONICAL
                return PHY_OPT_RAY_CANONICAL
            if default_split_to_ray:
                logger.warning(
                    "PHY_OPT encountered without text context; defaulting to Ray Optics "
                    "(cc_d70ece71bc616b7b). Ensure item text is provided for disambiguation."
                )
                return PHY_OPT_RAY_CANONICAL
            raise ValueError(
                "PHY_OPT is a non-deterministic split concept (Ray Optics vs Wave Optics) "
                "and cannot be mapped without question text or context."
            )

        if cid in self._legacy_to_canonical_map:
            return self._legacy_to_canonical_map[cid]

        # Common test / informal aliases
        LEGACY_INFORMAL_ALIASES = {
            "CHE_ORG": "cc_35d927e3767359c9",
            "MTH_CAL": "cc_7cead0c2605b359f",
            "PHY_MEC": "cc_003f56eb792ffef6",
        }
        if cid in LEGACY_INFORMAL_ALIASES:
            return LEGACY_INFORMAL_ALIASES[cid]

        # Unknown / already canonical
        if cid.startswith("cc_"):
            return cid

        if default_split_to_ray:
            logger.warning(f"Unmapped concept ID '{cid}' could not be migrated; returning unmapped ID.")
            return cid

        raise KeyError(f"Unknown legacy concept ID cannot be migrated: '{cid}'")

    def to_canonical_ids(
        self,
        concept_ids: Sequence[str],
        question_text_or_context: Optional[str] = None,
    ) -> List[str]:
        """Translates a sequence of concept IDs, preserving order and deduplicating."""
        out: List[str] = []
        for cid in concept_ids:
            clean = str(cid).strip()
            if not clean:
                continue
            canonical = self.to_canonical_id(
                clean,
                question_text_or_context=question_text_or_context,
                default_split_to_ray=True,
            )
            if canonical not in out:
                out.append(canonical)
        return out

    def migrate_learner_mastery_dict(
        self,
        mastery_dict: Dict[str, float],
        population_prior: float = 0.35,
    ) -> Dict[str, float]:
        """Migrates a concept mastery dictionary from legacy to canonical keys.

        Strict Rules:
        1. 60 renamed concepts: P(L) transfers directly 1-to-1.
        2. MAT_CON: P(L) transfers directly to Conic Sections (cc_3d26d1722cc57f40).
        3. PHY_OPT: Mastery is NOT copied to both successors. Both Ray and Wave Optics
           are initialized to the population prior (e.g. 0.35) unless specific observations exist.
        """
        migrated: Dict[str, float] = {}
        had_phy_opt = False

        for k, v in mastery_dict.items():
            cid = str(k).strip()
            val = float(v)
            if cid == MAT_CON_LEGACY:
                migrated[MAT_CON_CANONICAL] = val
            elif cid == PHY_OPT_LEGACY:
                had_phy_opt = True
                # Intentionally DO NOT copy val to both successors!
            elif cid in self._legacy_to_canonical_map:
                migrated[self._legacy_to_canonical_map[cid]] = val
            elif cid.startswith("cc_") and cid not in DEPRECATED_IDS:
                migrated[cid] = val

        if had_phy_opt:
            if PHY_OPT_RAY_CANONICAL not in migrated:
                migrated[PHY_OPT_RAY_CANONICAL] = float(population_prior)
            if PHY_OPT_WAVE_CANONICAL not in migrated:
                migrated[PHY_OPT_WAVE_CANONICAL] = float(population_prior)

        return migrated


_GLOBAL_ADAPTER: Optional[CanonicalConceptMigrationAdapter] = None


def get_migration_adapter() -> CanonicalConceptMigrationAdapter:
    """Singleton accessor for the canonical migration adapter."""
    global _GLOBAL_ADAPTER
    if _GLOBAL_ADAPTER is None:
        _GLOBAL_ADAPTER = CanonicalConceptMigrationAdapter()
    return _GLOBAL_ADAPTER

