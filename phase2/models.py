"""
Phase 2 Pydantic V2 Schemas for Educational Knowledge Representation.
Matches Output Schema specified in Section 13 and 14 of Taproot Phase 2 Plan v2.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, ConfigDict


class ScopeEnum(str, Enum):
    EDUCATIONAL = "educational"
    MENTIONED_ONLY = "mentioned_only"


class ConceptStatusEnum(str, Enum):
    ACTIVE = "active"
    AMBIGUOUS = "ambiguous"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"


class RelationshipStatusEnum(str, Enum):
    ACCEPTED = "accepted"
    CANDIDATE = "candidate"
    UNSUPPORTED = "unsupported"
    FLAGGED_CONFLICT = "flagged_conflict"
    FLAGGED_CYCLE = "flagged_cycle"
    REJECTED = "rejected"


class EvidenceLevelEnum(str, Enum):
    EXPLICIT = "EXPLICIT"
    STRONG_INFERRED = "STRONG_INFERRED"
    WEAK_INFERRED = "WEAK_INFERRED"
    UNCERTAIN = "UNCERTAIN"


class EvidenceKindEnum(str, Enum):
    EXPLICIT_STATEMENT = "explicit_statement"
    STATED_DEPENDENCY = "stated_dependency"
    DEFINITION_PATTERN = "definition_pattern"
    GLOSSARY_ENTRY = "glossary_entry"
    DEFINITION_DEPENDENCY = "definition_dependency"
    DERIVATION_USAGE = "derivation_usage"
    CROSS_REFERENCE = "cross_reference"
    SECTION_ORDER = "section_order"
    COOCCURRENCE = "cooccurrence"
    LEARNING_OBJECTIVE = "learning_objective"
    MODEL_INFERENCE = "model_inference"


class SectionSemanticStatusEnum(str, Enum):
    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


class ConceptTypeEnum(str, Enum):
    CONCEPT = "concept"
    PRINCIPLE = "principle"
    LAW = "law"
    THEOREM = "theorem"
    QUANTITY = "quantity"
    ENTITY = "entity"
    METHOD = "method"
    PROCESS = "process"
    STRUCTURE = "structure"
    PROPERTY = "property"


class ActionCategoryEnum(str, Enum):
    RECALL = "recall"
    IDENTIFY = "identify"
    CALCULATE = "calculate"
    SOLVE = "solve"
    DERIVE = "derive"
    APPLY = "apply"
    COMPARE = "compare"
    CLASSIFY = "classify"
    EXPLAIN = "explain"
    INTERPRET = "interpret"
    PROVE = "prove"
    CONSTRUCT = "construct"


class RelationshipTypeEnum(str, Enum):
    PART_OF = "part_of"
    IS_A = "is_a"
    INSTANCE_OF = "instance_of"
    DERIVED_FROM = "derived_from"
    PREREQUISITE_OF = "prerequisite_of"
    CONTRASTS_WITH = "contrasts_with"
    SIMILAR_TO = "similar_to"
    RELATED_TO = "related_to"


# Data Models

class DocumentProfile(BaseModel):
    genre: str = "textbook"
    domain_hint: Optional[str] = None
    level_hint: Optional[str] = None
    languages: List[str] = Field(default_factory=lambda: ["en"])


class SectionStatus(BaseModel):
    section_id: str
    semantic_status: SectionSemanticStatusEnum = SectionSemanticStatusEnum.OK
    warnings: List[str] = Field(default_factory=list)


class TextSpan(BaseModel):
    field: str = "normalized_text"
    start: int = Field(..., ge=0)
    end: int = Field(..., ge=0)


class Evidence(BaseModel):
    evidence_id: str
    block_id: str
    span: TextSpan
    excerpt: str
    level: EvidenceLevelEnum
    kind: EvidenceKindEnum
    source_confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ConfidenceBreakdown(BaseModel):
    value: float = Field(..., ge=0.0, le=1.0)
    components: Optional[Dict[str, float]] = None


class Alias(BaseModel):
    text: str
    language: str = "en"


class UnitLink(BaseModel):
    unit_id: str
    link: str  # defines, explains, demonstrates, assesses, uses, mentions


class ConceptExtractionInfo(BaseModel):
    method: str = "hybrid"
    pipeline_version: str = "2.0.0"


class Concept(BaseModel):
    concept_id: str
    canonical_name: str
    aliases: List[Alias] = Field(default_factory=list)
    type: ConceptTypeEnum = ConceptTypeEnum.CONCEPT
    scope: ScopeEnum = ScopeEnum.EDUCATIONAL
    status: ConceptStatusEnum = ConceptStatusEnum.ACTIVE
    mention_ids: List[str] = Field(default_factory=list)
    skill_ids: List[str] = Field(default_factory=list)
    unit_links: List[UnitLink] = Field(default_factory=list)
    confidence: ConfidenceBreakdown
    evidence_ids: List[str] = Field(default_factory=list)
    extraction: ConceptExtractionInfo = Field(default_factory=ConceptExtractionInfo)


class ConceptMention(BaseModel):
    mention_id: str
    concept_id: str
    block_id: str
    span: TextSpan
    surface_form: str
    language: str = "en"
    unit_id: Optional[str] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class Skill(BaseModel):
    skill_id: str
    action: ActionCategoryEnum
    statement: str
    concept_ids: List[str] = Field(default_factory=list)
    source_kind: str = "inferred"  # explicit_objective, procedure_text, exercise_derived, inferred
    confidence: ConfidenceBreakdown
    evidence_ids: List[str] = Field(default_factory=list)


class SourceSpanReference(BaseModel):
    block_id: str
    span: TextSpan


class ConceptLink(BaseModel):
    concept_id: str
    link: str


class EducationalUnit(BaseModel):
    unit_id: str
    unit_type: str  # definition, explanation, example, worked_example, etc.
    section_id: str
    source: List[SourceSpanReference] = Field(default_factory=list)
    parent_unit_id: Optional[str] = None
    concept_links: List[ConceptLink] = Field(default_factory=list)


class SkillLink(BaseModel):
    skill_id: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    basis: str = "verb_and_concepts"


class AssessableItem(BaseModel):
    item_id: str
    item_type: str = "exercise"  # exercise, question, worked_example_problem
    unit_id: str
    answer_unit_id: Optional[str] = None
    concept_ids: List[str] = Field(default_factory=list)
    skill_links: List[SkillLink] = Field(default_factory=list)
    confidence: Optional[ConfidenceBreakdown] = None
    evidence_ids: List[str] = Field(default_factory=list)


class Formula(BaseModel):
    formula_id: str
    representation: str
    source_unit_id: str
    concept_ids: List[str] = Field(default_factory=list)
    variables: Dict[str, str] = Field(default_factory=dict)


class Relationship(BaseModel):
    relationship_id: str
    source: str  # concept_id
    type: RelationshipTypeEnum
    target: str  # concept_id
    status: RelationshipStatusEnum = RelationshipStatusEnum.ACCEPTED
    evidence_level: EvidenceLevelEnum
    confidence: ConfidenceBreakdown
    evidence_ids: List[str] = Field(default_factory=list)
    flags: List[str] = Field(default_factory=list)


class Views(BaseModel):
    trusted: Dict[str, Any] = Field(default_factory=lambda: {"policy_version": "1", "relationship_ids": []})
    full: Optional[Dict[str, Any]] = None


class MergeRecord(BaseModel):
    record_id: str
    inputs: List[str]
    canonical_name: str
    signals: Dict[str, Any]
    score: float
    outcome: str


class IdMapEntry(BaseModel):
    old_id: str
    new_id: str
    relation: str  # same, merged_into, split_into, removed
    confidence: float = 1.0


class WarningMessage(BaseModel):
    code: str
    scope: str
    message: str


class EducationalKnowledgeRepresentation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    knowledge_document_id: str
    source_document_id: str
    schema_version: str = "2.0.0"
    pipeline_version: str = "2.0.0"
    source_schema_version: str = "1.0.0"
    status: str = "completed"
    document_profile: DocumentProfile = Field(default_factory=DocumentProfile)

    sections: List[SectionStatus] = Field(default_factory=list)
    evidence: List[Evidence] = Field(default_factory=list)
    mentions: List[ConceptMention] = Field(default_factory=list)
    concepts: List[Concept] = Field(default_factory=list)
    skills: List[Skill] = Field(default_factory=list)
    educational_units: List[EducationalUnit] = Field(default_factory=list)
    formulas: List[Formula] = Field(default_factory=list)
    assessable_items: List[AssessableItem] = Field(default_factory=list)
    relationships: List[Relationship] = Field(default_factory=list)
    views: Views = Field(default_factory=Views)
    merge_records: List[MergeRecord] = Field(default_factory=list)
    id_map: List[IdMapEntry] = Field(default_factory=list)
    qc_report: Dict[str, Any] = Field(default_factory=dict)
    coverage_report: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[WarningMessage] = Field(default_factory=list)
