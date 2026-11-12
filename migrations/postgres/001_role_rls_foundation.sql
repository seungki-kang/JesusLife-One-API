-- AUTHOR_REVIEW_REQUIRED. Local synthetic foundation only, not product tables.
-- Execute as an isolated cluster administrator inside ONE caller transaction.
-- Fresh install only: existing names intentionally fail, never alter live roles.
CREATE ROLE jl_migration_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION NOBYPASSRLS;
CREATE ROLE jl_api_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION NOBYPASSRLS;
-- NOINHERIT alone does not prevent SET ROLE. Grant NO role memberships.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
CREATE SCHEMA jl_rls_foundation AUTHORIZATION jl_migration_owner;
SET LOCAL ROLE jl_migration_owner;
REVOKE ALL ON SCHEMA jl_rls_foundation FROM PUBLIC;

CREATE TABLE jl_rls_foundation.memberships (
    account_id uuid NOT NULL,
    church_id uuid NOT NULL,
    can_write boolean NOT NULL DEFAULT false,
    PRIMARY KEY (account_id, church_id)
);
CREATE TABLE jl_rls_foundation.synthetic_records (
    record_id uuid PRIMARY KEY,
    church_id uuid NOT NULL,
    marker text NOT NULL CHECK (marker = 'synthetic')
);
ALTER TABLE jl_rls_foundation.memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE jl_rls_foundation.memberships FORCE ROW LEVEL SECURITY;
ALTER TABLE jl_rls_foundation.synthetic_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE jl_rls_foundation.synthetic_records FORCE ROW LEVEL SECURITY;

CREATE POLICY own_membership ON jl_rls_foundation.memberships
    FOR SELECT TO jl_api_runtime
    USING (account_id::text = current_setting('jesuslife.account_id', true)
       AND church_id::text = current_setting('jesuslife.church_id', true));
CREATE POLICY church_read ON jl_rls_foundation.synthetic_records
    FOR SELECT TO jl_api_runtime
    USING (church_id::text = current_setting('jesuslife.church_id', true)
       AND EXISTS (SELECT 1 FROM jl_rls_foundation.memberships m
                   WHERE m.church_id = synthetic_records.church_id));
CREATE POLICY church_insert ON jl_rls_foundation.synthetic_records
    FOR INSERT TO jl_api_runtime
    WITH CHECK (church_id::text = current_setting('jesuslife.church_id', true)
       AND EXISTS (SELECT 1 FROM jl_rls_foundation.memberships m
                   WHERE m.church_id = synthetic_records.church_id AND m.can_write));
CREATE POLICY church_update ON jl_rls_foundation.synthetic_records
    FOR UPDATE TO jl_api_runtime
    USING (church_id::text = current_setting('jesuslife.church_id', true)
       AND EXISTS (SELECT 1 FROM jl_rls_foundation.memberships m
                   WHERE m.church_id = synthetic_records.church_id AND m.can_write))
    WITH CHECK (church_id::text = current_setting('jesuslife.church_id', true)
       AND EXISTS (SELECT 1 FROM jl_rls_foundation.memberships m
                   WHERE m.church_id = synthetic_records.church_id AND m.can_write));
CREATE POLICY church_delete ON jl_rls_foundation.synthetic_records
    FOR DELETE TO jl_api_runtime
    USING (church_id::text = current_setting('jesuslife.church_id', true)
       AND EXISTS (SELECT 1 FROM jl_rls_foundation.memberships m
                   WHERE m.church_id = synthetic_records.church_id AND m.can_write));

GRANT USAGE ON SCHEMA jl_rls_foundation TO jl_api_runtime;
GRANT SELECT ON jl_rls_foundation.memberships TO jl_api_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON jl_rls_foundation.synthetic_records TO jl_api_runtime;
RESET ROLE;
