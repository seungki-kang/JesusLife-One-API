
CREATE SCHEMA ld_backup_race;
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
LANGUAGE sql AS $$
    INSERT INTO ld_backup_race.backup_consent AS c (owner_id, generation, active)
    VALUES (p_owner, 1, true)
    ON CONFLICT (owner_id) DO UPDATE
    SET generation = c.generation + CASE WHEN c.active THEN 0 ELSE 1 END,
        active = true
    RETURNING generation;
$$;

CREATE FUNCTION ld_backup_race.save_backup(
    p_owner uuid, p_generation bigint, p_entry uuid, p_ciphertext bytea
) RETURNS text LANGUAGE plpgsql AS $$
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
RETURNS boolean LANGUAGE plpgsql AS $$
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

GRANT USAGE ON SCHEMA ld_backup_race TO jl_ld_auth_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA ld_backup_race TO jl_ld_auth_runtime;
