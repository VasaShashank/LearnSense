"""
Central LLM Gateway for LearnSense / TAPROOT.
Implements Section 9 of TAPROOT master specification:
All production LLM calls go through one gateway.
The gateway owns:
- provider
- model
- timeout
- retry
- backoff
- rate limiting
- token budget
- request ID
- logging
- failure classification
- cache policy
- prompt version
- model version

Callers:
- semantic enrichment
- entity resolution
- relationship enrichment
- question generation
- learning content
- tutor
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from phase3.adapters.llm_adapter import (
    Phase3LLMAdapter,
    get_llm_adapter,
    reset_llm_adapter,
    set_llm_adapter,
)

CentralLLMGateway = Phase3LLMAdapter
get_central_llm_gateway = get_llm_adapter

__all__ = [
    "CentralLLMGateway",
    "Phase3LLMAdapter",
    "get_central_llm_gateway",
    "get_llm_adapter",
    "reset_llm_adapter",
    "set_llm_adapter",
]
