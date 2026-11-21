"""Phase 3 Migration Adapter Module — Re-export from authoritative Person 3 engine."""

from src.migration_adapter import *
from src.migration_adapter import (
    CanonicalConceptMigrationAdapter,
    ConceptMigrationRecord,
    CURRICULUM_ID,
    CURRICULUM_VERSION,
    CURRICULUM_FINGERPRINT,
    MAT_CON_LEGACY,
    MAT_CON_CANONICAL,
    PHY_OPT_LEGACY,
    PHY_OPT_RAY_CANONICAL,
    PHY_OPT_WAVE_CANONICAL,
    DEPRECATED_IDS,
    EXCLUDED_FROM_JEE_MAIN_2027,
    get_migration_adapter,
)
