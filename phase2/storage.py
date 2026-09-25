"""
Immutable Storage Layout Manager & Version Migration Utilities.
Plan §22:
knowledge/
  document_id/
    pipeline_version/
      manifest.json
      concepts/ ...
"""

import json
import os
from typing import Any, Dict, List
from phase2.models import EducationalKnowledgeRepresentation, IdMapEntry


class KnowledgeStorageManager:
    def __init__(self, base_dir: str = "knowledge"):
        self.base_dir = base_dir

    def store_knowledge_representation(self, ekr: EducationalKnowledgeRepresentation) -> str:
        doc_dir = os.path.join(self.base_dir, ekr.source_document_id, ekr.pipeline_version)
        os.makedirs(doc_dir, exist_ok=True)

        data = ekr.model_dump(mode="json")

        # Save primary export file
        export_path = os.path.join(doc_dir, "export.json")
        with open(export_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        # Save manifest.json
        manifest = {
            "knowledge_document_id": ekr.knowledge_document_id,
            "source_document_id": ekr.source_document_id,
            "schema_version": ekr.schema_version,
            "pipeline_version": ekr.pipeline_version,
            "status": ekr.status,
            "qc_report": ekr.qc_report,
            "coverage_report": ekr.coverage_report
        }
        with open(os.path.join(doc_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        # Active version pointer
        active_pointer = os.path.join(self.base_dir, ekr.source_document_id, "active")
        with open(active_pointer, "w", encoding="utf-8") as f:
            f.write(ekr.pipeline_version)

        return doc_dir


def generate_id_map_migration(old_ekr: EducationalKnowledgeRepresentation, new_ekr: EducationalKnowledgeRepresentation) -> List[IdMapEntry]:
    """Computes id_map migration entries between reprocessing runs."""
    id_map = []
    old_concepts = {c.canonical_name.lower(): c.concept_id for c in old_ekr.concepts}
    new_concepts = {c.canonical_name.lower(): c.concept_id for c in new_ekr.concepts}

    for name, old_id in old_concepts.items():
        if name in new_concepts:
            new_id = new_concepts[name]
            id_map.append(
                IdMapEntry(
                    old_id=old_id,
                    new_id=new_id,
                    relation="same" if old_id == new_id else "merged_into",
                    confidence=1.0
                )
            )
        else:
            id_map.append(
                IdMapEntry(
                    old_id=old_id,
                    new_id=old_id,
                    relation="removed",
                    confidence=1.0
                )
            )

    return id_map
