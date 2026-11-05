#!/usr/bin/env bash
# Restore a LearnSense backup (public schema) into an EMPTY database.
#
#   scripts/restore_postgres.sh --dsn-env RESTORE_DATABASE_URL \
#       --dump /backups/learnsense_<UTC>.dump --confirm-database <target-db-name> \
#       [--create-supabase-roles]
#
# Safety rules (all enforced, in this order, before anything is written):
# * The DSN comes from the env var named by --dsn-env. Its password is moved into a
#   temporary 0600 pgpass file deleted on exit; tools see a password-free DSN only.
# * --confirm-database must equal the target's current_database().
# * The target must contain no tables in the public schema.
# * Every role the dump grants to (or revokes from) must exist on the target server.
#   Missing roles abort the restore and are listed; no grant is silently dropped.
#   --create-supabase-roles first creates Supabase's `anon`, `authenticated` and
#   `service_role` (NOLOGIN) via deploy/postgres/init/00_supabase_roles.sql, for
#   restoring a Supabase-origin dump into plain PostgreSQL. Never needed on Supabase.
# * The `public` schema object itself (and its comment/ACL) is skipped: the target's
#   existing public schema is used. Everything inside it is restored.
# * Table privileges end up exactly as in the dump, even on targets with ALTER DEFAULT
#   PRIVILEGES (Supabase grants every new table in public to anon/authenticated/
#   service_role, and pg_dump does not record the revocations needed to undo that).
#   After the restore, the same transaction revokes all table privileges in public
#   from PUBLIC and Supabase's API roles and re-applies exactly the dump's grants.
# * Restore and that reconciliation run in ONE transaction and stop at the first error:
#   on failure the target database is left exactly as it was (empty). Roles created by
#   --create-supabase-roles are cluster-wide and remain.
set -euo pipefail

DSN_ENV="" DUMP="" CONFIRM="" CREATE_ROLES=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dsn-env) DSN_ENV="${2:-}"; shift 2 ;;
    --dump) DUMP="${2:-}"; shift 2 ;;
    --confirm-database) CONFIRM="${2:-}"; shift 2 ;;
    --create-supabase-roles) CREATE_ROLES=1; shift ;;
    -h|--help) sed -n '2,24p' "$0"; exit 0 ;;
    *) echo "ERROR: unknown argument $1" >&2; exit 2 ;;
  esac
done
[[ -n "$DSN_ENV" && -n "$DUMP" && -n "$CONFIRM" ]] || {
  echo "ERROR: --dsn-env, --dump and --confirm-database are required" >&2; exit 2; }
[[ -f "$DUMP" ]] || { echo "ERROR: dump file not found" >&2; exit 2; }
[[ -n "${!DSN_ENV:-}" ]] || { echo "ERROR: environment variable $DSN_ENV is not set or empty" >&2; exit 2; }

BIN="${PG_BIN:+$PG_BIN/}"
PY="${PYTHON:-python}"
for tool in pg_restore psql; do
  command -v "${BIN}${tool}" >/dev/null || { echo "ERROR: $tool not found (set PG_BIN)" >&2; exit 2; }
done

WORK="$(mktemp -d)"
chmod 700 "$WORK"
trap 'rm -rf "$WORK"' EXIT
export PGPASSFILE="$WORK/pgpass"
SAFE_DSN="$("$PY" "$(dirname "$0")/pg_credentials.py" --dsn-env "$DSN_ENV" --pgpass-file "$PGPASSFILE")"

ACTUAL="$("${BIN}psql" --dbname="$SAFE_DSN" -At -c 'select current_database()')"
if [[ "$ACTUAL" != "$CONFIRM" ]]; then
  echo "ERROR: target database is '$ACTUAL', not '$CONFIRM'; refusing to restore" >&2
  exit 3
fi
TABLES="$("${BIN}psql" --dbname="$SAFE_DSN" -At -c \
  "select count(*) from pg_tables where schemaname = 'public'")"
if [[ "$TABLES" != "0" ]]; then
  echo "ERROR: target database '$ACTUAL' is not empty ($TABLES tables); restore only into an empty database" >&2
  exit 3
fi

# Table of contents without the `public` schema object itself.
"${BIN}pg_restore" --list "$DUMP" > "$WORK/full.toc"
grep -vE '^[0-9]+; [0-9]+ [0-9]+ (SCHEMA - public |COMMENT - SCHEMA public |ACL - SCHEMA public )' \
  "$WORK/full.toc" > "$WORK/restore.toc"

if [[ "$CREATE_ROLES" == "1" ]]; then
  "${BIN}psql" --dbname="$SAFE_DSN" -v ON_ERROR_STOP=1 -q \
    -f "$(dirname "$0")/../deploy/postgres/init/00_supabase_roles.sql"
fi

# Roles referenced by the dump's GRANT/REVOKE statements must already exist.
"${BIN}pg_restore" --schema-only --use-list="$WORK/restore.toc" --file="$WORK/schema.sql" "$DUMP"
REFERENCED="$(grep -E '^(GRANT|REVOKE) ' "$WORK/schema.sql" \
  | sed -E 's/ WITH GRANT OPTION;$/;/; s/.* (TO|FROM) (.*);$/\2/' | tr ',' '\n' \
  | sed -E 's/^ +| +$//g; s/"//g' | grep -vE '^(PUBLIC)?$' | sort -u || true)"
MISSING=""
for role in $REFERENCED; do
  # Variable interpolation is guaranteed for SQL read from stdin (not for -c).
  exists="$(printf "select count(*) from pg_roles where rolname = :'role';\n" \
    | "${BIN}psql" --dbname="$SAFE_DSN" -At -v role="$role")"
  [[ "$exists" == "1" ]] || MISSING="$MISSING $role"
done
if [[ -n "$MISSING" ]]; then
  echo "ERROR: the dump grants privileges to roles missing on the target:$MISSING" >&2
  echo "       Create them first (Supabase-origin dump into plain PostgreSQL: --create-supabase-roles)." >&2
  echo "       Nothing was restored." >&2
  exit 4
fi

# Render the restore as SQL, then append the exact ACL reconciliation (see header).
"${BIN}pg_restore" --no-owner --use-list="$WORK/restore.toc" --file="$WORK/restore.sql" "$DUMP"
{
  echo 'DO $$'
  echo 'DECLARE r text;'
  echo 'BEGIN'
  echo '  REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;'
  echo "  FOREACH r IN ARRAY ARRAY['anon', 'authenticated', 'service_role'] LOOP"
  echo '    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN'
  echo "      EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA public FROM %I', r);"
  echo '    END IF;'
  echo '  END LOOP;'
  echo 'END $$;'
  grep -E '^GRANT .* ON TABLE .* TO (PUBLIC|anon|authenticated|service_role)( WITH GRANT OPTION)?;$' \
    "$WORK/schema.sql" || true
} > "$WORK/acl_reconcile.sql"

echo "Restoring into '$ACTUAL' ..."
"${BIN}psql" --dbname="$SAFE_DSN" -v ON_ERROR_STOP=1 -q --single-transaction \
  -f "$WORK/restore.sql" -f "$WORK/acl_reconcile.sql" > /dev/null

echo "Restored schema versions: $("${BIN}psql" --dbname="$SAFE_DSN" -At -c \
  "select string_agg(version, ',' order by version) from schema_migrations")"
echo "Next: run scripts/migrate.py status against this database, compare row counts with the"
echo "backup manifest, then restore file stores (docs/operations/backup-and-restore.md)."
