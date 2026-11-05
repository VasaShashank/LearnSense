-- =============================================================================
-- Migration 006 — Canonical job persistence
-- LearnSense / TAPROOT · Person 1 (persistence) · Person 5 (execution semantics)
-- =============================================================================
-- Storage for long-running work (ingestion, extraction, graph builds). Status
-- vocabulary follows the Master Blueprint §5.3: queued, running, succeeded,
-- failed, cancelled. Worker execution, retry policy and cancellation
-- orchestration are owned by Person 5 (docs/contracts/jobs.md).
-- Idempotent: safe to re-run.
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS jobs (
    job_id              TEXT        PRIMARY KEY,
    kind                TEXT        NOT NULL,
    owner_id            TEXT        NOT NULL,
    org_id              TEXT        REFERENCES organizations (org_id) ON DELETE RESTRICT,
    document_id         TEXT,
    status              TEXT        NOT NULL DEFAULT 'queued',
    progress_pct        SMALLINT    NOT NULL DEFAULT 0,
    stage               TEXT,
    error_code          TEXT,
    error_message       TEXT,
    attempt             INTEGER     NOT NULL DEFAULT 0,
    max_attempts        INTEGER     NOT NULL DEFAULT 1,
    idempotency_key     TEXT,
    pipeline_version    TEXT,
    result              JSONB,
    cancel_requested_at TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at          TIMESTAMPTZ,
    finished_at         TIMESTAMPTZ,
    CONSTRAINT ck_jobs_kind CHECK (kind ~ '^[a-z][a-z0-9_.]{0,63}$'),
    CONSTRAINT ck_jobs_status CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    CONSTRAINT ck_jobs_progress CHECK (progress_pct BETWEEN 0 AND 100),
    CONSTRAINT ck_jobs_attempts CHECK (attempt >= 0 AND max_attempts >= 1),
    CONSTRAINT uq_jobs_owner_idempotency UNIQUE (owner_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_jobs_owner_created ON jobs (owner_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_document ON jobs (document_id);
CREATE INDEX IF NOT EXISTS idx_jobs_active ON jobs (status, created_at)
    WHERE status IN ('queued', 'running');

ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
REVOKE ALL PRIVILEGES ON TABLE jobs FROM PUBLIC, anon, authenticated;

INSERT INTO schema_migrations (version, description)
VALUES ('006', 'Canonical job persistence')
ON CONFLICT (version) DO NOTHING;

COMMIT;
