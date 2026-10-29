CREATE TABLE IF NOT EXISTS nn_schema_version (
    version INT NOT NULL PRIMARY KEY,
    applied_at DATETIME(6) NOT NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS nn_completion_owners (
    owner_sub CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS nn_completion_records (
    owner_sub CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    record_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    course_number TINYINT NOT NULL,
    participation_mode VARCHAR(8) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    completed_at DATETIME(6) NOT NULL,
    revision BIGINT UNSIGNED NOT NULL,
    deleted_at DATETIME(6) NULL,
    updated_at DATETIME(6) NOT NULL,
    delete_base BIGINT UNSIGNED NULL,
    PRIMARY KEY (owner_sub, record_id),
    CONSTRAINT nn_record_owner FOREIGN KEY (owner_sub) REFERENCES nn_completion_owners(owner_sub),
    CONSTRAINT nn_course CHECK (course_number IN (1, 2)),
    CONSTRAINT nn_mode CHECK (participation_mode IN ('solo', 'together')),
    CONSTRAINT nn_revision CHECK (revision >= 1),
    CONSTRAINT nn_delete CHECK (
        (deleted_at IS NULL AND delete_base IS NULL) OR
        (deleted_at IS NOT NULL AND delete_base IS NOT NULL AND revision = delete_base + 1)
    )
) ENGINE=InnoDB;

INSERT INTO nn_schema_version (version, applied_at)
VALUES (1, UTC_TIMESTAMP(6)) ON DUPLICATE KEY UPDATE version=version;
