-- Separate product table; no changes to existing completion records/versions.
-- Runner validates both databases before target DDL. Retained UUID barriers
-- prevent erased generations from being replayed as newly consented records.
USE neorang_narang;
CREATE TABLE nn_mobile_synthetic (
 sync_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
 owner_sub CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 generation BIGINT UNSIGNED NOT NULL,
 metadata JSON NULL,
 erased BOOLEAN NOT NULL DEFAULT FALSE,
 UNIQUE KEY nn_mobile_one_per_generation (owner_sub,generation)
) ENGINE=InnoDB;
-- After shape/backup review, grant platform_core_app SELECT,INSERT,UPDATE on
-- this table only. The product adapter uses the Core connection/unit of work.
