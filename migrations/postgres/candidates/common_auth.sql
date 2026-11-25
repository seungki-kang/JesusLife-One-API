-- CANDIDATE ONLY. Fresh isolated development DB, not a live migration command.
-- Prerequisites: NOLOGIN owner jl_migration_owner and a dedicated
-- LOGIN NOSUPERUSER NOBYPASSRLS NOINHERIT jl_core_auth_runtime.
-- Execute in one administrator transaction. Fail if the schema already exists.
-- No copying, deleting or re-identifying existing MySQL/LD accounts here.
CREATE SCHEMA jl_core_auth AUTHORIZATION jl_migration_owner;
SET LOCAL ROLE jl_migration_owner;
SET LOCAL search_path TO jl_core_auth, pg_catalog;
REVOKE ALL ON SCHEMA jl_core_auth FROM PUBLIC;
CREATE TABLE core_schema_version (
    version INT NOT NULL PRIMARY KEY,
    applied_at TIMESTAMP(6) NOT NULL
);

CREATE TABLE accounts (
    account_id VARCHAR(36) NOT NULL PRIMARY KEY,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    security_version BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMP(6) NOT NULL,
    CONSTRAINT core_account_status CHECK (status IN ('active', 'disabled', 'deletion_pending', 'deleting', 'deleted'))
);

CREATE TABLE external_identities (
    issuer BYTEA NOT NULL,
    provider_subject BYTEA NOT NULL,
    account_id VARCHAR(36) NOT NULL,
    created_at TIMESTAMP(6) NOT NULL,
    PRIMARY KEY (issuer, provider_subject),
    UNIQUE (issuer, provider_subject, account_id),
    CONSTRAINT core_identity_account_fk FOREIGN KEY (account_id) REFERENCES accounts(account_id)
);

CREATE TABLE app_bindings (
    app_id BYTEA NOT NULL,
    client_id BYTEA NOT NULL,
    redirect_uri BYTEA NOT NULL,
    PRIMARY KEY (app_id, client_id, redirect_uri)
);

CREATE TABLE login_transactions (
    app_id BYTEA NOT NULL DEFAULT convert_to(current_setting('jesuslife.auth_app_id', true), 'UTF8'),
    state_hash BYTEA NOT NULL PRIMARY KEY,
    browser_binding_hash BYTEA NOT NULL,
    nonce_hash BYTEA NOT NULL,
    verifier_ciphertext BYTEA NOT NULL,
    key_version SMALLINT NOT NULL,
    client_id BYTEA NOT NULL,
    redirect_uri BYTEA NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP(6) NOT NULL,
    expires_at TIMESTAMP(6) NOT NULL,
    consumed_at TIMESTAMP(6) NULL,
    FOREIGN KEY (app_id, client_id, redirect_uri) REFERENCES app_bindings(app_id, client_id, redirect_uri),
    CONSTRAINT core_login_status CHECK (status IN ('pending', 'exchanging', 'completed', 'failed')),
    CONSTRAINT core_login_expiry CHECK (expires_at > created_at)
);

CREATE TABLE app_sessions (
    session_id VARCHAR(36) NOT NULL PRIMARY KEY,
    account_id VARCHAR(36) NOT NULL,
    issuer BYTEA NOT NULL,
    provider_subject BYTEA NOT NULL,
    client_id BYTEA NOT NULL,
    app_id BYTEA NOT NULL,
    cookie_hash BYTEA NOT NULL,
    csrf_hash BYTEA NOT NULL,
    account_security_version BIGINT NOT NULL,
    version BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMP(6) NOT NULL,
    expires_at TIMESTAMP(6) NOT NULL,
    revoked_at TIMESTAMP(6) NULL,
    UNIQUE (cookie_hash),
    CONSTRAINT core_session_account_fk FOREIGN KEY (account_id) REFERENCES accounts(account_id),
    CONSTRAINT core_session_identity_fk FOREIGN KEY (issuer, provider_subject, account_id)
        REFERENCES external_identities(issuer, provider_subject, account_id),
    CONSTRAINT core_session_expiry CHECK (expires_at > created_at)
);

