"""Atomic file replacement that tolerates transient Windows sharing violations.

All file-backed stores write a temporary file and ``os.replace`` it over the
target. On Windows that rename fails with ``PermissionError`` (WinError 5/32) while
another process briefly holds the target open without delete-sharing; sync
clients (OneDrive), antivirus scanners and the search indexer routinely do this to
freshly written files. The failure is transient but surfaced as nondeterministic
test and runtime errors.

``replace_atomically`` retries only that error, only on Windows, a bounded number
of times (~1.3 s total), then re-raises. Everywhere else it is exactly
``os.replace``. Atomicity is unchanged: the target is either the old or the new
file, never partial.
"""

from __future__ import annotations

import os
import sys
import time

_ATTEMPTS = 8
_FIRST_DELAY_SECONDS = 0.01


def replace_atomically(src, dst, *, _platform: str = sys.platform, _sleep=time.sleep) -> None:
    if _platform != "win32":
        os.replace(src, dst)
        return
    delay = _FIRST_DELAY_SECONDS
    for attempt in range(_ATTEMPTS):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == _ATTEMPTS - 1:
                raise
            _sleep(delay)
            delay = min(delay * 2, 0.4)
