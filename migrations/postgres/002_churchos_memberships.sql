-- AUTHOR_REVIEW_REQUIRED. Requires the separately provisioned PostgreSQL roles.
-- Execute inside one migration transaction.
CREATE SCHEMA jl_churchos AUTHORIZATION jl_migration_owner;
SET LOCAL ROLE jl_migration_owner;
REVOKE ALL ON SCHEMA jl_churchos FROM PUBLIC;

CREATE TABLE jl_churchos.memberships (
    account_id uuid NOT NULL,
    church_id uuid NOT NULL,
    can_manage_memberships boolean NOT NULL DEFAULT false,
    revoked_at timestamptz,
    PRIMARY KEY (account_id, church_id)
);

ALTER TABLE jl_churchos.memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE jl_churchos.memberships FORCE ROW LEVEL SECURITY;

CREATE POLICY own_active_membership ON jl_churchos.memberships
    FOR SELECT TO jl_api_runtime
    USING (revoked_at IS NULL
       AND account_id::text = current_setting('jesuslife.account_id', true)
       AND church_id::text = current_setting('jesuslife.church_id', true));

GRANT USAGE ON SCHEMA jl_churchos TO jl_api_runtime;
GRANT SELECT ON jl_churchos.memberships TO jl_api_runtime;
RESET ROLE;
