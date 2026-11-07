"""Opt-in rules for tests that may talk to a real PostgreSQL database.

Ordinary tests must never reach a database configured through ``.env`` or the
developer's shell. Live tests run only when BOTH are set explicitly:

    LEARNSENSE_ALLOW_LIVE_PG_TESTS=1
    LEARNSENSE_TEST_DATABASE_URL=<DSN of a disposable database>

``DATABASE_URL`` is deliberately not consulted for opt-in, so the application's
real connection string is not used by a test by accident.

LEARNSENSE_TEST_DATABASE_URL MUST POINT TO A DISPOSABLE DATABASE. Live tests create
organizations, memberships, classes and enrollments and never clean them up, so use
a throwaway database or project that you are prepared to wipe or delete. Never point
it at production, staging, or any database holding real user data.

What this module does NOT do: it cannot verify that a database is disposable. The one
automated check, refusing a URL identical to the *shell's* ``DATABASE_URL``, is only a
guard against copy-paste mistakes. It does not read ``.env``, does not compare hosts
or database names, and is trivially bypassed by a different string that reaches the
same database (for example a pooler URL versus a direct URL). The flag and the URL
being set is a statement by the person running the tests that the target is safe;
that responsibility is theirs.
"""

from __future__ import annotations

from typing import Mapping, Optional, Tuple

ALLOW_FLAG = "LEARNSENSE_ALLOW_LIVE_PG_TESTS"
TEST_URL_VAR = "LEARNSENSE_TEST_DATABASE_URL"


def resolve_live_pg(
    environ: Mapping[str, str], ambient_database_url: Optional[str] = None
) -> Tuple[bool, str, str]:
    """Return ``(enabled, test_url, reason)``; ``reason`` explains a refusal."""
    flag = environ.get(ALLOW_FLAG, "").strip()
    url = environ.get(TEST_URL_VAR, "").strip()
    if flag != "1":
        return False, "", f"set {ALLOW_FLAG}=1 and {TEST_URL_VAR} to run live PostgreSQL tests"
    if not url:
        return False, "", f"{ALLOW_FLAG}=1 but {TEST_URL_VAR} is empty"
    # Copy-paste guard only: string equality does not prove the database is disposable.
    if ambient_database_url and url == ambient_database_url.strip():
        return False, "", f"{TEST_URL_VAR} must not equal the application's DATABASE_URL"
    return True, url, ""
