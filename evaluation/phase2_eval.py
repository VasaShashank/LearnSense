"""
Golden set evaluation script for Phase 2 concept and relationship extraction.
Plan §24 & §25.
Extended for source fidelity across all formats (PDF, PPTX, DOCX, MD/TXT).
"""

from typing import Any, Dict, List, Optional, Set, Tuple
from phase2.models import EducationalKnowledgeRepresentation


def evaluate_knowledge_representation(
    ekr: EducationalKnowledgeRepresentation,
    golden_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Evaluates an extracted EducationalKnowledgeRepresentation (EKR) against
    a golden benchmark containing expected concepts, definitions, and relationships.
    """
    extracted_concepts: Set[str] = {c.canonical_name.lower().strip() for c in ekr.concepts}
    golden_concepts: Set[str] = {c.lower().strip() for c in golden_data.get("concepts", [])}

    tp_concepts = len(extracted_concepts & golden_concepts)
    fp_concepts = len(extracted_concepts - golden_concepts)
    fn_concepts = len(golden_concepts - extracted_concepts)

    prec_c = tp_concepts / (tp_concepts + fp_concepts) if (tp_concepts + fp_concepts) > 0 else 1.0
    rec_c = tp_concepts / (tp_concepts + fn_concepts) if (tp_concepts + fn_concepts) > 0 else 1.0
    f1_c = (2 * prec_c * rec_c) / (prec_c + rec_c) if (prec_c + rec_c) > 0 else 0.0

    # 1. Definition Evaluation
    # golden_defs is a dict: {term: expected_substring_in_definition}
    golden_defs: Dict[str, str] = {
        k.lower().strip(): v.lower().strip()
        for k, v in golden_data.get("definitions", {}).items()
    }
    def_matches = 0
    concept_map = {c.canonical_name.lower().strip(): c for c in ekr.concepts}
    for term, expected_substring in golden_defs.items():
        matched_concept = next(
            (c for name, c in concept_map.items() if term in name or name in term),
            None,
        )
        if matched_concept and matched_concept.description:
            if not expected_substring or expected_substring in matched_concept.description.lower():
                def_matches += 1
    def_rec = def_matches / len(golden_defs) if golden_defs else 1.0

    # 2. Relationship Evaluation
    # golden_rels is a list of dicts: [{"source": str, "target": str, "type": Optional[str]}]
    golden_rels = golden_data.get("relationships", [])
    id_to_name = {c.concept_id: c.canonical_name.lower().strip() for c in ekr.concepts}
    extracted_rel_triples: Set[Tuple[str, str, str]] = set()
    for rel in ekr.relationships:
        src = id_to_name.get(rel.source, "")
        tgt = id_to_name.get(rel.target, "")
        rtype = rel.type.value if hasattr(rel.type, "value") else str(rel.type)
        if src and tgt:
            extracted_rel_triples.add((src, rtype, tgt))

    rel_tp = 0
    for gr in golden_rels:
        g_src = gr.get("source", "").lower().strip()
        g_tgt = gr.get("target", "").lower().strip()
        g_type = gr.get("type")
        matched = any(
            (g_src in e_src or e_src in g_src)
            and (g_tgt in e_tgt or e_tgt in g_tgt)
            and (not g_type or g_type.lower() == e_type.lower())
            for (e_src, e_type, e_tgt) in extracted_rel_triples
        )
        if matched:
            rel_tp += 1
    rel_rec = rel_tp / len(golden_rels) if golden_rels else 1.0

    return {
        "concept_precision": round(prec_c, 4),
        "concept_recall": round(rec_c, 4),
        "concept_f1": round(f1_c, 4),
        "definition_recall": round(def_rec, 4),
        "relationship_recall": round(rel_rec, 4),
        "tp": tp_concepts,
        "fp": fp_concepts,
        "fn": fn_concepts,
        "total_extracted_concepts": len(extracted_concepts),
        "total_extracted_relationships": len(ekr.relationships),
    }
