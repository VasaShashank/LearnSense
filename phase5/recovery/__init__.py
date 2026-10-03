"""
Phase 5 Recovery Package.
Strict no-fallback policy (§1.2 #1, §2 #20): FallbackHandler deleted.
Only identical-call RetryPolicy (§1.3) retained.
"""
from phase5.recovery.retry_policy import RetryPolicy

__all__ = ["RetryPolicy"]
