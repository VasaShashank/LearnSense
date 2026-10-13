"""
Data models for Educational Resources, Video Transcripts, and Notation-Matched Recommendations.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class TranscriptSegment(BaseModel):
    """A timestamped segment of a video or audio transcript."""
    start_seconds: float
    end_seconds: float
    text: str
    concept_ids: List[str] = Field(default_factory=list)
    formulas_mentioned: List[str] = Field(default_factory=list)


class NotationVariant(BaseModel):
    """A symbol or notation mapping used in a resource."""
    symbol: str
    meaning: str
    canonical_symbol: str
    subject_domain: Optional[str] = None


class FormulaVariant(BaseModel):
    """A mathematical expression or equation representation."""
    raw_formula: str
    normalized_formula: str
    canonical_formula_id: Optional[str] = None
    variable_mappings: Dict[str, str] = Field(default_factory=dict)


class ResourceRecord(BaseModel):
    """
    Representation of an external educational resource (e.g. YouTube video, lecture clip).
    Maintains provenance, transcript data, concepts, notation variants, and formulas.
    """
    resource_id: str
    url: str
    provider: str = "youtube"
    title: str
    channel: str = ""
    duration_seconds: int = 0
    language: str = "en"
    transcript_available: bool = True
    transcript: List[TranscriptSegment] = Field(default_factory=list)
    concepts_covered: List[str] = Field(default_factory=list)
    prerequisite_concepts: List[str] = Field(default_factory=list)
    notation_variants: List[NotationVariant] = Field(default_factory=list)
    formulas: List[FormulaVariant] = Field(default_factory=list)
    difficulty: float = 0.5
    confidence: float = 1.0
    tags: List[str] = Field(default_factory=list)


class RecommendationRankingWeights(BaseModel):
    """Configurable weights for ranking candidate educational resources."""
    concept_match: float = 0.35
    notation_compatibility: float = 0.30
    prerequisite_relevance: float = 0.15
    learner_mastery_fit: float = 0.10
    evidence_quality: float = 0.10


class ResourceMatchResult(BaseModel):
    """
    Result of matching an educational resource against learner needs,
    including notation alignment, timestamp jumping point, and explainable score.
    """
    resource_id: str
    title: str
    url: str
    provider: str
    channel: str = ""
    duration_seconds: int = 0
    overall_score: float
    concept_score: float
    notation_score: float
    prerequisite_score: float
    pedagogical_fit_score: float
    recommended_timestamp_seconds: Optional[float] = None
    timestamp_end_seconds: Optional[float] = None
    matched_segment_text: Optional[str] = None
    notation_explanation: str = ""
    matched_formulas: List[str] = Field(default_factory=list)
    match_reasons: List[str] = Field(default_factory=list)
