"""Explicit Supabase development probe/server. Never loaded by the existing PC app."""
import argparse
from getpass import getpass
import os
from pathlib import Path
import re

from dotenv import dotenv_values
import psycopg

from app.core.database import ROOT
from app.core.postgres import PostgresConnectionError

DIRECTORY = ROOT / '.env.churchos-supabase-dev'
SETTINGS = DIRECTORY / 'settings.env'
CERTIFICATE = DIRECTORY / 'project-ca.crt'
ENABLED = 'JESUSLIFE_SUPABASE_DEV_ENABLED'


def membership_connector(values, password, *, driver=None):
    """No connection until called; no DSN, service file or inherited libpq options."""
    if values.get(ENABLED) != '1':
        raise ValueError('Supabase development verification is not enabled')
    host, reference = values.get('POOLER_HOST', ''), values.get('PROJECT_REF', '')
    certificate = Path(values.get('SSLROOTCERT') or CERTIFICATE)
    if (values.get('PROJECT_NAME') != 'jesuslife-api-dev'
            or not re.fullmatch(r'aws-[0-9]+-[a-z0-9-]+\.pooler\.supabase\.com', host)
            or not re.fullmatch(r'[a-z0-9]{20}', reference)
            or not certificate.is_absolute() or not certificate.is_file()
            or not password):
        raise ValueError('Invalid Supabase development settings')
    connect_driver = psycopg.connect if driver is None else driver

    def connect():
        if any(key.upper().startswith('PG') for key in os.environ):
            raise PostgresConnectionError('PostgreSQL environment is not isolated')
        try:
            db = connect_driver(
                host=host, port=5432, dbname='postgres',
                user='jl_churchos_dev_login.' + reference, password=password,
                sslmode='verify-full', sslrootcert=str(certificate),
                connect_timeout=5, application_name='jesuslife_churchos_dev_read',
                options='-c default_transaction_read_only=on -c statement_timeout=5000',
                prepare_threshold=None,
            )
        except Exception:
            raise PostgresConnectionError('Supabase development connection failed') from None
        try:
            db.read_only = True
            row = db.execute(
                "SELECT current_user = 'jl_churchos_dev_login', "
                "NOT rolsuper AND NOT rolbypassrls, "
                "NOT has_table_privilege(current_user, 'jl_churchos.memberships', "
                "'INSERT,UPDATE,DELETE,TRUNCATE'), "
                "has_table_privilege(current_user, 'jl_churchos.memberships', 'SELECT'), "
                "c.relrowsecurity AND c.relforcerowsecurity, "
                "current_setting('transaction_read_only') = 'on' "
                "FROM pg_roles r CROSS JOIN pg_class c "
                "WHERE r.rolname=current_user AND c.oid='jl_churchos.memberships'::regclass"
            ).fetchone()
            if row != (True,) * 6:
                raise ValueError('Read-only role or RLS check failed')
            db.rollback()
            return db
        except Exception:
            try:
                db.close()
            except Exception:
                pass
        raise PostgresConnectionError('Supabase read-only role or RLS check failed')

    return connect


def prepare():
    from scripts.local_mysql import protect
    DIRECTORY.mkdir(exist_ok=True)
    protect(DIRECTORY)
    with SETTINGS.open('x', encoding='utf-8') as output:
        protect(SETTINGS)
        output.write(f'{ENABLED}=0\nPROJECT_NAME=jesuslife-api-dev\n'
                     'POOLER_HOST=\nPROJECT_REF=\n'
                     f'SSLROOTCERT={CERTIFICATE.as_posix()}\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'probe', 'serve'))
    args = parser.parse_args()
    try:
        if args.action == 'prepare':
            prepare()
            print('PASS: protected settings prepared; verification disabled')
            return
        values = dotenv_values(SETTINGS, interpolate=False)
        if values.get(ENABLED) != '1':
            raise ValueError('Disabled')
        connect = membership_connector(values, getpass('jl_churchos_dev_login password (hidden): '))
        with connect() as db:
            if db.execute('SELECT 1').fetchone() != (1,):
                raise ValueError('Probe failed')
        print('PASS: Session pooler TLS and read-only role/RLS checks')
        if args.action == 'serve':
            # Import existing PC code only in this explicit command. Its configuration
            # and local Core persistence are preserved, never rewritten here.
            from app.auth0_pc import PcRuntime, create_app
            from scripts.auth0_pc_settings import PATH, validate
            from scripts.churchos_supabase_http import install_verification
            import uvicorn
            runtime = PcRuntime(validate(dotenv_values(PATH, interpolate=False)))
            app = create_app(runtime, church_membership_connect=connect)
            install_verification(app, runtime)
            uvicorn.run(app, host='127.0.0.1', port=8000, access_log=False,
                        log_level='critical')
    except (Exception, KeyboardInterrupt):
        print('BLOCKED: development verification unavailable; details suppressed')
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
