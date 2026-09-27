"""
NLP Output & Confidence Validator for Taproot Phase 5.
Validates concept/relationship entity completeness, required fields, ID references, non-empty names,
uniqueness, and confidence thresholds.
"""

from typing import List, Dict, Set, Any, Tuple, Union
from phase2.models import Concept, Relationship, EducationalKnowledgeRepresentation
from phase5.config.phase5_config import phase5_config
from phase5.models.validation_result import RecoveryClassification, ValidationResult, ValidationStatus
from phase5.observability.validation_events import ValidationEventLogger


class NLPValidator:
    """Validates Phase 2 NLP extracted entities and confidence bounds."""

    def __init__(self, confidence_threshold: float = phase5_config.NLP_CONFIDENCE_THRESHOLD):
        self.confidence_threshold = confidence_threshold

    def validate_concepts(self, concepts: List[Concept], document_id: str = "") -> ValidationResult:
        result = ValidationResult(status=ValidationStatus.VALID, is_valid=True)
        seen_ids: Set[str] = set()
        seen_names: Set[str] = set()
        low_confidence_count = 0

        for idx, concept in enumerate(concepts):
            c_id = concept.concept_id
            c_name = concept.canonical_name.strip() if getattr(concept, "canonical_name", None) else getattr(concept, "name", "").strip()

            # 1. Required fields
            if not c_id:
                result.add_error(f"Concept at index {idx} has missing or empty concept_id.")
            elif c_id in seen_ids:
                result.add_error(f"Duplicate concept_id found: '{c_id}'.")
            else:
                seen_ids.add(c_id)

            if not c_name:
                result.add_error(f"Concept '{c_id}' has empty concept name.")
            else:
                norm_name = c_name.lower()
                if norm_name in seen_names:
                    result.add_warning(f"Concept '{c_id}' has duplicate normalized name '{c_name}'.")
                else:
                    seen_names.add(norm_name)

            # 2. Confidence check
            conf = concept.confidence.value if hasattr(concept.confidence, "value") else float(concept.confidence)
            if conf < self.confidence_threshold:
                low_confidence_count += 1
                result.add_warning(
                    f"Concept '{c_id}' ('{c_name}') has low confidence {conf:.2f} < {self.confidence_threshold}."
                )

        result.metadata["total_concepts"] = len(concepts)
        result.metadata["low_confidence_concepts"] = low_confidence_count

        if low_confidence_count > 0:
            result.suggested_action = "Reprocess/regenerate low-confidence NLP extractions bounded by MAX_NLP_RETRIES."
            if low_confidence_count > len(concepts) / 2 and result.is_valid:
                result.status = ValidationStatus.WARNING
                result.recovery_classification = RecoveryClassification.PARTIALLY_RECOVERABLE

        if result.is_valid:
            ValidationEventLogger.log_event(
                "nlp_concepts_validation_passed",
                result.status.value,
                f"Validated {len(concepts)} NLP concepts (low_confidence={low_confidence_count}).",
                document_id=document_id,
            )
        else:
            ValidationEventLogger.log_event(
                "nlp_concepts_validation_failed",
                "INVALID",
                f"NLP concept validation failed with {len(result.errors)} errors.",
                document_id=document_id,
            )

        return result

    def validate_relationships(
        self,
        relationships: List[Relationship],
        valid_concept_ids: Set[str],
        document_id: str = "",
    ) -> ValidationResult:
        result = ValidationResult(status=ValidationStatus.VALID, is_valid=True)
        seen_edges: Set[Tuple[str, str, str]] = set()

        for idx, rel in enumerate(relationships):
            src = rel.source
            tgt = rel.target
            rel_type = str(rel.type.value) if hasattr(rel.type, "value") else str(rel.type)

            # 1. Existence and non-empty checks
            if not src or not tgt:
                result.add_error(f"Relationship at index {idx} has empty source or target concept ID.")
                continue

            # 2. Self-referencing link
            if src == tgt:
                result.add_error(f"Self-referencing relationship detected for concept '{src}'.")
                continue

            # 3. Broken references
            if valid_concept_ids and src not in valid_concept_ids:
                result.add_error(f"Relationship source concept '{src}' does not exist in graph.")
            if valid_concept_ids and tgt not in valid_concept_ids:
                result.add_error(f"Relationship target concept '{tgt}' does not exist in graph.")

            # 4. Duplicate edges
            edge_tuple = (src, tgt, rel_type)
            if edge_tuple in seen_edges:
                result.add_warning(f"Duplicate edge detected: {src} -> {rel_type} -> {tgt}.")
            else:
                seen_edges.add(edge_tuple)

        result.metadata["total_relationships"] = len(relationships)
        result.metadata["unique_edges"] = len(seen_edges)

        return result
