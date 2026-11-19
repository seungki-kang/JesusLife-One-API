"""Local One API login and completed diary backup rehearsal."""
import argparse
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import psycopg
from dotenv import dotenv_values
from psycopg.conninfo import conninfo_to_dict
import uvicorn

# This script is launched with the upload review worktree as its cwd.
sys.path.insert(0, str(Path.cwd()))
from app.modules.life_diary.completed_backup_routes import create_completed_backup_router
from scripts.auth0_pc_settings import validate
from scripts.life_diary_postgres_relay_dev import build_postgres_app

CONTAINER = 'jl-life-diary-postgres-dev'
ROLE = 'jl_ld_auth_runtime'
BACKUP_MIGRATION = (Path(__file__).resolve().parents[1]
                    / 'migrations/postgres/rehearsal/005_life_diary_completed_backup.sql')

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


def install_backup(app, dsn, database):
    authenticate = getattr(app.state, 'life_diary_backup_owner', None)
    if not callable(authenticate):
        raise RuntimeError('Apply the Life Diary backup authentication adapter first')

    app.include_router(
        create_completed_backup_router(authenticate, lambda: connect(dsn, database))
    )


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

    ddl = BACKUP_MIGRATION.read_text(encoding='utf-8')
    app = build_postgres_app(settings, pc_config, dsn)
    database = 'ld_backup_entry_' + uuid4().hex
    docker('createdb', '-U', 'postgres', database)
    try:
        docker('psql', '-X', '-U', 'postgres', '-d', database, '-v', 'ON_ERROR_STOP=1',
               '--single-transaction', '-f', '-', input_text=ddl)
        install_backup(app, dsn, database)
        uvicorn.run(app, host='127.0.0.1', port=18000, access_log=False,
                    proxy_headers=False)
    finally:
        docker('dropdb', '-U', 'postgres', database)
    print('Temporary Android backup database removed')



if __name__ == '__main__':
    main()
