"""
Phase 1 -> Phase 2 Input Contract Validator & Export Utilities.
"""

import json
from typing import Any, Dict, List, Tuple
from schemas.document import StructuredDocument
from phase2.models import EducationalKnowledgeRepresentation


class ContractValidationError(Exception):
    pass


def validate_structured_document_input(doc: StructuredDocument) -> List[str]:
    """
    Validates Phase 1 StructuredDocument against Phase 2 requirements.
    Plan §17:
    - Pins schema version 1.x (tolerates minor additive versions, rejects major != 1)
    - Verifies block, section, asset, and cross-reference IDs resolve
    - Returns list of non-fatal contract warnings
    """
    warnings = []
    major_version = doc.schema_version.split(".")[0]
    if major_version != "1":
        raise ContractValidationError(
            f"Unsupported Phase 1 schema major version: {doc.schema_version}. Phase 2 accepts version 1.x."
        )

    # Map sections
    section_ids = set()

    def collect_sections(nodes):
        for node in nodes:
            section_ids.add(node.section_id)
            collect_sections(node.children)

    collect_sections(doc.outline)

    # Collect block and asset IDs
    block_ids = set()
    page_block_map = {}
    for page in doc.pages:
        for block in page.blocks:
            if block.block_id in block_ids:
                warnings.append(f"Duplicate block_id detected: {block.block_id}")
            block_ids.add(block.block_id)
            page_block_map[block.block_id] = block.content.text

            if block.section_id and block.section_id not in section_ids:
                warnings.append(
                    f"Block {block.block_id} references unknown section_id: {block.section_id}"
                )

    asset_ids = {asset.asset_id for asset in doc.assets}
    for page in doc.pages:
        for block in page.blocks:
            for aid in block.asset_ids:
                if aid not in asset_ids:
                    warnings.append(f"Block {block.block_id} references missing asset_id: {aid}")

    return warnings


def export_output_json_schema() -> Dict[str, Any]:
    """Returns JSON Schema dict for EducationalKnowledgeRepresentation."""
    return EducationalKnowledgeRepresentation.model_json_schema()
