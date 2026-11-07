-- =============================================================================
-- Migration 007 — User profiles and organization invitations
-- LearnSense / TAPROOT · Person 1 · feat/supabase-auth-postgres
-- =============================================================================
-- 1. Adds user profile display fields (display_name, avatar_url) to users.
-- 2. Creates org_invitations table for email-based teacher and learner invites,
--    resolving the provisioning deadlock where an admin cannot add staff before
--    their first sign-in.
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. User profile columns
-- ---------------------------------------------------------------------------
ALTER TABLE users ADD COLUMN IF NOT EXISTS display_name TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url TEXT;

-- ---------------------------------------------------------------------------
-- 2. Organization invitations
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS org_invitations (
    invitation_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          TEXT NOT NULL REFERENCES organizations (org_id) ON DELETE CASCADE,
    email           TEXT NOT NULL,
    role            user_role NOT NULL DEFAULT 'LEARNER',
    class_id        TEXT REFERENCES course_classes (class_id) ON DELETE SET NULL,
    token_hash      TEXT NOT NULL,
    invited_by      TEXT NOT NULL,
    expires_at      TIMESTAMPTZ NOT NULL,
    accepted_at     TIMESTAMPTZ,
    accepted_by     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE org_invitations IS
    'Pending invitations to an organization, bound to email, role and optional class.';

CREATE INDEX IF NOT EXISTS idx_org_invitations_org_id ON org_invitations (org_id);
CREATE INDEX IF NOT EXISTS idx_org_invitations_email_lower ON org_invitations (LOWER(email));
CREATE INDEX IF NOT EXISTS idx_org_invitations_token_hash ON org_invitations (token_hash);
CREATE UNIQUE INDEX IF NOT EXISTS uq_org_invitations_active
    ON org_invitations (org_id, LOWER(email))
    WHERE accepted_at IS NULL;

-- Revoke direct client access to invitations (server authority model)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON org_invitations FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON org_invitations FROM authenticated;
    END IF;
END$$;

INSERT INTO schema_migrations (version, description)
VALUES ('007', 'User profile extension and organization invitations')
ON CONFLICT (version) DO NOTHING;

COMMIT;

