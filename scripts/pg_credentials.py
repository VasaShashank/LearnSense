"""Split a PostgreSQL DSN into a password-free DSN plus a private pgpass file.

Used by scripts/backup_postgres.sh and scripts/restore_postgres.sh so that no
password ever appears in a child process's command line (visible to other local
users in process listings):

    SAFE_DSN="$(python scripts/pg_credentials.py --dsn-env VAR --pgpass-file /tmp/x/pgpass)"
    export PGPASSFILE=/tmp/x/pgpass

* Reads the DSN from the named environment variable; never prints the password.
* Prints the DSN WITHOUT the password (user, host, port, database, query kept).
* If the DSN has a password, writes one pgpass line to --pgpass-file with mode 0600
  (libpq ignores group/world-readable pgpass files on POSIX). With no password,
  no file is written.
"""

from __future__ import annotations

import argparse
import os
import sys
from urllib.parse import unquote, urlsplit, urlunsplit


def _pgpass_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(":", "\\:")


def split_dsn(dsn: str):
    """(password-free DSN, pgpass line or None). Pure function."""
    parts = urlsplit(dsn)
    if parts.scheme not in ("postgres", "postgresql"):
        raise ValueError("DSN must use the postgres or postgresql scheme")
    if "password=" in (parts.query or ""):
        raise ValueError("Put the password in the URL user-info, not in the query string")
    user_info, sep, host_spec = parts.netloc.rpartition("@")
    username, has_password, password = user_info.partition(":")
    safe_netloc = f"{username}@{host_spec}" if sep else parts.netloc
    safe = urlunsplit((parts.scheme, safe_netloc, parts.path, parts.query, parts.fragment))
    if not has_password:
        return safe, None
    host = parts.hostname or "localhost"
    port = str(parts.port or 5432)
    database = unquote(parts.path.lstrip("/")) or "*"
    line = ":".join(_pgpass_escape(v) for v in (host, port, database, unquote(username) or "*", unquote(password)))
    return safe, line


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dsn-env", required=True)
    parser.add_argument("--pgpass-file", required=True)
    args = parser.parse_args(argv)
    dsn = os.environ.get(args.dsn_env, "").strip()
    if not dsn:
        print(f"ERROR: environment variable {args.dsn_env} is not set or empty", file=sys.stderr)
        return 2
    try:
        safe, line = split_dsn(dsn)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if line is not None:
        fd = os.open(args.pgpass_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(line + "\n")
        os.chmod(args.pgpass_file, 0o600)
    print(safe)
    return 0


if __name__ == "__main__":
    sys.exit(main())
