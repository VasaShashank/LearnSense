-- =============================================================================
-- LearnSense - pre-migration verification for migrations 003-006 (READ ONLY)
-- =============================================================================
-- Run it either way (both read-only):
--   * Supabase SQL Editor: paste and run. It is ONE SELECT statement, so the editor
--     shows ONE result grid (the editor only displays the last statement's result).
--     It returns about 125 rows: set the editor's row limit to at least 200 (the
--     common default of 100 silently drops the last sections).
--   * python scripts/premigration_check.py --dsn-env <VAR>   (runs it inside a
--     READ ONLY transaction and writes a report; see docs/operations/supabase-migration.md)
--
-- It changes nothing: it contains no DDL or DML. Checks that depend on columns which
-- may not exist run through query_to_xml(), and only when the column has been
-- confirmed to exist with a usable type; query_to_xml() executes its query
-- read-only. Org names in the output are XML-escaped (& shows as &amp;).
--
-- Columns: sort | section | check_name | status | observed | expected | action
-- status:
--   PASS        matches what migrations 003-006 and the API expect
--   WARN        migration can proceed, but review/decide before deploying the API
--   FAIL        do not run migrations 003-006 until resolved
--   INFO        context only
--   UNAVAILABLE check could not run (missing column/table, no privilege); review manually
-- Go/no-go: zero FAIL rows, every WARN and UNAVAILABLE row understood and accepted.
-- =============================================================================
WITH
att AS (   -- every column of every relation in schema public, with its base type name
    SELECT c.relname::text AS tbl, a.attname::text AS col, t.typname::text AS typ,
           format_type(a.atttypid, a.atttypmod) AS fmt, a.attnotnull AS nn,
           a.atthasdef AS hasdef, a.attidentity::text AS ident, a.attgenerated::text AS gen
    FROM pg_attribute a
    JOIN pg_class c ON c.oid = a.attrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_type t ON t.oid = a.atttypid
    WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
      AND a.attnum > 0 AND NOT a.attisdropped
),
rel AS (
    SELECT c.oid, c.relname::text AS relname, c.relkind::text AS relkind, c.relowner,
           pg_get_userbyid(c.relowner)::text AS owner,
           c.relrowsecurity AS rls, c.relforcerowsecurity AS frls
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
),
ix AS (
    SELECT ic.relname::text AS idx, t.relname::text AS tbl, i.indisunique AS uniq,
           i.indisprimary AS pk, i.indisvalid AS valid, (i.indpred IS NOT NULL) AS partial,
           (i.indexprs IS NOT NULL) AS expr, pg_get_indexdef(i.indexrelid) AS def,
           (SELECT array_agg(a.attname::text ORDER BY a.attname::text)
              FROM pg_attribute a
             WHERE a.attrelid = i.indrelid AND a.attnum > 0
               AND a.attnum = ANY (i.indkey::int2[])) AS cols
    FROM pg_index i
    JOIN pg_class ic ON ic.oid = i.indexrelid
    JOIN pg_class t ON t.oid = i.indrelid
    JOIN pg_namespace n ON n.oid = t.relnamespace
    WHERE n.nspname = 'public'
),
con AS (
    SELECT c.oid, c.conname::text AS conname, c.contype::text AS contype,
           n.nspname::text AS nspname, t.relname::text AS tbl, rt.relname::text AS reftbl,
           pg_get_constraintdef(c.oid) AS def,
           (SELECT array_agg(a.attname::text ORDER BY a.attname::text)
              FROM pg_attribute a
             WHERE a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)) AS cols
    FROM pg_constraint c
    JOIN pg_namespace n ON n.oid = c.connamespace
    LEFT JOIN pg_class t ON t.oid = c.conrelid
    LEFT JOIN pg_class rt ON rt.oid = c.confrelid
),
ratt AS (  -- columns of tables the checking role can actually read (guards data queries)
    SELECT a.* FROM att a JOIN rel r ON r.relname = a.tbl WHERE has_table_privilege(r.oid, 'SELECT')
),
h AS (     -- one row: the type of every column a guarded check needs (NULL = missing or unreadable)
    SELECT
      (SELECT typ FROM ratt WHERE tbl = 'organizations'     AND col = 'org_id')        AS o_org,
      (SELECT typ FROM ratt WHERE tbl = 'organizations'     AND col = 'name')          AS o_name,
      (SELECT typ FROM ratt WHERE tbl = 'org_memberships'   AND col = 'membership_id') AS m_mid,
      (SELECT typ FROM ratt WHERE tbl = 'org_memberships'   AND col = 'org_id')        AS m_org,
      (SELECT typ FROM ratt WHERE tbl = 'org_memberships'   AND col = 'user_id')       AS m_user,
      (SELECT typ FROM ratt WHERE tbl = 'org_memberships'   AND col = 'role')          AS m_role,
      (SELECT typ FROM ratt WHERE tbl = 'org_memberships'   AND col = 'is_active')     AS m_active,
      (SELECT typ FROM ratt WHERE tbl = 'course_classes'    AND col = 'class_id')      AS c_cid,
      (SELECT typ FROM ratt WHERE tbl = 'course_classes'    AND col = 'org_id')        AS c_org,
      (SELECT typ FROM ratt WHERE tbl = 'course_classes'    AND col = 'teacher_ids')   AS c_tid,
      (SELECT typ FROM ratt WHERE tbl = 'class_enrollments' AND col = 'enrollment_id') AS e_eid,
      (SELECT typ FROM ratt WHERE tbl = 'class_enrollments' AND col = 'class_id')      AS e_cid,
      (SELECT typ FROM ratt WHERE tbl = 'class_enrollments' AND col = 'learner_id')    AS e_lid,
      (SELECT typ FROM ratt WHERE tbl = 'class_enrollments' AND col = 'status')        AS e_status,
      (SELECT typ FROM ratt WHERE tbl = 'schema_migrations' AND col = 'version')       AS s_ver,
      EXISTS (SELECT 1 FROM rel WHERE relname = 'organizations'     AND relkind IN ('r', 'p') AND has_table_privilege(oid, 'SELECT')) AS t_org,
      EXISTS (SELECT 1 FROM rel WHERE relname = 'org_memberships'   AND relkind IN ('r', 'p') AND has_table_privilege(oid, 'SELECT')) AS t_mem,
      EXISTS (SELECT 1 FROM rel WHERE relname = 'course_classes'    AND relkind IN ('r', 'p') AND has_table_privilege(oid, 'SELECT')) AS t_cls,
      EXISTS (SELECT 1 FROM rel WHERE relname = 'class_enrollments' AND relkind IN ('r', 'p') AND has_table_privilege(oid, 'SELECT')) AS t_enr,
      COALESCE(has_table_privilege(to_regclass('auth.users'), 'SELECT'), false)         AS auth_ok,
      (SELECT t.typname::text FROM pg_attribute a JOIN pg_type t ON t.oid = a.atttypid
        WHERE a.attrelid = to_regclass('auth.users') AND a.attname = 'id'
          AND NOT a.attisdropped)                                                        AS auth_id,
      EXISTS (SELECT 1 FROM pg_attribute a
               WHERE a.attrelid = to_regclass('auth.users') AND a.attname = 'deleted_at'
                 AND NOT a.attisdropped)                                                 AS auth_deleted,
      (SELECT rolbypassrls FROM pg_roles WHERE rolname = 'postgres')                    AS pg_bypass
),
expected_cols (tbl, col, ok, warn, why) AS (VALUES
  ('organizations',     'org_id',        ARRAY['text','varchar'], ARRAY[]::text[],      'PK; 005/006 add TEXT foreign keys to it'),
  ('organizations',     'name',          ARRAY['text','varchar'], ARRAY[]::text[],      'API reads/writes; lower(name) uniqueness'),
  ('organizations',     'domain',        ARRAY['text','varchar'], ARRAY[]::text[],      'API inserts and selects it'),
  ('organizations',     'created_at',    ARRAY['timestamptz'],    ARRAY['timestamp'],   'API inserts and selects it'),
  ('org_memberships',   'membership_id', ARRAY['text','varchar'], ARRAY[]::text[],      'PK'),
  ('org_memberships',   'org_id',        ARRAY['text','varchar'], ARRAY[]::text[],      'FK to organizations'),
  ('org_memberships',   'user_id',       ARRAY['text','varchar'], ARRAY[]::text[],      'Supabase user id as TEXT; joined to class_enrollments.learner_id'),
  ('org_memberships',   'role',          ARRAY['user_role'],      ARRAY['text','varchar'], 'enum from 001; TEXT works if values are exactly ADMIN/TEACHER/LEARNER'),
  ('org_memberships',   'is_active',     ARRAY['bool'],           ARRAY[]::text[],      'API filters on is_active = TRUE'),
  ('org_memberships',   'created_at',    ARRAY['timestamptz'],    ARRAY['timestamp'],   'API inserts it'),
  ('org_memberships',   'updated_at',    ARRAY['timestamptz'],    ARRAY['timestamp'],   'API inserts/updates it'),
  ('course_classes',    'class_id',      ARRAY['text','varchar'], ARRAY[]::text[],      'PK; 004 adds a TEXT foreign key to it'),
  ('course_classes',    'org_id',        ARRAY['text','varchar'], ARRAY[]::text[],      'FK to organizations'),
  ('course_classes',    'subject_id',    ARRAY['text','varchar'], ARRAY[]::text[],      'API inserts and selects it'),
  ('course_classes',    'title',         ARRAY['text','varchar'], ARRAY[]::text[],      'API inserts and selects it'),
  ('course_classes',    'teacher_ids',   ARRAY['jsonb'],          ARRAY[]::text[],      '003 adds CHECK (jsonb_typeof(teacher_ids) = ''array''); json/text would make 003 fail'),
  ('course_classes',    'created_at',    ARRAY['timestamptz'],    ARRAY['timestamp'],   'API inserts and selects it'),
  ('class_enrollments', 'enrollment_id', ARRAY['text','varchar'], ARRAY[]::text[],      'PK'),
  ('class_enrollments', 'class_id',      ARRAY['text','varchar'], ARRAY[]::text[],      'FK to course_classes'),
  ('class_enrollments', 'learner_id',    ARRAY['text','varchar'], ARRAY[]::text[],      'joined to org_memberships.user_id (types must be comparable)'),
  ('class_enrollments', 'enrolled_at',   ARRAY['timestamptz'],    ARRAY['timestamp'],   'API inserts and selects it'),
  ('schema_migrations', 'version',       ARRAY['text','varchar'], ARRAY[]::text[],      'runner and ON CONFLICT (version)'),
  ('schema_migrations', 'applied_at',    ARRAY['timestamptz'],    ARRAY['timestamp'],   'informational only'),
  ('schema_migrations', 'description',   ARRAY['text','varchar'], ARRAY[]::text[],      'every migration inserts it')
),
planned_cols (tbl, col, typ, fmt) AS (VALUES   -- columns migration 003 adds with ADD COLUMN IF NOT EXISTS
  ('class_enrollments', 'status',        'text',        'text NOT NULL DEFAULT ''active'''),
  ('class_enrollments', 'unenrolled_at', 'timestamptz', 'timestamptz'),
  ('class_enrollments', 'unenrolled_by', 'text',        'text'),
  ('class_enrollments', 'updated_at',    'timestamptz', 'timestamptz NOT NULL DEFAULT now()'),
  ('schema_migrations', 'checksum',      'text',        'text')
),
existing_tables (tbl, altered_by_003) AS (VALUES
  ('organizations', false), ('org_memberships', false), ('course_classes', true),
  ('class_enrollments', true), ('schema_migrations', true)
),
checks (sort, section, check_name, status, observed, expected, action) AS (

-- ---------------------------------------------------------------- 0. Context
SELECT 0, '0 Context', 'session',
       'INFO',
       'user=' || current_user || '; database=' || current_database()
         || '; server=' || current_setting('server_version') || '; at=' || now()::text,
       'user=postgres in the Supabase SQL Editor',
       'Ownership/privilege checks below are evaluated for role postgres (the role migrations and the API use).'

-- ---------------------------------------------------------------- 1. Columns
UNION ALL
SELECT 100, '1 Columns', 'table exists: ' || t.tbl,
       CASE WHEN r.relkind IN ('r', 'p') THEN 'PASS' ELSE 'FAIL' END,
       COALESCE('relkind=' || r.relkind, 'missing'),
       'ordinary table (relkind r)',
       CASE WHEN r.relkind IN ('r', 'p') THEN '' ELSE 'Every later check on this table is affected; resolve first.' END
FROM existing_tables t LEFT JOIN rel r ON r.relname = t.tbl

UNION ALL
SELECT 101, '1 Columns', e.tbl || '.' || e.col,
       CASE WHEN a.typ IS NULL THEN 'FAIL'
            WHEN a.typ = ANY (e.ok) THEN 'PASS'
            WHEN a.typ = ANY (e.warn) THEN 'WARN'
            ELSE 'FAIL' END,
       COALESCE(a.fmt || CASE WHEN a.nn THEN ' NOT NULL' ELSE ' NULL' END
                || CASE WHEN a.hasdef THEN ' (has default)' ELSE '' END, 'missing'),
       array_to_string(e.ok, ' or '),
       CASE WHEN a.typ IS NULL THEN 'Missing column required by the API or migrations: ' || e.why
            WHEN a.typ = ANY (e.ok) THEN ''
            WHEN a.typ = ANY (e.warn) THEN 'Usable, differs from 001: ' || e.why
            ELSE 'Incompatible type: ' || e.why END
FROM expected_cols e LEFT JOIN att a ON a.tbl = e.tbl AND a.col = e.col

UNION ALL
SELECT 102, '1 Columns', 'added by 003: ' || p.tbl || '.' || p.col,
       CASE WHEN a.typ IS NULL THEN 'PASS' WHEN a.typ = p.typ THEN 'WARN' ELSE 'FAIL' END,
       COALESCE('already exists: ' || a.fmt || CASE WHEN a.nn THEN ' NOT NULL' ELSE ' NULL' END, 'absent'),
       'absent (003 adds ' || p.fmt || ')',
       CASE WHEN a.typ IS NULL THEN ''
            WHEN a.typ = p.typ THEN '003 keeps the existing column (IF NOT EXISTS). Confirm its meaning, nullability and default match.'
            ELSE '003 would keep an incompatible column. Resolve before migrating.' END
FROM planned_cols p LEFT JOIN att a ON a.tbl = p.tbl AND a.col = p.col

UNION ALL
SELECT 103, '1 Columns', 'existing class_enrollments.status values fit 003 CHECK',
       CASE WHEN s.present IS NULL THEN 'INFO'
            WHEN NOT s.usable THEN 'FAIL'
            WHEN s.v::int = 0 THEN 'PASS' ELSE 'FAIL' END,
       CASE WHEN s.present IS NULL THEN 'column absent (nothing to check)'
            WHEN NOT s.usable THEN 'column type ' || s.present || ' is not text'
            ELSE s.v || ' row(s) with NULL or a value other than active/unenrolled' END,
       '0 invalid rows (or column absent)',
       'Invalid rows make 003 fail (safely, rolled back).'
FROM (SELECT h.e_status AS present, h.e_status IN ('text', 'varchar') AS usable,
             CASE WHEN h.e_status IN ('text', 'varchar') THEN
               (xpath('/row/v/text()', query_to_xml($q$
                 SELECT count(*) AS v FROM public.class_enrollments
                 WHERE status IS NULL OR status::text NOT IN ('active', 'unenrolled')
               $q$, false, true, '')))[1]::text END AS v
      FROM h) s

UNION ALL
SELECT 104, '1 Columns', 'other NOT NULL columns without a default',
       CASE WHEN count(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
       COALESCE(string_agg(a.tbl || '.' || a.col || ' ' || a.fmt, ', ' ORDER BY a.tbl, a.col), 'none'),
       'none',
       CASE WHEN count(*) = 0 THEN ''
            ELSE 'The API and migrations insert only the columns above; these inserts would fail. Add defaults or make them nullable in a NEW migration.' END
FROM att a
WHERE a.tbl IN (SELECT tbl FROM existing_tables)
  AND a.nn AND NOT a.hasdef AND a.ident = '' AND a.gen = ''
  AND NOT EXISTS (SELECT 1 FROM expected_cols e WHERE e.tbl = a.tbl AND e.col = a.col)

UNION ALL
SELECT 105, '1 Columns', 'schema_migrations.applied_at insertable without a value',
       CASE WHEN a.typ IS NULL THEN 'UNAVAILABLE'
            WHEN a.nn AND NOT a.hasdef THEN 'FAIL'
            WHEN NOT a.hasdef THEN 'INFO' ELSE 'PASS' END,
       COALESCE(a.fmt || CASE WHEN a.nn THEN ' NOT NULL' ELSE ' NULL' END
                || CASE WHEN a.hasdef THEN ' with default' ELSE ' without default' END, 'missing'),
       'has a default (001 uses DEFAULT NOW())',
       CASE WHEN a.nn AND NOT a.hasdef THEN 'Migrations insert (version, description) only; 003 would fail.'
            WHEN NOT a.hasdef THEN 'New rows for 003-006 will have NULL applied_at (cosmetic).'
            ELSE '' END
FROM (SELECT 1) d LEFT JOIN att a ON a.tbl = 'schema_migrations' AND a.col = 'applied_at'

UNION ALL
SELECT 106, '1 Columns', 'tables readable by the checking role',
       CASE WHEN count(*) FILTER (WHERE r.oid IS NOT NULL AND NOT has_table_privilege(r.oid, 'SELECT')) = 0 THEN 'PASS' ELSE 'FAIL' END,
       COALESCE('not readable: ' || string_agg(t.tbl, ', ') FILTER (WHERE r.oid IS NOT NULL AND NOT has_table_privilege(r.oid, 'SELECT')),
                'all readable by ' || current_user),
       'all five tables readable',
       'Data checks on an unreadable table report UNAVAILABLE. The role that runs migrations and the API must be able to use every table (see 300/305).'
FROM existing_tables t LEFT JOIN rel r ON r.relname = t.tbl AND r.relkind IN ('r', 'p')

-- ---------------------------------------------------------------- 2. Indexes & constraints
UNION ALL
SELECT 200, '2 Indexes & constraints', 'uq_organizations_name_ci',
       CASE WHEN x.idx IS NULL THEN 'FAIL'
            WHEN x.tbl = 'organizations' AND x.uniq AND x.valid AND NOT x.partial AND x.def ILIKE '%lower(name)%' THEN 'PASS'
            ELSE 'FAIL' END,
       COALESCE(x.def || CASE WHEN x.valid THEN '' ELSE ' (INVALID: not enforced)' END, 'missing'),
       'CREATE UNIQUE INDEX uq_organizations_name_ci ON public.organizations USING btree (lower(name))',
       CASE WHEN x.idx IS NULL THEN 'Missing: organizations with the same name (ignoring case) can be created, and the API relies on this exact index name to return a duplicate-name error. Resolve duplicates (section 6), then adopt contingency migration 007 (scripts/sql/contingency_007_organization_name_ci.sql); never edit 001.'
            WHEN x.tbl = 'organizations' AND x.uniq AND x.valid AND NOT x.partial AND x.def ILIKE '%lower(name)%' THEN ''
            WHEN NOT x.valid THEN 'The index exists but is INVALID (e.g. a failed concurrent build) and enforces nothing. Drop and recreate it in a new migration.'
            ELSE 'An index with this name exists but differs; inspect before migrating.' END
FROM (SELECT 1) d LEFT JOIN ix x ON x.idx = 'uq_organizations_name_ci'

UNION ALL
SELECT 201, '2 Indexes & constraints', 'other case-insensitive unique index on organizations',
       CASE WHEN count(*) = 0 THEN 'PASS' ELSE 'WARN' END,
       COALESCE(string_agg(x.idx || ': ' || x.def, ' | '), 'none'),
       'none (only uq_organizations_name_ci)',
       CASE WHEN count(*) = 0 THEN ''
            ELSE 'A differently named index makes duplicate names surface as a server error instead of a duplicate-name response.' END
FROM ix x
WHERE x.tbl = 'organizations' AND x.uniq AND x.def ILIKE '%lower(%' AND x.idx <> 'uq_organizations_name_ci'

UNION ALL
SELECT 202, '2 Indexes & constraints', 'primary key: ' || p.tbl,
       CASE WHEN (SELECT x.cols FROM ix x WHERE x.tbl = p.tbl AND x.pk) = p.cols THEN 'PASS' ELSE 'FAIL' END,
       COALESCE((SELECT x.idx || ' (' || array_to_string(x.cols, ', ') || ')' FROM ix x WHERE x.tbl = p.tbl AND x.pk), 'no primary key'),
       '(' || array_to_string(p.cols, ', ') || ')',
       ''
FROM (VALUES ('organizations', ARRAY['org_id']), ('org_memberships', ARRAY['membership_id']),
             ('course_classes', ARRAY['class_id']), ('class_enrollments', ARRAY['enrollment_id']),
             ('schema_migrations', ARRAY['version'])) AS p (tbl, cols)

UNION ALL
SELECT 203, '2 Indexes & constraints', 'unique key for ' || u.usage,
       CASE WHEN EXISTS (SELECT 1 FROM ix x WHERE x.tbl = u.tbl AND x.uniq AND x.valid AND NOT x.partial
                                              AND NOT x.expr AND x.cols = u.cols) THEN 'PASS' ELSE 'FAIL' END,
       COALESCE((SELECT string_agg(x.idx || ' (' || COALESCE(array_to_string(x.cols, ', '), 'expression') || ')'
                                   || CASE WHEN x.partial THEN ' partial' ELSE '' END
                                   || CASE WHEN x.valid THEN '' ELSE ' INVALID' END, ' | ')
                   FROM ix x WHERE x.tbl = u.tbl AND x.uniq), 'no unique index'),
       'non-partial unique index on {' || array_to_string(u.cols, ', ') || '} (column order irrelevant)',
       'Without it the API''s upsert fails at runtime (no matching unique constraint).'
FROM (VALUES ('org_memberships', ARRAY['org_id', 'user_id'], 'ON CONFLICT (org_id, user_id)'),
             ('class_enrollments', ARRAY['class_id', 'learner_id'], 'ON CONFLICT (class_id, learner_id)'))
     AS u (tbl, cols, usage)

UNION ALL
SELECT 204, '2 Indexes & constraints', 'foreign key ' || f.tbl || '.' || f.col || ' -> ' || f.reftbl,
       CASE WHEN count(c.oid) > 0 THEN 'PASS' ELSE 'WARN' END,
       COALESCE(string_agg(c.conname || ': ' || c.def, ' | '), 'missing'),
       'FOREIGN KEY (' || f.col || ') REFERENCES ' || f.reftbl || ' (001 uses ON DELETE CASCADE)',
       CASE WHEN count(c.oid) > 0 THEN '' ELSE 'Not required by 003-006, but tenant integrity depends on it.' END
FROM (VALUES ('org_memberships', 'org_id', 'organizations'), ('course_classes', 'org_id', 'organizations'),
             ('class_enrollments', 'class_id', 'course_classes')) AS f (tbl, col, reftbl)
LEFT JOIN con c ON c.nspname = 'public' AND c.contype = 'f' AND c.tbl = f.tbl
               AND c.reftbl = f.reftbl AND c.cols = ARRAY[f.col]
GROUP BY f.tbl, f.col, f.reftbl

UNION ALL
SELECT 205, '2 Indexes & constraints', 'all constraints: ' || t.tbl,
       'INFO',
       COALESCE((SELECT string_agg(c.conname || ' [' || c.contype || ']: ' || c.def, ' | ' ORDER BY c.conname)
                   FROM con c WHERE c.nspname = 'public' AND c.tbl = t.tbl), 'none'),
       '', ''
FROM existing_tables t

UNION ALL
SELECT 206, '2 Indexes & constraints', 'all indexes: ' || t.tbl,
       'INFO',
       COALESCE((SELECT string_agg(x.def, ' | ' ORDER BY x.idx) FROM ix x WHERE x.tbl = t.tbl), 'none'),
       '', ''
FROM existing_tables t

-- ---------------------------------------------------------------- 3. Ownership, RLS, privileges
UNION ALL
SELECT 300, '3 Ownership & RLS', 'owner: ' || t.tbl,
       CASE WHEN r.oid IS NULL OR to_regrole('postgres') IS NULL THEN 'UNAVAILABLE'
            WHEN pg_has_role('postgres', r.relowner, 'MEMBER') THEN 'PASS'
            WHEN t.altered_by_003 THEN 'FAIL' ELSE 'WARN' END,
       COALESCE('owner=' || r.owner, 'table missing'),
       'postgres (or a role postgres is a member of)',
       CASE WHEN r.oid IS NULL THEN ''
            WHEN to_regrole('postgres') IS NULL THEN 'Role postgres not found.'
            WHEN pg_has_role('postgres', r.relowner, 'MEMBER') THEN ''
            WHEN t.altered_by_003 THEN '003 runs ALTER TABLE here; the migrating role must own the table.'
            ELSE 'The API relies on owner rights (RLS has no policies) unless postgres has BYPASSRLS; see 305.' END
FROM existing_tables t LEFT JOIN rel r ON r.relname = t.tbl AND r.relkind IN ('r', 'p')

UNION ALL
SELECT 301, '3 Ownership & RLS', 'postgres can reference ' || t.tbl || ' (FKs in 004-006)',
       CASE WHEN r.oid IS NULL OR to_regrole('postgres') IS NULL THEN 'UNAVAILABLE'
            WHEN has_table_privilege('postgres', r.oid, 'REFERENCES') THEN 'PASS' ELSE 'FAIL' END,
       CASE WHEN r.oid IS NULL OR to_regrole('postgres') IS NULL THEN 'n/a'
            ELSE 'REFERENCES=' || has_table_privilege('postgres', r.oid, 'REFERENCES')::text END,
       'REFERENCES=true',
       ''
FROM (VALUES ('organizations'), ('course_classes')) AS t (tbl)
LEFT JOIN rel r ON r.relname = t.tbl AND r.relkind IN ('r', 'p')

UNION ALL
SELECT 302, '3 Ownership & RLS', 'postgres can CREATE in schema public',
       CASE WHEN to_regrole('postgres') IS NULL THEN 'UNAVAILABLE'
            WHEN has_schema_privilege('postgres', 'public', 'CREATE') THEN 'PASS' ELSE 'FAIL' END,
       CASE WHEN to_regrole('postgres') IS NULL THEN 'role postgres not found'
            ELSE 'CREATE=' || has_schema_privilege('postgres', 'public', 'CREATE')::text END,
       'CREATE=true', '003-006 create nine tables in public.'

UNION ALL
SELECT 303, '3 Ownership & RLS', 'role attributes: ' || v.rolname,
       CASE WHEN r.rolname IS NULL THEN 'WARN' ELSE 'INFO' END,
       COALESCE('rolbypassrls=' || r.rolbypassrls::text || ', rolsuper=' || r.rolsuper::text
                || ', rolcanlogin=' || r.rolcanlogin::text, 'role missing'),
       v.expected, ''
FROM (VALUES ('postgres', 'rolbypassrls=true on Supabase'), ('service_role', 'rolbypassrls=true on Supabase'),
             ('anon', 'rolbypassrls=false'), ('authenticated', 'rolbypassrls=false')) AS v (rolname, expected)
LEFT JOIN pg_roles r ON r.rolname = v.rolname

UNION ALL
SELECT 304, '3 Ownership & RLS', 'RLS: ' || t.tbl,
       CASE WHEN r.oid IS NULL THEN 'UNAVAILABLE'
            WHEN NOT r.rls THEN 'WARN'
            WHEN r.frls AND NOT COALESCE(h.pg_bypass, false) THEN 'FAIL'
            WHEN r.frls THEN 'WARN' ELSE 'PASS' END,
       COALESCE('enabled=' || r.rls::text || ', forced=' || r.frls::text, 'table missing'),
       'enabled=true, forced=false',
       CASE WHEN r.oid IS NULL THEN ''
            WHEN NOT r.rls THEN 'RLS off: anon/authenticated access then depends only on grants (see 307).'
            WHEN r.frls AND NOT COALESCE(h.pg_bypass, false) THEN 'Forced RLS with no policies blocks the owner too; the API would see no rows.'
            WHEN r.frls THEN 'Forced RLS; postgres still bypasses it via BYPASSRLS.'
            ELSE '' END
FROM existing_tables t CROSS JOIN h LEFT JOIN rel r ON r.relname = t.tbl AND r.relkind IN ('r', 'p')

UNION ALL
SELECT 305, '3 Ownership & RLS', 'API role (postgres) can use all four institutional tables',
       CASE WHEN to_regrole('postgres') IS NULL OR count(r.oid) < 4 THEN 'UNAVAILABLE'
            WHEN bool_and(CASE WHEN r.oid IS NULL OR to_regrole('postgres') IS NULL THEN false
                               ELSE ((pg_has_role('postgres', r.relowner, 'MEMBER') AND NOT r.frls)
                                     OR COALESCE(h.pg_bypass, false))
                                    AND has_table_privilege('postgres', r.oid, 'SELECT')
                                    AND has_table_privilege('postgres', r.oid, 'INSERT')
                                    AND has_table_privilege('postgres', r.oid, 'UPDATE')
                                    AND has_table_privilege('postgres', r.oid, 'DELETE') END)
            THEN 'PASS' ELSE 'FAIL' END,
       'tables found=' || count(r.oid) || '; postgres BYPASSRLS=' || COALESCE(h.pg_bypass::text, 'unknown'),
       'owner (RLS not forced) or BYPASSRLS, plus SELECT/INSERT/UPDATE/DELETE',
       'Assumes DATABASE_URL connects as postgres (Supabase direct or session pooler on 5432). A different role needs its own check.'
FROM (VALUES ('organizations'), ('org_memberships'), ('course_classes'), ('class_enrollments')) AS t (tbl)
CROSS JOIN h
LEFT JOIN rel r ON r.relname = t.tbl AND r.relkind IN ('r', 'p')
GROUP BY h.pg_bypass

UNION ALL
SELECT 306, '3 Ownership & RLS', 'policies on existing tables',
       'INFO',
       count(*) || ' policy(ies)' || COALESCE(': ' || string_agg(p.tablename || '.' || p.policyname || ' (' || p.cmd || ')', ', '), ''),
       '0 (none were found during the audit)',
       'With privileges revoked from anon/authenticated (307) policies are moot for them; the API bypasses RLS.'
FROM pg_policies p
WHERE p.schemaname = 'public' AND p.tablename IN (SELECT tbl FROM existing_tables)

UNION ALL
SELECT 307, '3 Ownership & RLS', 'client privileges: ' || g.grantee,
       CASE WHEN g.grantee <> 'public' AND to_regrole(g.grantee) IS NULL THEN 'INFO'
            WHEN count(*) FILTER (WHERE g.has_any) = 0 THEN 'PASS' ELSE 'WARN' END,
       CASE WHEN g.grantee <> 'public' AND to_regrole(g.grantee) IS NULL THEN 'role missing'
            ELSE COALESCE(string_agg(g.tbl, ', ') FILTER (WHERE g.has_any), 'no privileges on the four tables + schema_migrations') END,
       'no privileges (002 revoked them)',
       CASE WHEN count(*) FILTER (WHERE g.has_any) = 0 THEN ''
            ELSE 'Revoke in a NEW migration or rerun the REVOKE from 002 manually; RLS currently blocks rows but grants should be absent.' END
FROM (SELECT gr.grantee, t.tbl,
             CASE WHEN r.oid IS NULL OR (gr.grantee <> 'public' AND to_regrole(gr.grantee) IS NULL) THEN false
                  ELSE has_table_privilege(gr.grantee, r.oid, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') END AS has_any
        FROM (VALUES ('anon'), ('authenticated'), ('public')) AS gr (grantee)
        CROSS JOIN existing_tables t
        LEFT JOIN rel r ON r.relname = t.tbl AND r.relkind IN ('r', 'p')) g
GROUP BY g.grantee

UNION ALL
SELECT 308, '3 Ownership & RLS', 'default privileges for new objects in public',
       'INFO',
       COALESCE(string_agg(pg_get_userbyid(d.defaclrole) || ' [' || d.defaclobjtype::text || ']: '
                           || array_to_string(d.defaclacl, ','), ' | '), 'none'),
       'anon/authenticated likely listed (Supabase default)',
       '003-006 explicitly REVOKE anon/authenticated/PUBLIC on every new table; service_role keeps its default grants.'
FROM pg_default_acl d LEFT JOIN pg_namespace n ON n.oid = d.defaclnamespace
WHERE d.defaclnamespace = 0 OR n.nspname = 'public'

-- ---------------------------------------------------------------- 4. teacher_ids
UNION ALL
SELECT 400, '4 teacher_ids', 'values that are not JSON arrays',
       CASE WHEN s.v IS NULL THEN 'UNAVAILABLE' WHEN s.v::int = 0 THEN 'PASS' ELSE 'FAIL' END,
       COALESCE(s.v || ' row(s)', 'column missing or not jsonb (type: ' || COALESCE(s.t, 'missing') || ')'),
       '0',
       'Any non-array value makes 003 fail when it adds ck_course_classes_teacher_ids_array (rolled back safely).'
FROM (SELECT h.c_tid AS t,
             CASE WHEN h.c_tid = 'jsonb' THEN
               (xpath('/row/v/text()', query_to_xml($q$
                 SELECT count(*) AS v FROM public.course_classes
                 WHERE teacher_ids IS NOT NULL AND jsonb_typeof(teacher_ids) <> 'array'
               $q$, false, true, '')))[1]::text END AS v
      FROM h) s

UNION ALL
SELECT 401, '4 teacher_ids', 'NULL values',
       CASE WHEN s.v IS NULL THEN 'UNAVAILABLE' WHEN s.v::int = 0 THEN 'PASS' ELSE 'WARN' END,
       COALESCE(s.v || ' row(s)', 'column missing or not jsonb'),
       '0',
       'The CHECK accepts NULL; such classes have no teachers. Prefer ''[]''.'
FROM (SELECT CASE WHEN h.c_tid = 'jsonb' THEN
               (xpath('/row/v/text()', query_to_xml($q$
                 SELECT count(*) AS v FROM public.course_classes WHERE teacher_ids IS NULL
               $q$, false, true, '')))[1]::text END AS v
      FROM h) s

UNION ALL
SELECT 402, '4 teacher_ids', 'arrays containing non-string elements',
       CASE WHEN s.v IS NULL THEN 'UNAVAILABLE' WHEN s.v::int = 0 THEN 'PASS' ELSE 'WARN' END,
       COALESCE(s.v || ' row(s)', 'column missing or not jsonb'),
       '0',
       'Teacher ids should be Supabase user ids as strings.'
FROM (SELECT CASE WHEN h.c_tid = 'jsonb' THEN
               (xpath('/row/v/text()', query_to_xml($q$
                 SELECT count(*) AS v FROM public.course_classes c
                 WHERE CASE WHEN jsonb_typeof(c.teacher_ids) = 'array'
                            THEN EXISTS (SELECT 1 FROM jsonb_array_elements(c.teacher_ids) e
                                         WHERE jsonb_typeof(e) <> 'string')
                            ELSE false END
               $q$, false, true, '')))[1]::text END AS v
      FROM h) s

-- ---------------------------------------------------------------- 5. Membership roles
UNION ALL
SELECT 500, '5 Roles', 'enum public.user_role labels',
       CASE WHEN s.labels IS NULL THEN 'INFO'
            WHEN s.labels = 'ADMIN,TEACHER,LEARNER' THEN 'PASS'
            WHEN s.labels LIKE '%ADMIN%' AND s.labels LIKE '%TEACHER%' AND s.labels LIKE '%LEARNER%' THEN 'WARN'
            ELSE 'FAIL' END,
       COALESCE(s.labels, 'type public.user_role does not exist (role column must then be text)'),
       'ADMIN,TEACHER,LEARNER',
       CASE WHEN s.labels IS NULL OR s.labels = 'ADMIN,TEACHER,LEARNER' THEN ''
            ELSE 'The API writes exactly ADMIN, TEACHER and LEARNER.' END
FROM (SELECT (SELECT string_agg(e.enumlabel::text, ',' ORDER BY e.enumsortorder)
                FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid
                JOIN pg_namespace n ON n.oid = t.typnamespace
               WHERE t.typname = 'user_role' AND n.nspname = 'public') AS labels) s

UNION ALL
SELECT 501, '5 Roles', 'role distribution',
       CASE WHEN s.v IS NULL THEN 'UNAVAILABLE' ELSE 'INFO' END,
       COALESCE(s.v, 'role column missing'),
       'only ADMIN / TEACHER / LEARNER', ''
FROM (SELECT CASE WHEN h.m_role IS NOT NULL THEN
               (xpath('/row/v/text()', query_to_xml($q$
                 SELECT string_agg(r || '=' || n, ', ' ORDER BY r) AS v
                 FROM (SELECT COALESCE(role::text, '<NULL>') AS r, count(*) AS n
                       FROM public.org_memberships GROUP BY 1) s
               $q$, false, true, '')))[1]::text END AS v
      FROM h) s

UNION ALL
SELECT 502, '5 Roles', 'memberships with an unexpected role value',
       CASE WHEN s.v IS NULL THEN 'UNAVAILABLE' WHEN s.v::int = 0 THEN 'PASS' ELSE 'FAIL' END,
       COALESCE(s.v || ' row(s)', 'role column missing'),
       '0',
       'Authorization compares role = ''ADMIN''/''TEACHER''/''LEARNER'' exactly (case-sensitive); fix the data first.'
FROM (SELECT CASE WHEN h.m_role IS NOT NULL THEN
               (xpath('/row/v/text()', query_to_xml($q$
                 SELECT count(*) AS v FROM public.org_memberships
                 WHERE role IS NULL OR role::text NOT IN ('ADMIN', 'TEACHER', 'LEARNER')
               $q$, false, true, '')))[1]::text END AS v
      FROM h) s

UNION ALL
SELECT 503, '5 Roles', 'organizations without an active ADMIN',
       CASE WHEN s.v IS NULL THEN 'UNAVAILABLE' WHEN s.v::int = 0 THEN 'PASS' ELSE 'WARN' END,
       COALESCE(s.v || ' organization(s)', 'needed columns missing or incompatible'),
       '0',
       'Nobody can administer such an organization through the API.'
FROM (SELECT CASE WHEN h.o_org IN ('text', 'varchar') AND h.m_org IN ('text', 'varchar')
                   AND h.m_role IS NOT NULL AND h.m_active = 'bool' THEN
               (xpath('/row/v/text()', query_to_xml($q$
                 SELECT count(*) AS v FROM public.organizations o
                 WHERE NOT EXISTS (SELECT 1 FROM public.org_memberships m
                                   WHERE m.org_id = o.org_id AND m.role::text = 'ADMIN'
                                     AND m.is_active IS TRUE)
               $q$, false, true, '')))[1]::text END AS v
      FROM h) s

UNION ALL
SELECT 504, '5 Roles', 'memberships with NULL is_active',
       CASE WHEN s.v IS NULL THEN 'UNAVAILABLE' WHEN s.v::int = 0 THEN 'PASS' ELSE 'WARN' END,
       COALESCE(s.v || ' row(s)', 'is_active missing or not boolean'),
       '0',
       'The API treats NULL as inactive.'
FROM (SELECT CASE WHEN h.m_active = 'bool' THEN
               (xpath('/row/v/text()', query_to_xml($q$
                 SELECT count(*) AS v FROM public.org_memberships WHERE is_active IS NULL
               $q$, false, true, '')))[1]::text END AS v
      FROM h) s

-- ---------------------------------------------------------------- 6. Organization names
UNION ALL
SELECT 600, '6 Org names', 'duplicate names ignoring case (lower(name))',
       CASE WHEN s.v IS NULL THEN 'UNAVAILABLE' WHEN s.v::int = 0 THEN 'PASS' ELSE 'FAIL' END,
       COALESCE(s.v || ' duplicated name(s)' || COALESCE(': ' || s.names, ''), 'name missing or not text'),
       '0',
       'Duplicates block creating uq_organizations_name_ci; rename or merge them first (a product decision).'
FROM (SELECT CASE WHEN h.o_name IN ('text', 'varchar') THEN
               (xpath('/row/v/text()', query_to_xml($q$
                 SELECT count(*) AS v FROM (SELECT lower(name) FROM public.organizations
                                            GROUP BY 1 HAVING count(*) > 1) d
               $q$, false, true, '')))[1]::text END AS v,
             CASE WHEN h.o_name IN ('text', 'varchar') THEN
               (xpath('/row/v/text()', query_to_xml($q$
                 SELECT string_agg(k, '; ' ORDER BY k) AS v
                 FROM (SELECT lower(name) AS k FROM public.organizations
                       GROUP BY 1 HAVING count(*) > 1) d
               $q$, false, true, '')))[1]::text END AS names
      FROM h) s

UNION ALL
SELECT 601, '6 Org names', 'duplicate names ignoring case and surrounding spaces',
       CASE WHEN s.v IS NULL THEN 'UNAVAILABLE' WHEN s.v::int = 0 THEN 'PASS' ELSE 'WARN' END,
       COALESCE(s.v || ' duplicated name(s)', 'name missing or not text'),
       '0',
       'Not blocked by the index (it does not trim) but confusing to users.'
FROM (SELECT CASE WHEN h.o_name IN ('text', 'varchar') THEN
               (xpath('/row/v/text()', query_to_xml($q$
                 SELECT count(*) AS v FROM (SELECT lower(btrim(name)) FROM public.organizations
                                            GROUP BY 1 HAVING count(*) > 1) d
               $q$, false, true, '')))[1]::text END AS v
      FROM h) s

-- ---------------------------------------------------------------- 7. Supabase Auth ids
UNION ALL
SELECT 700, '7 Auth ids', 'auth.users readable',
       CASE WHEN h.auth_ok THEN 'PASS' ELSE 'UNAVAILABLE' END,
       CASE WHEN to_regclass('auth.users') IS NULL THEN 'auth.users not found'
            WHEN h.auth_ok THEN 'readable by ' || current_user
            ELSE 'not readable by ' || current_user END,
       'readable',
       CASE WHEN h.auth_ok THEN '' ELSE 'Rows 702-708 cannot run; compare ids from the Supabase dashboard instead.' END
FROM h

UNION ALL
SELECT 701, '7 Auth ids', 'id column types (inspected before comparing)',
       CASE WHEN h.auth_id IS NULL THEN 'UNAVAILABLE' ELSE 'INFO' END,
       'auth.users.id=' || COALESCE(h.auth_id, 'missing') || '; org_memberships.user_id=' || COALESCE(h.m_user, 'missing')
         || '; class_enrollments.learner_id=' || COALESCE(h.e_lid, 'missing')
         || '; course_classes.teacher_ids=' || COALESCE(h.c_tid, 'missing'),
       'auth.users.id=uuid; the others text',
       'Comparisons cast both sides to text: a uuid renders in lowercase canonical form, so ids stored in another case or with spaces do not match (703/706).'
FROM h

UNION ALL
SELECT 702, '7 Auth ids', 'memberships whose user_id matches no auth.users.id',
       CASE WHEN s.v IS NULL THEN 'UNAVAILABLE' WHEN s.v::int = 0 THEN 'PASS' ELSE 'WARN' END,
       COALESCE(s.v || ' of ' || s.total || ' membership(s)' || COALESCE('; membership_id: ' || s.ids, ''), 'not checked (see 700/701)'),
       '0',
       'The API identifies users by their Supabase id; unmatched members cannot use these memberships. Fix or remove them (data decision).'
FROM (SELECT CASE WHEN h.auth_ok AND h.auth_id IS NOT NULL AND h.m_user IS NOT NULL THEN
               (xpath('/row/v/text()', query_to_xml($q$
                 SELECT count(*) AS v FROM public.org_memberships m
                 WHERE NOT EXISTS (SELECT 1 FROM auth.users u WHERE u.id::text = m.user_id::text)
               $q$, false, true, '')))[1]::text END AS v,
             CASE WHEN h.t_mem THEN
               (xpath('/row/v/text()', query_to_xml($q$
                 SELECT count(*) AS v FROM public.org_memberships
               $q$, false, true, '')))[1]::text END AS total,
             CASE WHEN h.auth_ok AND h.auth_id IS NOT NULL AND h.m_user IS NOT NULL AND h.m_mid IS NOT NULL THEN
               (xpath('/row/v/text()', query_to_xml($q$
                 SELECT string_agg(m.membership_id::text, ', ' ORDER BY m.membership_id::text) AS v
                 FROM public.org_memberships m
                 WHERE NOT EXISTS (SELECT 1 FROM auth.users u WHERE u.id::text = m.user_id::text)
               $q$, false, true, '')))[1]::text END AS ids
      FROM h) s

UNION ALL
SELECT 703, '7 Auth ids', 'memberships matching only after lowercasing/trimming',
       CASE WHEN s.v IS NULL THEN 'UNAVAILABLE' WHEN s.v::int = 0 THEN 'PASS' ELSE 'WARN' END,
       COALESCE(s.v || ' row(s)', 'not checked (see 700/701)'),
       '0',
       'These are the right users stored in a different form; normalize them to the lowercase id.'
FROM (SELECT CASE WHEN h.auth_ok AND h.auth_id IS NOT NULL AND h.m_user IS NOT NULL THEN
               (xpath('/row/v/text()', query_to_xml($q$
                 SELECT count(*) AS v FROM public.org_memberships m
                 WHERE NOT EXISTS (SELECT 1 FROM auth.users u WHERE u.id::text = m.user_id::text)
                   AND EXISTS (SELECT 1 FROM auth.users u WHERE u.id::text = lower(btrim(m.user_id::text)))
               $q$, false, true, '')))[1]::text END AS v
      FROM h) s

UNION ALL
SELECT 704, '7 Auth ids', 'membership user_id values not shaped like a UUID',
       CASE WHEN s.v IS NULL THEN 'UNAVAILABLE' WHEN s.v::int = 0 THEN 'PASS' ELSE 'WARN' END,
       COALESCE(s.v || ' row(s)', 'user_id missing'),
       '0',
       'Legacy/demo ids (e.g. learner_a) cannot belong to a Supabase account.'
FROM (SELECT CASE WHEN h.m_user IS NOT NULL THEN
               (xpath('/row/v/text()', query_to_xml($q$
                 SELECT count(*) AS v FROM public.org_memberships
                 WHERE user_id IS NULL
                    OR user_id::text !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
               $q$, false, true, '')))[1]::text END AS v
      FROM h) s

UNION ALL
SELECT 705, '7 Auth ids', 'enrollments whose learner_id matches no auth.users.id',
       CASE WHEN s.v IS NULL THEN 'UNAVAILABLE' WHEN s.v::int = 0 THEN 'PASS' ELSE 'WARN' END,
       COALESCE(s.v || ' of ' || s.total || ' enrollment(s)' || COALESCE('; enrollment_id: ' || s.ids, ''), 'not checked (see 700/701)'),
       '0',
       'Unmatched learners cannot see these enrollments.'
FROM (SELECT CASE WHEN h.auth_ok AND h.auth_id IS NOT NULL AND h.e_lid IS NOT NULL THEN
               (xpath('/row/v/text()', query_to_xml($q$
                 SELECT count(*) AS v FROM public.class_enrollments e
                 WHERE NOT EXISTS (SELECT 1 FROM auth.users u WHERE u.id::text = e.learner_id::text)
               $q$, false, true, '')))[1]::text END AS v,
             CASE WHEN h.t_enr THEN
               (xpath('/row/v/text()', query_to_xml($q$
                 SELECT count(*) AS v FROM public.class_enrollments
               $q$, false, true, '')))[1]::text END AS total,
             CASE WHEN h.auth_ok AND h.auth_id IS NOT NULL AND h.e_lid IS NOT NULL AND h.e_eid IS NOT NULL THEN
               (xpath('/row/v/text()', query_to_xml($q$
                 SELECT string_agg(e.enrollment_id::text, ', ' ORDER BY e.enrollment_id::text) AS v
                 FROM public.class_enrollments e
                 WHERE NOT EXISTS (SELECT 1 FROM auth.users u WHERE u.id::text = e.learner_id::text)
               $q$, false, true, '')))[1]::text END AS ids
      FROM h) s

UNION ALL
SELECT 706, '7 Auth ids', 'enrollments matching only after lowercasing/trimming',
       CASE WHEN s.v IS NULL THEN 'UNAVAILABLE' WHEN s.v::int = 0 THEN 'PASS' ELSE 'WARN' END,
       COALESCE(s.v || ' row(s)', 'not checked (see 700/701)'),
       '0', 'Normalize to the lowercase id.'
FROM (SELECT CASE WHEN h.auth_ok AND h.auth_id IS NOT NULL AND h.e_lid IS NOT NULL THEN
               (xpath('/row/v/text()', query_to_xml($q$
                 SELECT count(*) AS v FROM public.class_enrollments e
                 WHERE NOT EXISTS (SELECT 1 FROM auth.users u WHERE u.id::text = e.learner_id::text)
                   AND EXISTS (SELECT 1 FROM auth.users u WHERE u.id::text = lower(btrim(e.learner_id::text)))
               $q$, false, true, '')))[1]::text END AS v
      FROM h) s

UNION ALL
SELECT 707, '7 Auth ids', 'teacher_ids entries matching no auth.users.id',
       CASE WHEN s.v IS NULL THEN 'UNAVAILABLE' WHEN s.v::int = 0 THEN 'PASS' ELSE 'WARN' END,
       COALESCE(s.v || ' entr(ies)', 'not checked (see 700/701, 400)'),
       '0', 'Unmatched teachers cannot act on the class.'
FROM (SELECT CASE WHEN h.auth_ok AND h.auth_id IS NOT NULL AND h.c_tid = 'jsonb' THEN
               (xpath('/row/v/text()', query_to_xml($q$
                 SELECT count(*) AS v
                 FROM public.course_classes c
                 CROSS JOIN LATERAL jsonb_array_elements_text(
                     CASE WHEN jsonb_typeof(c.teacher_ids) = 'array' THEN c.teacher_ids ELSE '[]'::jsonb END) AS t (id)
                 WHERE NOT EXISTS (SELECT 1 FROM auth.users u WHERE u.id::text = t.id)
               $q$, false, true, '')))[1]::text END AS v
      FROM h) s

UNION ALL
SELECT 708, '7 Auth ids', 'memberships pointing at soft-deleted auth users',
       CASE WHEN s.v IS NULL THEN 'UNAVAILABLE' WHEN s.v::int = 0 THEN 'PASS' ELSE 'WARN' END,
       COALESCE(s.v || ' row(s)', 'not checked (auth.users.deleted_at absent or unreadable)'),
       '0', 'Deleted accounts cannot sign in; deactivate these memberships.'
FROM (SELECT CASE WHEN h.auth_ok AND h.auth_deleted AND h.auth_id IS NOT NULL AND h.m_user IS NOT NULL THEN
               (xpath('/row/v/text()', query_to_xml($q$
                 SELECT count(*) AS v FROM public.org_memberships m
                 JOIN auth.users u ON u.id::text = m.user_id::text
                 WHERE u.deleted_at IS NOT NULL
               $q$, false, true, '')))[1]::text END AS v
      FROM h) s

-- ---------------------------------------------------------------- 8. Names 003-006 will create
UNION ALL
SELECT 800, '8 New object names', 'tables created by 003-006 already present in public',
       CASE WHEN count(r.oid) = 0 THEN 'PASS' ELSE 'FAIL' END,
       COALESCE(string_agg(r.relname || ' (relkind ' || r.relkind || ', owner ' || r.owner || ')', ', '), 'none'),
       'none of: users, audit_events, document_owners, document_shares, plans, org_plan_assignments, quota_limits, usage_events, jobs',
       CASE WHEN count(r.oid) = 0 THEN ''
            ELSE 'CREATE TABLE IF NOT EXISTS would silently keep the existing object, and the following statements might not match it. Inspect before migrating.' END
FROM (VALUES ('users'), ('audit_events'), ('document_owners'), ('document_shares'), ('plans'),
             ('org_plan_assignments'), ('quota_limits'), ('usage_events'), ('jobs')) AS n (name)
LEFT JOIN rel r ON r.relname = n.name

UNION ALL
SELECT 801, '8 New object names', 'same table names in other schemas',
       'INFO',
       COALESCE(string_agg(ns.nspname || '.' || c.relname, ', ' ORDER BY ns.nspname, c.relname), 'none'),
       'e.g. auth.users (expected; unrelated)',
       'Harmless: migrations create in the first schema of search_path (see 1003).'
FROM pg_class c JOIN pg_namespace ns ON ns.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f')
  AND ns.nspname NOT IN ('public', 'pg_catalog', 'information_schema')
  AND c.relname IN ('users', 'audit_events', 'document_owners', 'document_shares', 'plans',
                    'org_plan_assignments', 'quota_limits', 'usage_events', 'jobs')

UNION ALL
SELECT 802, '8 New object names', 'index/key names created by 003-006 already used in public',
       CASE WHEN count(r.oid) = 0 THEN 'PASS' ELSE 'FAIL' END,
       COALESCE(string_agg(r.relname || ' (relkind ' || r.relkind || ')', ', '), 'none'),
       'none',
       CASE WHEN count(r.oid) = 0 THEN ''
            ELSE 'CREATE INDEX IF NOT EXISTS would silently skip; a clashing key name makes CREATE TABLE fail (rolled back). Inspect each.' END
FROM (VALUES ('idx_users_email_lower'), ('idx_class_enrollments_active'), ('idx_audit_events_org_time'),
             ('idx_audit_events_actor_time'), ('idx_audit_events_target'), ('idx_document_owners_owner'),
             ('idx_document_shares_class'), ('idx_usage_events_org_dim_time'), ('idx_usage_events_user_time'),
             ('idx_jobs_owner_created'), ('idx_jobs_document'), ('idx_jobs_active'),
             ('users_pkey'), ('audit_events_pkey'), ('document_owners_pkey'), ('document_shares_pkey'),
             ('plans_pkey'), ('org_plan_assignments_pkey'), ('quota_limits_pkey'), ('usage_events_pkey'),
             ('jobs_pkey'), ('uq_usage_events_request_id'), ('uq_jobs_owner_idempotency')) AS n (name)
LEFT JOIN rel r ON r.relname = n.name

UNION ALL
SELECT 803, '8 New object names', 'function public.audit_events_reject_mutation()',
       CASE WHEN to_regprocedure('public.audit_events_reject_mutation()') IS NULL THEN 'PASS' ELSE 'WARN' END,
       CASE WHEN to_regprocedure('public.audit_events_reject_mutation()') IS NULL THEN 'absent' ELSE 'exists' END,
       'absent',
       CASE WHEN to_regprocedure('public.audit_events_reject_mutation()') IS NULL THEN ''
            ELSE '003 uses CREATE OR REPLACE and would overwrite it; make sure nothing else uses it.' END

-- ---------------------------------------------------------------- 9. 003 constraint & trigger names
UNION ALL
SELECT 900, '9 003 names', 'constraint ' || n.name,
       CASE WHEN count(c.oid) = 0 THEN 'PASS'
            WHEN bool_and(c.nspname = 'public' AND c.tbl = n.tbl AND c.def ILIKE n.frag) THEN 'WARN'
            ELSE 'FAIL' END,
       COALESCE(string_agg(c.nspname || '.' || COALESCE(c.tbl, '?') || ': ' || c.def, ' | '), 'absent'),
       'absent (003 adds it on public.' || n.tbl || ')',
       CASE WHEN count(c.oid) = 0 THEN ''
            WHEN bool_and(c.nspname = 'public' AND c.tbl = n.tbl AND c.def ILIKE n.frag) THEN '003 keeps the existing equivalent constraint.'
            ELSE '003 checks this name in ANY schema/table and would then skip its own constraint. Rename the other constraint first.' END
FROM (VALUES ('ck_class_enrollments_status', 'class_enrollments', '%active%unenrolled%'),
             ('ck_course_classes_teacher_ids_array', 'course_classes', '%jsonb_typeof%teacher_ids%array%')) AS n (name, tbl, frag)
LEFT JOIN con c ON c.conname = n.name
GROUP BY n.name, n.tbl, n.frag

UNION ALL
SELECT 901, '9 003 names', 'trigger ' || n.name,
       CASE WHEN count(t.oid) = 0 THEN 'PASS' ELSE 'INFO' END,
       COALESCE(string_agg(ns.nspname || '.' || c.relname, ', '), 'absent'),
       'absent',
       CASE WHEN count(t.oid) = 0 THEN ''
            ELSE 'Only relevant if on public.audit_events (which should not exist yet, see 800).' END
FROM (VALUES ('trg_audit_events_append_only'), ('trg_audit_events_no_truncate')) AS n (name)
LEFT JOIN pg_trigger t ON t.tgname = n.name
LEFT JOIN pg_class c ON c.oid = t.tgrelid
LEFT JOIN pg_namespace ns ON ns.oid = c.relnamespace
GROUP BY n.name

-- ---------------------------------------------------------------- 10. Overall compatibility
UNION ALL
SELECT 1000, '10 Compatibility', 'server version',
       CASE WHEN current_setting('server_version_num')::int >= 130000 THEN 'PASS' ELSE 'FAIL' END,
       current_setting('server_version'), '>= 13', ''

UNION ALL
SELECT 1001, '10 Compatibility', 'gen_random_uuid() available (003, 005)',
       CASE WHEN to_regprocedure('gen_random_uuid()') IS NOT NULL THEN 'PASS' ELSE 'FAIL' END,
       COALESCE(to_regprocedure('gen_random_uuid()')::text, 'not found on search_path'),
       'available', ''

UNION ALL
SELECT 1002, '10 Compatibility', 'recorded migration versions',
       CASE WHEN s.v IS NULL THEN 'UNAVAILABLE' WHEN s.v = '001,002' THEN 'PASS' ELSE 'FAIL' END,
       COALESCE(s.v, 'schema_migrations.version missing'),
       '001,002',
       CASE WHEN s.v = '001,002' THEN 'scripts/migrate.py status should then report pending 003-006 and unverified 001, 002.'
            ELSE 'Unexpected history: the runner refuses unknown or out-of-order versions. Investigate before migrating.' END
FROM (SELECT CASE WHEN h.s_ver IS NOT NULL THEN
               (xpath('/row/v/text()', query_to_xml($q$
                 SELECT string_agg(version::text, ',' ORDER BY version::text) AS v FROM public.schema_migrations
               $q$, false, true, '')))[1]::text END AS v
      FROM h) s

UNION ALL
SELECT 1003, '10 Compatibility', 'search_path for unqualified names in 003-006',
       CASE WHEN to_regnamespace('postgres') IS NOT NULL AND current_setting('search_path') LIKE '%$user%' THEN 'FAIL'
            WHEN current_setting('search_path') NOT LIKE '%public%' THEN 'FAIL'
            ELSE 'PASS' END,
       'search_path=' || current_setting('search_path')
         || '; schema named postgres ' || CASE WHEN to_regnamespace('postgres') IS NULL THEN 'absent' ELSE 'EXISTS' END,
       'public resolves first (no schema named postgres)',
       'Migrations create unqualified tables; with "$user" first and a schema named postgres they would land there. The migration connection may use a different search_path than the SQL Editor; check it if a role-level setting exists.'

UNION ALL
SELECT 1004, '10 Compatibility', 'join/foreign-key types compatible',
       CASE WHEN h.m_user IN ('text', 'varchar') AND h.e_lid IN ('text', 'varchar')
             AND h.o_org IN ('text', 'varchar') AND h.c_cid IN ('text', 'varchar') THEN 'PASS' ELSE 'FAIL' END,
       'user_id=' || COALESCE(h.m_user, 'missing') || ', learner_id=' || COALESCE(h.e_lid, 'missing')
         || ', organizations.org_id=' || COALESCE(h.o_org, 'missing') || ', course_classes.class_id=' || COALESCE(h.c_cid, 'missing'),
       'all text/varchar',
       'Roster query joins user_id = learner_id; 004-006 add TEXT foreign keys to org_id and class_id. uuid columns would break both.'
FROM h

UNION ALL
SELECT 1005, '10 Compatibility', 'row counts',
       CASE WHEN s.o IS NULL OR s.m IS NULL OR s.c IS NULL OR s.e IS NULL THEN 'UNAVAILABLE'
            WHEN s.o = '5' AND s.m = '8' AND s.c = '3' AND s.e = '2' THEN 'PASS' ELSE 'WARN' END,
       'organizations=' || COALESCE(s.o, '?') || ', org_memberships=' || COALESCE(s.m, '?')
         || ', course_classes=' || COALESCE(s.c, '?') || ', class_enrollments=' || COALESCE(s.e, '?'),
       'organizations=5, org_memberships=8, course_classes=3, class_enrollments=2 (audit)',
       'A difference only means data changed since the audit; re-take the backup if so. Record these numbers to compare after migrating.'
FROM (SELECT
        CASE WHEN h.t_org THEN (xpath('/row/v/text()', query_to_xml($q$SELECT count(*) AS v FROM public.organizations$q$, false, true, '')))[1]::text END AS o,
        CASE WHEN h.t_mem THEN (xpath('/row/v/text()', query_to_xml($q$SELECT count(*) AS v FROM public.org_memberships$q$, false, true, '')))[1]::text END AS m,
        CASE WHEN h.t_cls THEN (xpath('/row/v/text()', query_to_xml($q$SELECT count(*) AS v FROM public.course_classes$q$, false, true, '')))[1]::text END AS c,
        CASE WHEN h.t_enr THEN (xpath('/row/v/text()', query_to_xml($q$SELECT count(*) AS v FROM public.class_enrollments$q$, false, true, '')))[1]::text END AS e
      FROM h) s

UNION ALL
SELECT 1006, '10 Compatibility', 'enrollments without an active LEARNER membership in the class''s organization',
       CASE WHEN s.v IS NULL THEN 'UNAVAILABLE' WHEN s.v::int = 0 THEN 'PASS' ELSE 'WARN' END,
       COALESCE(s.v || ' enrollment(s)', 'needed columns missing or incompatible'),
       '0',
       'After 003 every existing enrollment is status=active, but rosters/analytics only include learners with an active LEARNER membership in the org.'
FROM (SELECT CASE WHEN h.e_lid IN ('text', 'varchar') AND h.e_cid IN ('text', 'varchar')
                   AND h.c_cid IN ('text', 'varchar') AND h.c_org IN ('text', 'varchar')
                   AND h.m_org IN ('text', 'varchar') AND h.m_user IN ('text', 'varchar')
                   AND h.m_role IS NOT NULL AND h.m_active = 'bool' THEN
               (xpath('/row/v/text()', query_to_xml($q$
                 SELECT count(*) AS v
                 FROM public.class_enrollments e
                 JOIN public.course_classes c ON c.class_id = e.class_id
                 WHERE NOT EXISTS (SELECT 1 FROM public.org_memberships m
                                   WHERE m.org_id = c.org_id AND m.user_id = e.learner_id
                                     AND m.role::text = 'LEARNER' AND m.is_active IS TRUE)
               $q$, false, true, '')))[1]::text END AS v
      FROM h) s

UNION ALL
SELECT 1007, '10 Compatibility', 'user triggers on existing tables',
       'INFO',
       COALESCE(string_agg(r.relname || '.' || t.tgname, ', ' ORDER BY r.relname, t.tgname), 'none'),
       'none expected',
       'Triggers can interfere with API writes or 003''s column additions; review any listed.'
FROM pg_trigger t JOIN rel r ON r.oid = t.tgrelid
WHERE NOT t.tgisinternal AND r.relname IN (SELECT tbl FROM existing_tables)

UNION ALL
SELECT 1008, '10 Compatibility', 'event triggers (fire on DDL)',
       'INFO',
       COALESCE(string_agg(e.evtname || ' (' || e.evtevent || CASE WHEN e.evtenabled = 'D' THEN ', disabled' ELSE '' END || ')',
                           ', ' ORDER BY e.evtname), 'none'),
       'Supabase platform triggers (e.g. pgrst_*, graphql) are normal',
       'Any non-platform trigger listed here will run during 003-006; review it.'
FROM pg_event_trigger e

UNION ALL
SELECT 1009, '10 Compatibility', 'duplicate (org_id, user_id) membership pairs',
       CASE WHEN s.v IS NULL THEN 'UNAVAILABLE' WHEN s.v::int = 0 THEN 'PASS' ELSE 'FAIL' END,
       COALESCE(s.v || ' duplicated pair(s)', 'needed columns missing'),
       '0',
       'The API upserts on (org_id, user_id); duplicates also block (re)creating that unique key. Merge them first.'
FROM (SELECT CASE WHEN h.m_org IS NOT NULL AND h.m_user IS NOT NULL THEN
               (xpath('/row/v/text()', query_to_xml($q$
                 SELECT count(*) AS v FROM (SELECT 1 FROM public.org_memberships
                                            GROUP BY org_id, user_id HAVING count(*) > 1) d
               $q$, false, true, '')))[1]::text END AS v
      FROM h) s

UNION ALL
SELECT 1010, '10 Compatibility', 'duplicate (class_id, learner_id) enrollment pairs',
       CASE WHEN s.v IS NULL THEN 'UNAVAILABLE' WHEN s.v::int = 0 THEN 'PASS' ELSE 'FAIL' END,
       COALESCE(s.v || ' duplicated pair(s)', 'needed columns missing'),
       '0',
       'The API upserts on (class_id, learner_id); duplicates also block (re)creating that unique key. Merge them first.'
FROM (SELECT CASE WHEN h.e_cid IS NOT NULL AND h.e_lid IS NOT NULL THEN
               (xpath('/row/v/text()', query_to_xml($q$
                 SELECT count(*) AS v FROM (SELECT 1 FROM public.class_enrollments
                                            GROUP BY class_id, learner_id HAVING count(*) > 1) d
               $q$, false, true, '')))[1]::text END AS v
      FROM h) s

UNION ALL
SELECT 1011, '10 Compatibility', 'rows whose parent row is missing (orphans)',
       CASE WHEN s.v IS NULL THEN 'UNAVAILABLE' WHEN s.v = '0,0,0' THEN 'PASS' ELSE 'WARN' END,
       COALESCE('memberships without organization, classes without organization, enrollments without class = ' || s.v,
                'needed columns missing or incompatible'),
       '0,0,0',
       'Possible only where a foreign key is missing (204). Orphans are invisible to the API; remove or re-parent them.'
FROM (SELECT CASE WHEN h.o_org IN ('text', 'varchar') AND h.m_org IN ('text', 'varchar')
                   AND h.c_org IN ('text', 'varchar') AND h.c_cid IN ('text', 'varchar')
                   AND h.e_cid IN ('text', 'varchar') THEN
               (xpath('/row/v/text()', query_to_xml($q$
                 SELECT (SELECT count(*) FROM public.org_memberships m
                          WHERE NOT EXISTS (SELECT 1 FROM public.organizations o WHERE o.org_id = m.org_id))
                        || ',' ||
                        (SELECT count(*) FROM public.course_classes c
                          WHERE NOT EXISTS (SELECT 1 FROM public.organizations o WHERE o.org_id = c.org_id))
                        || ',' ||
                        (SELECT count(*) FROM public.class_enrollments e
                          WHERE NOT EXISTS (SELECT 1 FROM public.course_classes c WHERE c.class_id = e.class_id)) AS v
               $q$, false, true, '')))[1]::text END AS v
      FROM h) s
)
SELECT sort, section, check_name, status, observed, expected, action
FROM checks
ORDER BY sort, check_name;
