"""
Golden set evaluation script for Phase 2 concept and relationship extraction.
Plan §24 & §25.
"""

from typing import Any, Dict, List, Set, Tuple
from phase2.models import EducationalKnowledgeRepresentation


def evaluate_knowledge_representation(
    ekr: EducationalKnowledgeRepresentation,
    golden_data: Dict[str, Any]
) -> Dict[str, float]:
    extracted_concepts: Set[str] = {c.canonical_name.lower() for c in ekr.concepts}
    golden_concepts: Set[str] = {c.lower() for c in golden_data.get("concepts", [])}

    tp_concepts = len(extracted_concepts & golden_concepts)
    fp_concepts = len(extracted_concepts - golden_concepts)
    fn_concepts = len(golden_concepts - extracted_concepts)

    prec_c = tp_concepts / (tp_concepts + fp_concepts) if (tp_concepts + fp_concepts) > 0 else 1.0
    rec_c = tp_concepts / (tp_concepts + fn_concepts) if (tp_concepts + fn_concepts) > 0 else 1.0
    f1_c = (2 * prec_c * rec_c) / (prec_c + rec_c) if (prec_c + rec_c) > 0 else 0.0

    return {
        "concept_precision": round(prec_c, 4),
        "concept_recall": round(rec_c, 4),
        "concept_f1": round(f1_c, 4),
        "tp": tp_concepts,
        "fp": fp_concepts,
        "fn": fn_concepts
    }
