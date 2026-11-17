-- Apply as administrator in one transaction in an isolated development database.
-- Provision jl_migration_owner and a dedicated jl_ld_auth_runtime role first.
CREATE SCHEMA jl_ld_auth AUTHORIZATION jl_migration_owner;
SET LOCAL ROLE jl_migration_owner;
SET LOCAL search_path TO jl_ld_auth, pg_catalog;
REVOKE ALL ON SCHEMA jl_ld_auth FROM PUBLIC;
CREATE TABLE core_schema_version (
    version INT NOT NULL PRIMARY KEY,
    applied_at TIMESTAMP(6) NOT NULL
);

CREATE TABLE accounts (
    account_id VARCHAR(36) NOT NULL PRIMARY KEY,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    security_version BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMP(6) NOT NULL,
    CONSTRAINT core_account_status CHECK (status IN ('active', 'disabled'))
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

CREATE TABLE login_transactions (
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
    CONSTRAINT core_login_status CHECK (status IN ('pending', 'exchanging', 'completed', 'failed')),
    CONSTRAINT core_login_expiry CHECK (expires_at > created_at)
);

CREATE TABLE app_sessions (
    session_id VARCHAR(36) NOT NULL PRIMARY KEY,
    account_id VARCHAR(36) NOT NULL,
    issuer BYTEA NOT NULL,
    provider_subject BYTEA NOT NULL,
    client_id BYTEA NOT NULL,
    app_id BYTEA,
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


CREATE TABLE mobile_schema_version (version INT NOT NULL PRIMARY KEY);
CREATE TABLE mobile_logins (
 state_hash BYTEA NOT NULL PRIMARY KEY,
 transaction_id VARCHAR(36) NOT NULL UNIQUE,
 challenge BYTEA NOT NULL,
 app_id BYTEA,
 client_id BYTEA,
 return_uri BYTEA NOT NULL,
 browser_ciphertext BYTEA NULL,
 handoff_hash BYTEA NULL UNIQUE,
 credential_ciphertext BYTEA NULL,
 account_id VARCHAR(36) NULL,
 expires_at TIMESTAMP(6) NOT NULL,
 consumed_at TIMESTAMP(6) NULL
);

INSERT INTO core_schema_version VALUES (1, timezone('UTC', CURRENT_TIMESTAMP));
INSERT INTO mobile_schema_version VALUES (1);
GRANT USAGE ON SCHEMA jl_ld_auth TO jl_ld_auth_runtime;
GRANT SELECT ON core_schema_version, mobile_schema_version, product_consents TO jl_ld_auth_runtime;
GRANT SELECT, INSERT ON external_identities, session_access_tokens TO jl_ld_auth_runtime;
GRANT SELECT, INSERT, UPDATE ON login_transactions, mobile_logins, app_sessions TO jl_ld_auth_runtime;
GRANT SELECT, INSERT ON accounts TO jl_ld_auth_runtime;
-- Row locking requires UPDATE privilege on at least one column.
GRANT UPDATE (account_id) ON accounts TO jl_ld_auth_runtime;
RESET ROLE;
