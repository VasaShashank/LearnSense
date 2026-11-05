-- =============================================================================
-- CONTINGENCY migration 007 — case-insensitive unique organization names
-- =============================================================================
-- NOT a migration yet. Adopt it ONLY when the pre-migration check
-- (scripts/sql/supabase_premigration_check.sql, row 200) reports
-- uq_organizations_name_ci as missing or INVALID on the target database.
--
-- To adopt: copy this file unchanged to migrations/007_organization_name_ci.sql,
-- commit it, and apply it with scripts/migrate.py like any other migration
-- (it then runs after 006 everywhere). See docs/operations/supabase-migration.md.
--
-- Why: migration 001 creates this index, but a database whose 001 was applied from
-- an older version may lack it. Without it, organizations whose names differ only by
-- case can be created, and the API (institution_service) relies on this exact index
-- name to return 409 ORGANIZATION_NAME_TAKEN.
--
-- Safe everywhere: a no-op where a valid index of this name already exists; refuses
-- (rolls back, changes nothing) if existing names already collide.
-- =============================================================================

BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM organizations GROUP BY lower(name) HAVING count(*) > 1) THEN
        RAISE EXCEPTION 'organizations contain names that differ only by case; resolve them before migration 007';
    END IF;
    -- An INVALID index (e.g. a failed concurrent build) enforces nothing: rebuild it.
    IF EXISTS (
        SELECT 1 FROM pg_index i
        JOIN pg_class c ON c.oid = i.indexrelid
        WHERE c.relname = 'uq_organizations_name_ci'
          AND c.relnamespace = 'public'::regnamespace
          AND NOT i.indisvalid
    ) THEN
        DROP INDEX public.uq_organizations_name_ci;
    END IF;
END$$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_organizations_name_ci
    ON organizations (LOWER(name));

INSERT INTO schema_migrations (version, description)
VALUES ('007', 'Case-insensitive unique organization names (compatibility)')
ON CONFLICT (version) DO NOTHING;

COMMIT;
