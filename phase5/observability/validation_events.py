"""
Structured Observability and Validation Event Logger for Taproot Phase 5.
Logs validation, retry, and recovery events with context identifiers.
"""

import logging
import json
from typing import Any, Dict, Optional

logger = logging.getLogger("taproot.phase5.observability")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class ValidationEventLogger:
    """Logs structured JSON/text validation events with diagnostic metadata."""

    @staticmethod
    def log_event(
        event_name: str,
        status: str,
        message: str,
        document_id: Optional[str] = None,
        subject_id: Optional[str] = None,
        learner_id: Optional[str] = None,
        concept_id: Optional[str] = None,
        question_id: Optional[str] = None,
        attempt_id: Optional[str] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
        level: int = logging.INFO,
    ):
        event_data = {
            "event": event_name,
            "status": status,
            "message": message,
            "context": {
                "document_id": document_id,
                "subject_id": subject_id,
                "learner_id": learner_id,
                "concept_id": concept_id,
                "question_id": question_id,
                "attempt_id": attempt_id,
            },
            "metadata": extra_metadata or {},
        }
        event_data["context"] = {k: v for k, v in event_data["context"].items() if v is not None}

        log_msg = f"{event_name.upper()} | Status: {status} | {message} | Context: {json.dumps(event_data['context'])}"
        logger.log(level, log_msg)