CREATE TABLE session_access_tokens (
    fingerprint BYTEA NOT NULL PRIMARY KEY,
    fingerprint_key_version SMALLINT NOT NULL,
    session_id VARCHAR(36) NOT NULL,
    jwt_ciphertext BYTEA NOT NULL,
    encryption_key_version SMALLINT NOT NULL,
    issued_at TIMESTAMP(6) NOT NULL,
    expires_at TIMESTAMP(6) NOT NULL,
    CONSTRAINT core_token_session_fk FOREIGN KEY (session_id) REFERENCES app_sessions(session_id),
    CONSTRAINT core_token_expiry CHECK (expires_at > issued_at)
);

CREATE TABLE product_consents (
    account_id VARCHAR(36) NOT NULL,
    product BYTEA NOT NULL,
    purpose BYTEA NOT NULL,
    policy_version BYTEA NOT NULL,
    generation BIGINT NOT NULL,
    granted_at TIMESTAMP(6) NOT NULL,
    revoked_at TIMESTAMP(6) NULL,
    PRIMARY KEY (account_id, product, purpose),
    CONSTRAINT core_consent_account_fk FOREIGN KEY (account_id) REFERENCES accounts(account_id)
);



INSERT INTO core_schema_version VALUES (1, timezone('UTC', CURRENT_TIMESTAMP));
GRANT USAGE ON SCHEMA jl_core_auth TO jl_core_auth_runtime;
GRANT SELECT ON core_schema_version, app_bindings TO jl_core_auth_runtime;
GRANT SELECT, INSERT ON accounts, external_identities, session_access_tokens TO jl_core_auth_runtime;
GRANT UPDATE (account_id) ON accounts TO jl_core_auth_runtime;
GRANT SELECT, INSERT, UPDATE ON login_transactions, app_sessions, product_consents TO jl_core_auth_runtime;

-- The broker necessarily resolves common identity before an account is known.
-- Only this internal runtime may read common accounts/identity metadata.
-- This is NOT the product API role, a client credential, or a migration role.
ALTER TABLE accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE accounts FORCE ROW LEVEL SECURITY;
CREATE POLICY broker_accounts ON accounts TO jl_core_auth_runtime USING (true) WITH CHECK (true);
ALTER TABLE external_identities ENABLE ROW LEVEL SECURITY;
ALTER TABLE external_identities FORCE ROW LEVEL SECURITY;
CREATE POLICY broker_identities ON external_identities TO jl_core_auth_runtime USING (true) WITH CHECK (true);

ALTER TABLE login_transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE login_transactions FORCE ROW LEVEL SECURITY;
CREATE POLICY app_login ON login_transactions TO jl_core_auth_runtime
 USING (app_id = convert_to(current_setting('jesuslife.auth_app_id', true), 'UTF8'))
 WITH CHECK (app_id = convert_to(current_setting('jesuslife.auth_app_id', true), 'UTF8'));
ALTER TABLE app_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_sessions FORCE ROW LEVEL SECURITY;
CREATE POLICY app_session ON app_sessions TO jl_core_auth_runtime
 USING (app_id = convert_to(current_setting('jesuslife.auth_app_id', true), 'UTF8'))
 WITH CHECK (app_id = convert_to(current_setting('jesuslife.auth_app_id', true), 'UTF8'));
ALTER TABLE session_access_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE session_access_tokens FORCE ROW LEVEL SECURITY;
CREATE POLICY app_token ON session_access_tokens TO jl_core_auth_runtime
 USING (EXISTS (SELECT 1 FROM app_sessions s WHERE s.session_id=session_access_tokens.session_id))
 WITH CHECK (EXISTS (SELECT 1 FROM app_sessions s WHERE s.session_id=session_access_tokens.session_id));
ALTER TABLE product_consents ENABLE ROW LEVEL SECURITY;
ALTER TABLE product_consents FORCE ROW LEVEL SECURITY;
CREATE POLICY app_consent ON product_consents TO jl_core_auth_runtime
 USING (product = convert_to(current_setting('jesuslife.auth_app_id', true), 'UTF8'))
 WITH CHECK (product = convert_to(current_setting('jesuslife.auth_app_id', true), 'UTF8'));
RESET ROLE;
