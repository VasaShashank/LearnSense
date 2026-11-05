-- =============================================================================
-- Migration 003 — User records, enrollment lifecycle, audit events
-- LearnSense / TAPROOT · Person 1 · feat/supabase-auth-postgres
-- =============================================================================
-- * users: one row per verified Supabase identity (no credentials stored).
-- * class_enrollments: soft unenrollment (history is retained, never deleted).
-- * course_classes: teacher_ids must be a JSON array.
-- * audit_events: trigger-protected (no UPDATE/DELETE/TRUNCATE) record of
--   privileged institutional operations; see the limitation note in section 3.
-- * schema_migrations.checksum: recorded by scripts/migrate.py.
--
-- Idempotent: safe to re-run. Apply with scripts/migrate.py (see migrations/README.md).
-- =============================================================================

BEGIN;

ALTER TABLE schema_migrations ADD COLUMN IF NOT EXISTS checksum TEXT;

-- ---------------------------------------------------------------------------
-- 1. users
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    user_id         UUID        PRIMARY KEY,
    email           TEXT,
    status          TEXT        NOT NULL DEFAULT 'active',
    status_reason   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at    TIMESTAMPTZ,
    CONSTRAINT ck_users_status CHECK (status IN ('active', 'disabled'))
);

COMMENT ON TABLE users IS
    'Local record of a Supabase-verified identity. Supabase remains the credential authority; '
    'status=disabled blocks LearnSense API access without touching the Supabase account.';

CREATE INDEX IF NOT EXISTS idx_users_email_lower ON users (LOWER(email));

-- ---------------------------------------------------------------------------
-- 2. Enrollment lifecycle (soft unenrollment)
-- ---------------------------------------------------------------------------
ALTER TABLE class_enrollments ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';
ALTER TABLE class_enrollments ADD COLUMN IF NOT EXISTS unenrolled_at TIMESTAMPTZ;
ALTER TABLE class_enrollments ADD COLUMN IF NOT EXISTS unenrolled_by TEXT;
ALTER TABLE class_enrollments ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_class_enrollments_status') THEN
        ALTER TABLE class_enrollments
            ADD CONSTRAINT ck_class_enrollments_status CHECK (status IN ('active', 'unenrolled'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_course_classes_teacher_ids_array') THEN
        ALTER TABLE course_classes
            ADD CONSTRAINT ck_course_classes_teacher_ids_array CHECK (jsonb_typeof(teacher_ids) = 'array');
    END IF;
END$$;

CREATE INDEX IF NOT EXISTS idx_class_enrollments_active
    ON class_enrollments (class_id)
    WHERE status = 'active';

-- ---------------------------------------------------------------------------
-- 3. audit_events (append-only)
-- ---------------------------------------------------------------------------
-- org_id intentionally has no foreign key: audit history must outlive the rows it
-- describes.
CREATE TABLE IF NOT EXISTS audit_events (
    event_id        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor_user_id   TEXT        NOT NULL,
    org_id          TEXT,
    action          TEXT        NOT NULL,
    target_type     TEXT        NOT NULL,
    target_id       TEXT        NOT NULL,
    details         JSONB       NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_audit_events_org_time ON audit_events (org_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_events_actor_time ON audit_events (actor_user_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_events_target ON audit_events (target_type, target_id);

CREATE OR REPLACE FUNCTION audit_events_reject_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only';
END$$;

DROP TRIGGER IF EXISTS trg_audit_events_append_only ON audit_events;
CREATE TRIGGER trg_audit_events_append_only
    BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION audit_events_reject_mutation();

-- TRUNCATE bypasses row-level triggers, so it needs its own statement trigger.
DROP TRIGGER IF EXISTS trg_audit_events_no_truncate ON audit_events;
CREATE TRIGGER trg_audit_events_no_truncate
    BEFORE TRUNCATE ON audit_events
    FOR EACH STATEMENT EXECUTE FUNCTION audit_events_reject_mutation();

-- LIMITATION: these triggers stop UPDATE, DELETE and TRUNCATE issued through
-- ordinary statements, including by the table owner. They are NOT absolute
-- immutability: a role that owns the table (or a superuser) can still
-- `ALTER TABLE audit_events DISABLE TRIGGER ...`, drop the triggers, or drop the
-- table. While the application connects as the table owner, tamper-resistance
-- against a compromised application credential requires a separate non-owner
-- application role and/or shipping events to an external append-only store.

-- ---------------------------------------------------------------------------
-- 4. Deny direct client access (same model as migrations 001/002)
-- ---------------------------------------------------------------------------
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL PRIVILEGES ON TABLE users, audit_events FROM PUBLIC, anon, authenticated;

INSERT INTO schema_migrations (version, description)
VALUES ('003', 'User records, soft unenrollment, append-only audit events')
ON CONFLICT (version) DO NOTHING;

COMMIT;
