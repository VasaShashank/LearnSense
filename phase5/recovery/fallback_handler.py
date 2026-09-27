"""
Fallback Handler and Recovery Manager for Taproot Phase 5.
Directs recovery flows based on failure classification.
"""

from typing import Any, Callable, Dict, Optional, Tuple
from phase5.models.validation_result import RecoveryClassification, ValidationResult, ValidationStatus
from phase5.observability.validation_events import ValidationEventLogger


class FallbackHandler:
    """Executes registered fallback strategies when primary operations fail or return invalid/low-confidence results."""

    @staticmethod
    def execute_fallback(
        boundary_name: str,
        primary_func: Callable[[], Any],
        fallback_func: Callable[[], Any],
        validator_func: Optional[Callable[[Any], ValidationResult]] = None,
        context_id: Optional[str] = None,
    ) -> Tuple[Any, ValidationResult]:
        try:
            result = primary_func()
            if validator_func:
                val_res = validator_func(result)
                if val_res.is_valid:
                    return result, val_res
                ValidationEventLogger.log_event(
                    event_name=f"{boundary_name}_fallback_triggered",
                    status="RECOVERING",
                    message=f"Primary execution returned invalid result: {val_res.errors}. Triggering fallback.",
                    document_id=context_id,
                )
            else:
                return result, ValidationResult(status=ValidationStatus.VALID, is_valid=True)
        except Exception as e:
            ValidationEventLogger.log_event(
                event_name=f"{boundary_name}_primary_failed",
                status="RECOVERING",
                message=f"Primary execution raised exception: {str(e)}. Triggering fallback.",
                document_id=context_id,
            )

        try:
            fallback_result = fallback_func()
            if validator_func:
                fb_val_res = validator_func(fallback_result)
                fb_val_res.warnings.append("Result produced via fallback strategy.")
                return fallback_result, fb_val_res
            return fallback_result, ValidationResult(
                status=ValidationStatus.WARNING,
                is_valid=True,
                warnings=["Result produced via fallback strategy."],
            )
        except Exception as fb_err:
            ValidationEventLogger.log_event(
                event_name=f"{boundary_name}_fallback_failed",
                status="FAILED",
                message=f"Fallback execution also failed: {str(fb_err)}",
                document_id=context_id,
            )
            val_res = ValidationResult(
                status=ValidationStatus.INVALID,
                is_valid=False,
                recoverable=False,
                recovery_classification=RecoveryClassification.NON_RECOVERABLE,
            )
            val_res.add_error(f"Both primary and fallback executions failed for boundary {boundary_name}.")
            raise fb_err


class RecoveryManager:
    """Classifies failures and determines whether recovery or termination should occur."""

    @staticmethod
    def classify_failure(
        exception: Optional[Exception] = None,
        val_result: Optional[ValidationResult] = None,
    ) -> RecoveryClassification:
        if val_result:
            return val_result.recovery_classification

        if exception:
            from phase5.errors.error_types import TaprootException
            if isinstance(exception, TaprootException):
                return RecoveryClassification.RECOVERABLE if exception.recoverable else RecoveryClassification.NON_RECOVERABLE

        return RecoveryClassification.NON_RECOVERABLE
