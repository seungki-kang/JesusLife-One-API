"""Local One API login and completed diary backup rehearsal."""
import argparse
import base64
import binascii
from contextlib import closing
from pathlib import Path
import subprocess
import sys
from uuid import UUID, uuid4

import psycopg
from dotenv import dotenv_values
from psycopg.conninfo import conninfo_to_dict
from fastapi import APIRouter, HTTPException, Request, Response
import uvicorn

# This script is launched with the upload review worktree as its cwd.
sys.path.insert(0, str(Path.cwd()))
from app.core.life_diary_login import PREFIX
from app.modules.life_diary.backup_rehearsal import BackupPayload
from app.modules.neorang_narang.router import SafeValidationRoute
from scripts.auth0_pc_settings import validate
from scripts.life_diary_postgres_relay_dev import build_postgres_app

CONTAINER = 'jl-life-diary-postgres-dev'
ROLE = 'jl_ld_auth_runtime'
SCHEMA = 'ld_backup_race'

def docker(*args, input_text=None):
    subprocess.run(['docker', 'exec', '-i', CONTAINER, *args], input=input_text,
                   text=True, check=True, timeout=30)


def connect(dsn, database):
    conn = psycopg.connect(dsn, dbname=database, connect_timeout=5,
                           options='-c statement_timeout=10000')
    if (conn.info.dbname, conn.info.user) != (database, ROLE):
        conn.close()
        raise RuntimeError('Unexpected PostgreSQL session')
    return conn


def scalar(conn, sql, params=()):
    return conn.execute(sql, params).fetchone()[0]



def backup_router(authenticated_owner, dsn, database):
    router = APIRouter(prefix=PREFIX + '/backup', route_class=SafeValidationRoute)

    @router.put('/entries/{generation}/{entry_id}')
    def upload(generation: int, entry_id: UUID, payload: BackupPayload, request: Request, response: Response):
        owner = authenticated_owner(request)
        if not 1 <= generation <= 9223372036854775807:
            raise HTTPException(422, 'Invalid backup generation')
        try:
            ciphertext = base64.b64decode(payload.ciphertext, validate=True)
        except (ValueError, binascii.Error):
            raise HTTPException(422, 'Invalid backup encoding') from None
        if base64.b64encode(ciphertext).decode('ascii') != payload.ciphertext:
            raise HTTPException(422, 'Invalid backup encoding')
        with closing(connect(dsn, database)) as conn, conn.transaction():
            conn.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
            status = scalar(conn, f'SELECT {SCHEMA}.save_backup(%s, %s, %s, %s)',
                            (owner, generation, entry_id, ciphertext))
            if status == 'denied':
                raise HTTPException(403, 'Backup consent is inactive or stale')
            if status == 'conflict':
                raise HTTPException(409, 'Backup entry already exists')
            if status not in ('created', 'replay'):
                raise HTTPException(503, 'Backup storage unavailable')
        response.status_code = 201 if status == 'created' else 200
        return {'result': status}

    @router.get('/entries/{generation}/{entry_id}')
    def download(generation: int, entry_id: UUID, request: Request, response: Response):
        owner = authenticated_owner(request)
        if not 1 <= generation <= 9223372036854775807:
            raise HTTPException(422, 'Invalid backup generation')
        with closing(connect(dsn, database)) as conn:
            row = conn.execute(
                f'''SELECT e.ciphertext FROM {SCHEMA}.backup_entries AS e
                    JOIN {SCHEMA}.backup_consent AS c
                    USING (owner_id, generation)
                    WHERE e.owner_id = %s AND e.generation = %s
                      AND e.entry_id = %s AND c.active''',
                (owner, generation, entry_id),
            ).fetchone()
        if row is None:
            raise HTTPException(404, 'Backup entry unavailable')
        response.headers['Cache-Control'] = 'no-store'
        return {'format_version': 1, 'ciphertext': base64.b64encode(row[0]).decode('ascii')}

    @router.delete('/consent/{generation}', status_code=204)
    def withdraw(generation: int, request: Request):
        owner = authenticated_owner(request)
        if not 1 <= generation <= 9223372036854775807:
            raise HTTPException(422, 'Invalid backup generation')
        with closing(connect(dsn, database)) as conn, conn.transaction():
            conn.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
            scalar(conn, f'SELECT {SCHEMA}.withdraw_backup(%s, %s)', (owner, generation))
        return Response(status_code=204)

    return router


def install_backup(app, dsn, database):
    authenticate = getattr(app.state, 'life_diary_backup_owner', None)
    if not callable(authenticate):
        raise RuntimeError('Apply the Life Diary backup authentication adapter first')

    app.include_router(backup_router(authenticate, dsn, database))

    @app.post(PREFIX + '/backup/consent')
    def grant(request: Request, response: Response):
        user = authenticate(request)
        with closing(connect(dsn, database)) as conn, conn.transaction():
            generation = scalar(conn, f'SELECT {SCHEMA}.grant_backup(%s)', (user,))
        response.headers['Cache-Control'] = 'no-store'
        return {'generation': generation}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings', type=Path, required=True)
    parser.add_argument('--pc-settings', type=Path, required=True)
    parser.add_argument('--postgres-settings', type=Path, required=True)
    args = parser.parse_args()
    settings = dotenv_values(args.settings, interpolate=False)
    pc_config = validate(dotenv_values(args.pc_settings, interpolate=False))
    dsn = dotenv_values(args.postgres_settings, interpolate=False).get('JESUSLIFE_LD_AUTH_POSTGRES_DSN')
    if not dsn:
        raise SystemExit('Local PostgreSQL setting is missing')
    try:
        dsn_config = conninfo_to_dict(dsn)
    except psycopg.ProgrammingError:
        raise SystemExit('Invalid local PostgreSQL setting') from None
    expected = {'host': '127.0.0.1', 'port': '15432', 'user': ROLE, 'dbname': 'ld_auth_dev'}
    if any(dsn_config.get(key) != value for key, value in expected.items()) or {'hostaddr', 'service'} & dsn_config.keys():
        raise SystemExit('Unexpected PostgreSQL test target')

    app = build_postgres_app(settings, pc_config, dsn)
    database = 'ld_backup_entry_' + uuid4().hex
    docker('createdb', '-U', 'postgres', database)
    try:
        docker('psql', '-X', '-U', 'postgres', '-d', database, '-v', 'ON_ERROR_STOP=1',
               '--single-transaction', '-f', '-', input_text=DDL)
        install_backup(app, dsn, database)
        uvicorn.run(app, host='127.0.0.1', port=18000, access_log=False,
                    proxy_headers=False)
    finally:
        docker('dropdb', '-U', 'postgres', database)
    print('Temporary Android backup database removed')


DDL = """
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
"""


if __name__ == '__main__':
    main()
