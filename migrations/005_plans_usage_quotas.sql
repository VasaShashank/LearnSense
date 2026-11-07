-- =============================================================================
-- Migration 005 — Plans, quota limits, usage events
-- LearnSense / TAPROOT · Person 1 (foundation) · Person 5 (dimensions, metering)
-- =============================================================================
-- Generic, dimension-based infrastructure. No plans, limits or dimensions are
-- seeded: an organization without a plan assignment has no quota limits.
-- Final dimension names and limits are a Person 5 / team decision
-- (docs/contracts/usage-and-quotas.md).
-- Idempotent: safe to re-run.
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS plans (
    plan_id         TEXT        PRIMARY KEY,
    name            TEXT        NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_plans_plan_id CHECK (plan_id ~ '^[a-z][a-z0-9_-]{1,62}$')
);

CREATE TABLE IF NOT EXISTS org_plan_assignments (
    org_id          TEXT        PRIMARY KEY REFERENCES organizations (org_id) ON DELETE CASCADE,
    plan_id         TEXT        NOT NULL REFERENCES plans (plan_id),
    assigned_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    assigned_by     TEXT        NOT NULL
);

CREATE TABLE IF NOT EXISTS quota_limits (
    plan_id         TEXT        NOT NULL REFERENCES plans (plan_id) ON DELETE CASCADE,
    dimension       TEXT        NOT NULL,
    period          TEXT        NOT NULL,
    limit_quantity  BIGINT      NOT NULL,
    PRIMARY KEY (plan_id, dimension, period),
    CONSTRAINT ck_quota_limits_dimension CHECK (dimension ~ '^[a-z][a-z0-9_.]{0,63}$'),
    CONSTRAINT ck_quota_limits_period CHECK (period IN ('day', 'month', 'total')),
    CONSTRAINT ck_quota_limits_limit CHECK (limit_quantity >= 0)
);

-- Usage outlives nothing: ON DELETE RESTRICT keeps attributable history.
CREATE TABLE IF NOT EXISTS usage_events (
    event_id        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    org_id          TEXT        REFERENCES organizations (org_id) ON DELETE RESTRICT,
    user_id         TEXT        NOT NULL,
    dimension       TEXT        NOT NULL,
    quantity        BIGINT      NOT NULL,
    source          TEXT        NOT NULL,
    request_id      TEXT        NOT NULL,
    CONSTRAINT uq_usage_events_request_id UNIQUE (request_id),
    CONSTRAINT ck_usage_events_dimension CHECK (dimension ~ '^[a-z][a-z0-9_.]{0,63}$'),
    CONSTRAINT ck_usage_events_quantity CHECK (quantity > 0)
);

CREATE INDEX IF NOT EXISTS idx_usage_events_org_dim_time
    ON usage_events (org_id, dimension, occurred_at);
CREATE INDEX IF NOT EXISTS idx_usage_events_user_time
    ON usage_events (user_id, occurred_at);

ALTER TABLE plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE org_plan_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE quota_limits ENABLE ROW LEVEL SECURITY;
ALTER TABLE usage_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL PRIVILEGES ON TABLE plans, org_plan_assignments, quota_limits, usage_events
    FROM PUBLIC, anon, authenticated;

INSERT INTO schema_migrations (version, description)
VALUES ('005', 'Plans, quota limits and usage events')
ON CONFLICT (version) DO NOTHING;

COMMIT;
