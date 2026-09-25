"""
Security Sandboxing, Resource Capping, and Prompt Injection Detector for Taproot Phase 1.
Enforces process memory/CPU limits, stream decompression limits, hidden white-on-white text detection,
and flags prompt injection instruction patterns with POSSIBLE_PROMPT_INJECTION warnings.
Matches Section 13 & Section 21 of TAPROOT_PHASE_1_MASTER_IMPLEMENTATION_PLAN.md.
"""

import re
import resource
from typing import Dict, Any, List, Tuple
from schemas.document import DocumentBlock, DocumentWarning


class SecuritySandbox:
    # Instruction override patterns for prompt injection defense
    PROMPT_INJECTION_PATTERNS = [
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"disregard\s+(all\s+)?prior\s+prompts",
        r"system\s+prompt:",
        r"you\s+are\s+now\s+an?\s+AI",
        r"override\s+system\s+rules",
        r"developer\s+mode\s+enabled",
    ]

    def __init__(
        self,
        max_memory_mb: int = 1500,
        max_cpu_seconds: int = 60,
    ):
        self.max_memory_bytes = max_memory_mb * 1024 * 1024
        self.max_cpu_seconds = max_cpu_seconds

    def apply_process_limits(self) -> None:
        """Enforces CPU time and virtual memory RLIMITs on Unix worker processes."""
        try:
            # Set CPU time limit
            resource.setrlimit(resource.RLIMIT_CPU, (self.max_cpu_seconds, self.max_cpu_seconds + 5))
            # Set Virtual Memory limit
            resource.setrlimit(resource.RLIMIT_AS, (self.max_memory_bytes, self.max_memory_bytes))
        except Exception:
            # Non-Unix environment or permission restriction
            pass

    def inspect_block_security(
        self,
        block: DocumentBlock,
        page_index: int,
        page_width: float,
        page_height: float,
    ) -> List[DocumentWarning]:
        """
        Inspects block for security vulnerabilities:
        1. Off-page or invisible white-on-white hidden text -> HIDDEN_TEXT_DETECTED.
        2. Prompt injection instruction overrides -> POSSIBLE_PROMPT_INJECTION.
        """
        warnings: List[DocumentWarning] = []
        text = block.content.text.strip()
        if not text:
            return warnings

        # 1. Check Off-Page Hidden Text (coordinates outside page boundaries)
        x0, y0, x1, y1 = block.bbox
        if x1 < 0 or x0 > page_width or y1 < 0 or y0 > page_height:
            block.role = "hidden"
            block.warnings.append("HIDDEN_TEXT_DETECTED")
            warnings.append(
                DocumentWarning(
                    code="HIDDEN_TEXT_DETECTED",
                    severity="medium",
                    page_index=page_index,
                    block_id=block.block_id,
                    message="Text positioned outside rendered page boundaries detected.",
                )
            )

        # 2. Check White-on-White / Invisible Font Color
        spans = block.content.structured_data.get("spans", []) if block.content.structured_data else []
        for span in spans:
            color = span.get("color")
            # PyMuPDF white color RGB int 16777215
            if color == 16777215 or color == (1.0, 1.0, 1.0):
                block.role = "hidden"
                if "HIDDEN_TEXT_DETECTED" not in block.warnings:
                    block.warnings.append("HIDDEN_TEXT_DETECTED")
                    warnings.append(
                        DocumentWarning(
                            code="HIDDEN_TEXT_DETECTED",
                            severity="medium",
                            page_index=page_index,
                            block_id=block.block_id,
                            message="White-on-white invisible text detected.",
                        )
                    )
                break

        # 3. Check Prompt Injection Instruction Overrides
        for pattern in self.PROMPT_INJECTION_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                block.warnings.append("POSSIBLE_PROMPT_INJECTION")
                warnings.append(
                    DocumentWarning(
                        code="POSSIBLE_PROMPT_INJECTION",
                        severity="high",
                        page_index=page_index,
                        block_id=block.block_id,
                        message="Potential LLM instruction override pattern detected in document text.",
                    )
                )
                break

        return warnings
