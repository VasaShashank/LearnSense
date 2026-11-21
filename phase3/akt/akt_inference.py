"""Phase 3 AKT Inference Module — Re-export from authoritative Person 3 engine."""

from src.akt_inference import *
from src.akt_inference import (
    AKTMasteryInferenceService,
    LearnerInteraction,
    VocabularyWrapper,
    LegacyV4AKTMasteryInferenceService,
    RELEASE_CHECKPOINT_PATH,
    RELEASE_VOCABULARY_PATH,
    AUTHORITATIVE_CHECKPOINT_PATH,
    AUTHORITATIVE_VOCABULARY_PATH,
    AUTHORITATIVE_CHECKPOINT_SHA256,
    DEFAULT_MASTERY_THRESHOLD,
    POPULATION_PRIOR_MASTERY,
)
