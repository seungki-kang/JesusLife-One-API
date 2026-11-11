-- Apply only after reviewing backup/restore rollout and DB privileges.
USE platform_core;
CREATE TABLE nn_mobile_backups (
 account_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 generation BIGINT UNSIGNED NOT NULL,
 revision BIGINT UNSIGNED NOT NULL,
 envelope MEDIUMBLOB NOT NULL,
 PRIMARY KEY (account_id, generation),
 CONSTRAINT nn_mobile_backup_account FOREIGN KEY (account_id) REFERENCES accounts(account_id)
) ENGINE=InnoDB;
