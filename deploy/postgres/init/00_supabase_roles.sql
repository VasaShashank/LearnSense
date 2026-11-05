-- Supabase compatibility shim for NON-Supabase PostgreSQL (local staging, CI,
-- disposable test clusters, restoring a Supabase-origin dump). Supabase projects
-- already define these roles; do not run this against Supabase.
--
-- * Migrations revoke table privileges from the Supabase API roles `anon` and
--   `authenticated`, so those roles must exist before migrations run.
-- * Supabase-origin dumps carry grants to `service_role`; it must exist for those
--   grants to restore faithfully. Created NOLOGIN: nothing can connect as it here.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        CREATE ROLE anon NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        CREATE ROLE authenticated NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        CREATE ROLE service_role NOLOGIN;
    END IF;
END$$;
