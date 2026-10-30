-- Additive, manually approved application only. Core v1/PC tables unchanged.
-- MySQL DDL auto-commits: preserve a verified backup; retry only after inspecting
-- table shapes. Never stamp version 1 until ALL tables have the expected shape.
-- Use scripts.mobile_mysql: preflight BOTH v1/mobile schema shapes and versions
-- before target DDL. This SQL alone is not a safe retry/restore procedure.
USE platform_core;
CREATE TABLE mobile_schema_version (version INT NOT NULL PRIMARY KEY);
CREATE TABLE mobile_logins (
 state_hash BINARY(32) NOT NULL PRIMARY KEY,
 transaction_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL UNIQUE,
 challenge VARBINARY(43) NOT NULL,
 return_uri VARBINARY(512) NOT NULL,
 browser_ciphertext VARBINARY(1024) NULL,
 handoff_hash BINARY(32) NULL UNIQUE,
 credential_ciphertext VARBINARY(1024) NULL,
 account_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL,
 expires_at DATETIME(6) NOT NULL,
 consumed_at DATETIME(6) NULL
) ENGINE=InnoDB;
CREATE TABLE mobile_consents (
 account_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
 generation BIGINT UNSIGNED NOT NULL DEFAULT 0,
 active BOOLEAN NOT NULL DEFAULT FALSE,
 deletion_through BIGINT UNSIGNED NOT NULL DEFAULT 0,
 -- Historical completion is scoped to deletion_through, not a later grant.
 deletion_status VARCHAR(16) CHARACTER SET ascii NOT NULL DEFAULT 'none',
 CONSTRAINT mobile_consent_account FOREIGN KEY (account_id) REFERENCES accounts(account_id)
) ENGINE=InnoDB;
INSERT INTO mobile_schema_version VALUES (1);
