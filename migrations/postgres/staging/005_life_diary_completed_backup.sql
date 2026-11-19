-- Apply in a single transaction as the staging migrator.
-- Requires jl_migration_owner and jl_ld_auth_runtime. This migration creates
-- a dedicated schema and fails if an existing schema has the same name.
CREATE SCHEMA ld_backup_race AUTHORIZATION jl_migration_owner;
SET LOCAL ROLE jl_migration_owner;
REVOKE ALL ON SCHEMA ld_backup_race FROM PUBLIC;
CREATE TABLE ld_backup_race.backup_consent (
    owner_id uuid PRIMARY KEY,
    generation bigint NOT NULL CHECK (generation > 0),
    active boolean NOT NULL
);

CREATE TABLE ld_backup_race.backup_entries (
    owner_id uuid NOT NULL,
    generation bigint NOT NULL,
    entry_id uuid NOT NULL,
    ciphertext bytea NOT NULL,
    PRIMARY KEY (owner_id, generation, entry_id)
);

CREATE FUNCTION ld_backup_race.grant_backup(p_owner uuid) RETURNS bigint
LANGUAGE sql SET search_path TO pg_catalog, pg_temp AS $$
    INSERT INTO ld_backup_race.backup_consent AS c (owner_id, generation, active)
    VALUES (p_owner, 1, true)
    ON CONFLICT (owner_id) DO UPDATE
    SET generation = c.generation + CASE WHEN c.active THEN 0 ELSE 1 END,
        active = true
    RETURNING generation;
$$;

CREATE FUNCTION ld_backup_race.save_backup(
    p_owner uuid, p_generation bigint, p_entry uuid, p_ciphertext bytea
) RETURNS text LANGUAGE plpgsql SET search_path TO pg_catalog, pg_temp AS $$
DECLARE
    consent ld_backup_race.backup_consent%ROWTYPE;
    existing bytea;
BEGIN
    SELECT * INTO consent FROM ld_backup_race.backup_consent
    WHERE owner_id = p_owner FOR UPDATE;
    IF NOT FOUND OR NOT consent.active OR consent.generation <> p_generation THEN
        RETURN 'denied';
    END IF;

    INSERT INTO ld_backup_race.backup_entries
    VALUES (p_owner, p_generation, p_entry, p_ciphertext)
    ON CONFLICT DO NOTHING;
    IF FOUND THEN
        RETURN 'created';
    END IF;

    SELECT ciphertext INTO existing FROM ld_backup_race.backup_entries
    WHERE owner_id = p_owner AND generation = p_generation AND entry_id = p_entry;
    IF existing = p_ciphertext THEN
        RETURN 'replay';
    END IF;
    RETURN 'conflict';
END;
$$;

CREATE FUNCTION ld_backup_race.withdraw_backup(p_owner uuid, p_generation bigint)
RETURNS boolean LANGUAGE plpgsql SET search_path TO pg_catalog, pg_temp AS $$
BEGIN
    UPDATE ld_backup_race.backup_consent SET active = false
    WHERE owner_id = p_owner AND generation = p_generation AND active;
    IF NOT FOUND THEN
        RETURN false;
    END IF;
    DELETE FROM ld_backup_race.backup_entries
    WHERE owner_id = p_owner AND generation = p_generation;
    RETURN true;
END;
$$;

REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA ld_backup_race FROM PUBLIC;
GRANT USAGE ON SCHEMA ld_backup_race TO jl_ld_auth_runtime;
GRANT SELECT, INSERT, UPDATE ON ld_backup_race.backup_consent TO jl_ld_auth_runtime;
GRANT SELECT, INSERT, DELETE ON ld_backup_race.backup_entries TO jl_ld_auth_runtime;
GRANT EXECUTE ON FUNCTION ld_backup_race.grant_backup(uuid),
    ld_backup_race.save_backup(uuid, bigint, uuid, bytea),
    ld_backup_race.withdraw_backup(uuid, bigint) TO jl_ld_auth_runtime;
ALTER TABLE ld_backup_race.backup_consent ENABLE ROW LEVEL SECURITY;
ALTER TABLE ld_backup_race.backup_entries ENABLE ROW LEVEL SECURITY;

CREATE POLICY backup_consent_one_api
ON ld_backup_race.backup_consent
TO jl_ld_auth_runtime
USING (true)
WITH CHECK (true);

CREATE POLICY backup_entries_one_api
ON ld_backup_race.backup_entries
TO jl_ld_auth_runtime
USING (true)
WITH CHECK (true);

RESET ROLE;
