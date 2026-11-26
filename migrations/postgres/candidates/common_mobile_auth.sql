-- CANDIDATE ONLY. Existing jl_core_auth schema required. Not yet applied live.
-- Run as administrator in one transaction; no account/identity replacement.
SET LOCAL ROLE jl_migration_owner;
CREATE TABLE jl_core_auth.common_mobile_schema_version (version INT PRIMARY KEY);
INSERT INTO jl_core_auth.common_mobile_schema_version VALUES (1);
CREATE TABLE jl_core_auth.mobile_logins (
 state_hash BYTEA PRIMARY KEY,
 transaction_id VARCHAR(36) NOT NULL UNIQUE,
 challenge BYTEA NOT NULL,
 app_id BYTEA NOT NULL,
 client_id BYTEA NOT NULL,
 return_uri BYTEA NOT NULL,
 browser_ciphertext BYTEA,
 handoff_hash BYTEA UNIQUE,
 credential_ciphertext BYTEA,
 account_id VARCHAR(36) REFERENCES jl_core_auth.accounts(account_id),
 expires_at TIMESTAMP(6) NOT NULL,
 consumed_at TIMESTAMP(6)
);
REVOKE ALL ON jl_core_auth.common_mobile_schema_version, jl_core_auth.mobile_logins FROM PUBLIC;
GRANT SELECT ON jl_core_auth.common_mobile_schema_version TO jl_core_auth_runtime;
ALTER TABLE jl_core_auth.common_mobile_schema_version ENABLE ROW LEVEL SECURITY;
ALTER TABLE jl_core_auth.common_mobile_schema_version FORCE ROW LEVEL SECURITY;
CREATE POLICY common_mobile_version_read ON jl_core_auth.common_mobile_schema_version
 FOR SELECT TO jl_core_auth_runtime USING (version=1);
GRANT SELECT, INSERT, UPDATE ON jl_core_auth.mobile_logins TO jl_core_auth_runtime;
ALTER TABLE jl_core_auth.mobile_logins ENABLE ROW LEVEL SECURITY;
ALTER TABLE jl_core_auth.mobile_logins FORCE ROW LEVEL SECURITY;
CREATE POLICY app_mobile_login ON jl_core_auth.mobile_logins TO jl_core_auth_runtime
 USING (app_id=convert_to(current_setting('jesuslife.auth_app_id',true),'UTF8'))
 WITH CHECK (app_id=convert_to(current_setting('jesuslife.auth_app_id',true),'UTF8'));
RESET ROLE;
