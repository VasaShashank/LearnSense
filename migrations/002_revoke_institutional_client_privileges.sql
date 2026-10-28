-- =============================================================================
-- Migration 002 — Revoke direct client privileges on institutional tables
-- LearnSense / TAPROOT · Person 1 · feat/supabase-auth-postgres
-- =============================================================================
-- Backend authorization uses the server-side database owner. Supabase API
-- client roles receive no direct table privileges; RLS remains enabled with
-- no client-facing policies.
--
-- Safe to re-run: REVOKE is idempotent and the version insert ignores conflicts.
-- =============================================================================

BEGIN;

REVOKE ALL PRIVILEGES ON TABLE
    public.organizations,
    public.org_memberships,
    public.course_classes,
    public.class_enrollments
FROM PUBLIC, anon, authenticated;

INSERT INTO public.schema_migrations (version, description)
VALUES ('002', 'Revoke direct client privileges on institutional tables')
ON CONFLICT (version) DO NOTHING;

COMMIT;
