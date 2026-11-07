-- =============================================================================
-- Migration 004 — Document ownership and class-material shares
-- LearnSense / TAPROOT · Person 1 · feat/supabase-auth-postgres
-- =============================================================================
-- PostgreSQL home for the records previously kept only in storage/document_owners
-- and storage/document_shares. Existing JSON records are imported with
-- scripts/import_document_access.py (IDs are preserved; nothing is deleted).
--
-- owner_id is TEXT because legacy records may predate canonical UUID identities.
-- Idempotent: safe to re-run.
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS document_owners (
    document_id     TEXT        PRIMARY KEY,
    owner_id        TEXT        NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source          TEXT        NOT NULL DEFAULT 'app',
    CONSTRAINT ck_document_owners_source CHECK (source IN ('app', 'json_import'))
);

COMMENT ON TABLE document_owners IS
    'Uploader of a private document. Ownership is claimed once and never transferred.';

CREATE INDEX IF NOT EXISTS idx_document_owners_owner ON document_owners (owner_id);

CREATE TABLE IF NOT EXISTS document_shares (
    document_id     TEXT        NOT NULL REFERENCES document_owners (document_id) ON DELETE CASCADE,
    class_id        TEXT        NOT NULL REFERENCES course_classes (class_id) ON DELETE CASCADE,
    owner_id        TEXT        NOT NULL,
    shared_by       TEXT        NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (document_id, class_id)
);

COMMENT ON TABLE document_shares IS
    'Explicit grant of an owned document to a class. Revocation deletes the grant; '
    'the audit_events table keeps the history.';

CREATE INDEX IF NOT EXISTS idx_document_shares_class ON document_shares (class_id);

ALTER TABLE document_owners ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_shares ENABLE ROW LEVEL SECURITY;
REVOKE ALL PRIVILEGES ON TABLE document_owners, document_shares FROM PUBLIC, anon, authenticated;

INSERT INTO schema_migrations (version, description)
VALUES ('004', 'Document ownership and class-material shares')
ON CONFLICT (version) DO NOTHING;

COMMIT;
