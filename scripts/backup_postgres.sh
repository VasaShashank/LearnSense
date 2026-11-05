#!/usr/bin/env bash
# Back up LearnSense: the `public` schema of PostgreSQL (custom-format dump) plus the
# file stores not yet in PostgreSQL.
#
#   scripts/backup_postgres.sh --dsn-env DATABASE_URL --out /backups [--file-root .]
#
# * The DSN is read from the environment variable named by --dsn-env. The password is
#   moved into a temporary 0600 pgpass file (PGPASSFILE) that is deleted on exit; the
#   PostgreSQL tools only ever see a password-free DSN on their command line.
# * Only the `public` schema is dumped: it holds every LearnSense table. Platform
#   schemas (Supabase `auth`, `storage`, `extensions`, ...) belong to the platform and
#   are backed up by it.
# * pg_dump/psql must be on PATH (or set PG_BIN). Python 3 is required (PYTHON).
# * Produces, in --out:
#     learnsense_<UTC>.dump          pg_dump --format=custom --schema=public
#     learnsense_<UTC>.manifest      schema versions, row counts, sha256 of artifacts
#     learnsense_files_<UTC>.tar.gz  storage/ file stores (only with --file-root)
# See docs/operations/backup-and-restore.md.
set -euo pipefail

DSN_ENV="" OUT="" FILE_ROOT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dsn-env) DSN_ENV="${2:-}"; shift 2 ;;
    --out) OUT="${2:-}"; shift 2 ;;
    --file-root) FILE_ROOT="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "ERROR: unknown argument $1" >&2; exit 2 ;;
  esac
done
[[ -n "$DSN_ENV" && -n "$OUT" ]] || { echo "ERROR: --dsn-env and --out are required" >&2; exit 2; }
[[ -n "${!DSN_ENV:-}" ]] || { echo "ERROR: environment variable $DSN_ENV is not set or empty" >&2; exit 2; }

BIN="${PG_BIN:+$PG_BIN/}"
PY="${PYTHON:-python}"
command -v "${BIN}pg_dump" >/dev/null || { echo "ERROR: pg_dump not found (set PG_BIN)" >&2; exit 2; }
command -v "${BIN}psql" >/dev/null || { echo "ERROR: psql not found (set PG_BIN)" >&2; exit 2; }

# Credentials: private temp dir, password-free DSN for every tool invocation.
CRED_DIR="$(mktemp -d)"
chmod 700 "$CRED_DIR"
trap 'rm -rf "$CRED_DIR"' EXIT
export PGPASSFILE="$CRED_DIR/pgpass"
SAFE_DSN="$("$PY" "$(dirname "$0")/pg_credentials.py" --dsn-env "$DSN_ENV" --pgpass-file "$PGPASSFILE")"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$OUT"
DUMP="$OUT/learnsense_${STAMP}.dump"
MANIFEST="$OUT/learnsense_${STAMP}.manifest"

echo "Dumping schema public ..."
"${BIN}pg_dump" --format=custom --no-owner --schema=public --dbname="$SAFE_DSN" --file="$DUMP"

{
  echo "created_utc=$STAMP"
  echo "schemas=public"
  echo "database=$("${BIN}psql" --dbname="$SAFE_DSN" -At -c 'select current_database()')"
  echo "schema_versions=$("${BIN}psql" --dbname="$SAFE_DSN" -At -c \
    "select string_agg(version, ',' order by version) from schema_migrations")"
  for table in organizations org_memberships course_classes class_enrollments users audit_events \
               document_owners document_shares plans org_plan_assignments quota_limits usage_events jobs; do
    count="$("${BIN}psql" --dbname="$SAFE_DSN" -At -c \
      "select case when to_regclass('public.$table') is null then -1 else (select count(*) from public.$table) end" \
      2>/dev/null || echo -1)"
    echo "rows.$table=$count"
  done
} > "$MANIFEST"

if [[ -n "$FILE_ROOT" ]]; then
  ARCHIVE="$OUT/learnsense_files_${STAMP}.tar.gz"
  stores=()
  for store in document_owners document_shares jobs learner_states learners sessions subjects \
               learning_contexts question_banks institutions users usage classes documents \
               interventions resources idempotency.db taproot.db; do
    [[ -e "$FILE_ROOT/storage/$store" ]] && stores+=("storage/$store")
  done
  if [[ ${#stores[@]} -gt 0 ]]; then
    echo "Archiving ${#stores[@]} file stores ..."
    tar -czf "$ARCHIVE" -C "$FILE_ROOT" "${stores[@]}"
  fi
fi

( cd "$OUT" && for f in learnsense_*"${STAMP}"*; do
    [[ "$f" == *.manifest ]] && continue
    echo "sha256.$f=$(sha256sum "$f" | cut -d' ' -f1)"
  done ) >> "$MANIFEST"

echo "Backup complete:"
ls -1 "$OUT" | grep "$STAMP" | sed 's/^/  /'
