-- =============================================================================
-- Migration 001 — Institutional Schema
-- LearnSense / TAPROOT · Person 1 · feat/supabase-auth-postgres
-- =============================================================================
-- Creates the authoritative PostgreSQL tables for multi-tenant institutional
-- entities: organizations, org memberships, course classes, and class
-- enrollments. These tables replace JSON-file persistence as the production
-- store for all institutional reads and writes.
--
-- Apply with:
--   psql "$DATABASE_URL" -f migrations/001_institutional_schema.sql
-- Or via Supabase SQL Editor in the project dashboard.
--
-- This migration is idempotent: every statement uses IF NOT EXISTS / DO NOTHING,
-- so re-running it on an already-migrated database is safe.
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Role enum
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'user_role') THEN
        CREATE TYPE user_role AS ENUM ('ADMIN', 'TEACHER', 'LEARNER');
    END IF;
END$$;

-- ---------------------------------------------------------------------------
-- 2. organizations
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS organizations (
    org_id          TEXT        PRIMARY KEY,
    name            TEXT        NOT NULL,
    domain          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Enforce unique, case-insensitive organization names.
CREATE UNIQUE INDEX IF NOT EXISTS uq_organizations_name_ci
    ON organizations (LOWER(name));

COMMENT ON TABLE organizations IS
    'Top-level educational tenants. Every org_id is the authoritative isolation boundary.';

CREATE INDEX IF NOT EXISTS idx_organizations_domain
    ON organizations (domain)
    WHERE domain IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 3. org_memberships
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS org_memberships (
    membership_id   TEXT        PRIMARY KEY,
    org_id          TEXT        NOT NULL REFERENCES organizations (org_id) ON DELETE CASCADE,
    user_id         TEXT        NOT NULL,
    role            user_role   NOT NULL DEFAULT 'LEARNER',
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- One active role per (org, user) pair.
    CONSTRAINT uq_org_memberships_org_user UNIQUE (org_id, user_id)
);

COMMENT ON TABLE org_memberships IS
    'Associates a Supabase auth user_id with an organization and grants a role.';

CREATE INDEX IF NOT EXISTS idx_org_memberships_user_id
    ON org_memberships (user_id);

CREATE INDEX IF NOT EXISTS idx_org_memberships_org_active
    ON org_memberships (org_id, is_active);

-- ---------------------------------------------------------------------------
-- 4. course_classes
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS course_classes (
    class_id        TEXT        PRIMARY KEY,
    org_id          TEXT        NOT NULL REFERENCES organizations (org_id) ON DELETE CASCADE,
    subject_id      TEXT        NOT NULL,
    title           TEXT        NOT NULL,
    -- Stored as a JSONB array of user_id strings; avoids a separate join table
    -- for a list that is read whole and mutated infrequently.
    teacher_ids     JSONB       NOT NULL DEFAULT '[]'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE course_classes IS
    'A classroom or cohort within an organization, tied to a subject/course.';

CREATE INDEX IF NOT EXISTS idx_course_classes_org_id
    ON course_classes (org_id);

CREATE INDEX IF NOT EXISTS idx_course_classes_subject_id
    ON course_classes (subject_id);

-- ---------------------------------------------------------------------------
-- 5. class_enrollments
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS class_enrollments (
    enrollment_id   TEXT        PRIMARY KEY,
    class_id        TEXT        NOT NULL REFERENCES course_classes (class_id) ON DELETE CASCADE,
    learner_id      TEXT        NOT NULL,
    enrolled_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- A learner can only be enrolled once per class.
    CONSTRAINT uq_class_enrollments_class_learner UNIQUE (class_id, learner_id)
);

COMMENT ON TABLE class_enrollments IS
    'Enrollment of a learner in a specific course class.';

CREATE INDEX IF NOT EXISTS idx_class_enrollments_class_id
    ON class_enrollments (class_id);

CREATE INDEX IF NOT EXISTS idx_class_enrollments_learner_id
    ON class_enrollments (learner_id);

-- ---------------------------------------------------------------------------
-- 6. Deny direct client access by default
-- ---------------------------------------------------------------------------
-- The application connects with its server-side database role. Supabase's
-- anon/authenticated API roles receive no row policies, so PostgREST cannot
-- read or mutate institutional rows directly. Add narrowly-scoped policies
-- only if direct client access is intentionally introduced later.
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE org_memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE course_classes ENABLE ROW LEVEL SECURITY;
ALTER TABLE class_enrollments ENABLE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------------------
-- 7. Schema version record (used by application startup check)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_migrations (
    version         TEXT        PRIMARY KEY,
    applied_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    description     TEXT
);

ALTER TABLE schema_migrations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE schema_migrations FROM PUBLIC, anon, authenticated;

INSERT INTO schema_migrations (version, description)
VALUES ('001', 'Institutional schema: organizations, memberships, classes, enrollments')
ON CONFLICT (version) DO NOTHING;

COMMIT;
