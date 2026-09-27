"""
Retry Policy Manager for Taproot Phase 5.
Enforces max attempt limits and exponential backoff / attempt tracking.
"""

import time
from typing import Callable, Any, Optional, Type, Tuple
from phase5.config.phase5_config import phase5_config
from phase5.observability.validation_events import ValidationEventLogger


class RetryPolicy:
    """Encapsulates bounded retries with logging for transient or recoverable operations."""

    def __init__(self, max_retries: int = phase5_config.MAX_RECOVERY_ATTEMPTS, delay_seconds: float = 0.1):
        self.max_retries = max_retries
        self.delay_seconds = delay_seconds

    def execute(
        self,
        operation_name: str,
        func: Callable[[], Any],
        retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,),
        context_id: Optional[str] = None,
    ) -> Any:
        attempts = 0
        while True:
            attempts += 1
            try:
                return func()
            except retryable_exceptions as e:
                ValidationEventLogger.log_event(
                    event_name="operation_attempt_failed",
                    status="RETRYING",
                    message=f"{operation_name} failed on attempt {attempts}/{self.max_retries + 1}: {str(e)}",
                    document_id=context_id,
                    extra_metadata={"attempt": attempts, "max_retries": self.max_retries},
                )
                if attempts > self.max_retries:
                    ValidationEventLogger.log_event(
                        event_name="recovery_exhausted",
                        status="FAILED",
                        message=f"{operation_name} exhausted all {self.max_retries + 1} attempts.",
                        document_id=context_id,
                    )
                    raise e
                time.sleep(self.delay_seconds * (2 ** (attempts - 1)))
