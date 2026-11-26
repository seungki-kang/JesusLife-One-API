-- CANDIDATE ONLY: NOT APPROVED FOR LIVE APPLICATION.
-- Requires existing jl_migration_owner. Run only in an isolated reviewed harness.
-- Authentication runtime receives no backup privileges.
BEGIN;

CREATE ROLE jl_ld_backup_runtime
    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION NOBYPASSRLS;

CREATE SCHEMA jl_ld_backup AUTHORIZATION jl_migration_owner;
SET LOCAL ROLE jl_migration_owner;

REVOKE ALL ON SCHEMA jl_ld_backup FROM PUBLIC;

CREATE TABLE jl_ld_backup.schema_version (
    version integer PRIMARY KEY CHECK (version = 1)
);
INSERT INTO jl_ld_backup.schema_version VALUES (1);

CREATE TABLE jl_ld_backup.consent (
    account_id uuid PRIMARY KEY,
    generation bigint NOT NULL CHECK (generation > 0),
    active boolean NOT NULL
);

CREATE TABLE jl_ld_backup.entries (
    account_id uuid NOT NULL,
    generation bigint NOT NULL CHECK (generation > 0),
    backup_id uuid NOT NULL CHECK (
        substring(backup_id::text, 15, 1) = '4'
        AND substring(backup_id::text, 20, 1) IN ('8', '9', 'a', 'b')
    ),
    format_version integer NOT NULL CHECK (format_version = 1),
    ciphertext bytea NOT NULL CHECK (
        octet_length(ciphertext) BETWEEN 29 AND 49152
    ),
    PRIMARY KEY (account_id, generation, backup_id),
    FOREIGN KEY (account_id) REFERENCES jl_ld_backup.consent(account_id)
);

REVOKE ALL ON ALL TABLES IN SCHEMA jl_ld_backup FROM PUBLIC;
GRANT USAGE ON SCHEMA jl_ld_backup TO jl_ld_backup_runtime;
GRANT SELECT ON jl_ld_backup.schema_version TO jl_ld_backup_runtime;
GRANT SELECT, INSERT, UPDATE ON jl_ld_backup.consent TO jl_ld_backup_runtime;
GRANT SELECT, INSERT, DELETE ON jl_ld_backup.entries TO jl_ld_backup_runtime;

ALTER TABLE jl_ld_backup.schema_version ENABLE ROW LEVEL SECURITY;
ALTER TABLE jl_ld_backup.schema_version FORCE ROW LEVEL SECURITY;
CREATE POLICY version_read ON jl_ld_backup.schema_version
    FOR SELECT TO jl_ld_backup_runtime USING (version = 1);

ALTER TABLE jl_ld_backup.consent ENABLE ROW LEVEL SECURITY;
ALTER TABLE jl_ld_backup.consent FORCE ROW LEVEL SECURITY;
CREATE POLICY consent_owner ON jl_ld_backup.consent
    TO jl_ld_backup_runtime
    USING (
        current_setting('jesuslife.backup_app_id', true) = 'life_diary'
        AND account_id::text = current_setting('jesuslife.backup_account_id', true)
    )
    WITH CHECK (
        current_setting('jesuslife.backup_app_id', true) = 'life_diary'
        AND account_id::text = current_setting('jesuslife.backup_account_id', true)
    );

ALTER TABLE jl_ld_backup.entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE jl_ld_backup.entries FORCE ROW LEVEL SECURITY;
CREATE POLICY entry_owner ON jl_ld_backup.entries
    TO jl_ld_backup_runtime
    USING (
        current_setting('jesuslife.backup_app_id', true) = 'life_diary'
        AND account_id::text = current_setting('jesuslife.backup_account_id', true)
    )
    WITH CHECK (
        current_setting('jesuslife.backup_app_id', true) = 'life_diary'
        AND account_id::text = current_setting('jesuslife.backup_account_id', true)
    );

-- RLS enforces account isolation, not consent activity or generation.
-- Store operations must lock the consent row and check active/generation
-- in the same transaction as upload, download, grant or withdrawal.
-- Account context must come only from verified Life Diary authentication.
-- Custom settings are trusted server context, not protection from a stolen DB role.
RESET ROLE;
COMMIT;
