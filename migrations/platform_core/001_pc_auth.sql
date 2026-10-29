-- Approved local Core schema. Execute only through scripts.core_mysql.
-- Target: separate platform_core DB on approved local MySQL 127.0.0.1:3307.
-- Administrative runner must verify selected DB, acquire migration lock,
-- reject unknown/future schema versions, and inspect existing table shape.
-- No changes to neorang_narang, life_diary, MariaDB or existing owners.
USE platform_core;

CREATE TABLE IF NOT EXISTS core_schema_version (
    version INT NOT NULL PRIMARY KEY,
    applied_at DATETIME(6) NOT NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS accounts (
    account_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    status VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'active',
    security_version BIGINT UNSIGNED NOT NULL DEFAULT 0,
    created_at DATETIME(6) NOT NULL,
    CONSTRAINT core_account_status CHECK (status IN ('active', 'disabled'))
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS external_identities (
    issuer VARBINARY(512) NOT NULL,
    provider_subject VARBINARY(1020) NOT NULL,
    account_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (issuer, provider_subject),
    UNIQUE KEY core_identity_account_binding (issuer, provider_subject, account_id),
    KEY core_identity_account (account_id),
    CONSTRAINT core_identity_account_fk FOREIGN KEY (account_id) REFERENCES accounts(account_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS login_transactions (
    state_hash BINARY(32) NOT NULL PRIMARY KEY,
    browser_binding_hash BINARY(32) NOT NULL,
    nonce_hash BINARY(32) NOT NULL,
    verifier_ciphertext VARBINARY(1024) NOT NULL,
    key_version SMALLINT UNSIGNED NOT NULL,
    client_id VARBINARY(255) NOT NULL,
    redirect_uri VARBINARY(512) NOT NULL,
    status VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'pending',
    created_at DATETIME(6) NOT NULL,
    expires_at DATETIME(6) NOT NULL,
    consumed_at DATETIME(6) NULL,
    CONSTRAINT core_login_status CHECK (status IN ('pending', 'exchanging', 'completed', 'failed')),
    CONSTRAINT core_login_expiry CHECK (expires_at > created_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS app_sessions (
    session_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    account_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    issuer VARBINARY(512) NOT NULL,
    provider_subject VARBINARY(1020) NOT NULL,
    client_id VARBINARY(255) NOT NULL,
    cookie_hash BINARY(32) NOT NULL,
    csrf_hash BINARY(32) NOT NULL,
    account_security_version BIGINT UNSIGNED NOT NULL,
    version BIGINT UNSIGNED NOT NULL DEFAULT 0,
    created_at DATETIME(6) NOT NULL,
    expires_at DATETIME(6) NOT NULL,
    revoked_at DATETIME(6) NULL,
    UNIQUE KEY core_cookie_hash (cookie_hash),
    KEY core_session_account (account_id),
    CONSTRAINT core_session_account_fk FOREIGN KEY (account_id) REFERENCES accounts(account_id),
    CONSTRAINT core_session_identity_fk FOREIGN KEY (issuer, provider_subject, account_id)
        REFERENCES external_identities(issuer, provider_subject, account_id),
    CONSTRAINT core_session_expiry CHECK (expires_at > created_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS session_access_tokens (
    fingerprint BINARY(32) NOT NULL PRIMARY KEY,
    fingerprint_key_version SMALLINT UNSIGNED NOT NULL,
    session_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    jwt_ciphertext BLOB NOT NULL,
    encryption_key_version SMALLINT UNSIGNED NOT NULL,
    issued_at DATETIME(6) NOT NULL,
    expires_at DATETIME(6) NOT NULL,
    KEY core_token_session (session_id),
    CONSTRAINT core_token_session_fk FOREIGN KEY (session_id) REFERENCES app_sessions(session_id),
    CONSTRAINT core_token_expiry CHECK (expires_at > issued_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS product_consents (
    account_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    product VARBINARY(64) NOT NULL,
    purpose VARBINARY(64) NOT NULL,
    policy_version VARBINARY(64) NOT NULL,
    generation BIGINT UNSIGNED NOT NULL,
    granted_at DATETIME(6) NOT NULL,
    revoked_at DATETIME(6) NULL,
    PRIMARY KEY (account_id, product, purpose),
    CONSTRAINT core_consent_account_fk FOREIGN KEY (account_id) REFERENCES accounts(account_id)
) ENGINE=InnoDB;

-- Receipt is last. Runner must validate table shape before writing receipt.
INSERT INTO core_schema_version (version, applied_at)
SELECT 1, UTC_TIMESTAMP(6)
WHERE NOT EXISTS (SELECT 1 FROM core_schema_version WHERE version=1);
